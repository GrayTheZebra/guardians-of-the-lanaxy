#!/usr/bin/env python3

import argparse
import os
import pwd
import signal
from pathlib import Path
import json
import platform
import socket
import sys
import time
from datetime import datetime

from database import Database

from config import DEFAULT_CONFIG_PATH, load_config
from events.bus import EventBus
from events.event import Event
from guardian_manager import (
    get_guardian_metadata,
    load_guardian,
    run_checks,
)
from guardian_test_ipc import GuardianTestServer
from logger import setup_logger
from mqtt_client import MqttPublisher
from state import StateStore
from topology import apply_runtime_policies
from notifications import NotificationDispatcher


APP_NAME = "Guardians of the LANaxy"
APP_SLUG = "guardians-of-the-lanaxy"
CLI_NAME = "lanaxy"
APP_VERSION = "1.0.0"

RUNTIME_STATUS_PATH = Path("/run/lanaxy/runtime.json")


def write_runtime_status(
    started_at: float,
    guardians: int,
    mqtt_connected: bool,
    last_reload: str = "",
) -> None:
    payload = {
        "pid": os.getpid(),
        "version": APP_VERSION,
        "started_at": datetime.fromtimestamp(started_at).isoformat(
            timespec="seconds"
        ),
        "uptime_seconds": int(time.time() - started_at),
        "guardians": guardians,
        "mqtt_connected": mqtt_connected,
        "last_loop": datetime.now().isoformat(timespec="seconds"),
        "last_reload": last_reload,
    }
    temporary = RUNTIME_STATUS_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, RUNTIME_STATUS_PATH)


def build_info(checks: list, started_at: float) -> dict:
    now = time.time()

    return {
        "name": APP_NAME,
        "slug": APP_SLUG,
        "cli": CLI_NAME,
        "version": APP_VERSION,
        "hostname": socket.gethostname(),
        "python": platform.python_version(),
        "guardians": len(checks),
        "started_at": datetime.fromtimestamp(started_at).isoformat(
            timespec="seconds"
        ),
        "uptime_seconds": int(now - started_at),
    }


def parse_arguments():
    parser = argparse.ArgumentParser(prog=CLI_NAME, description=APP_NAME)
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"Pfad zur Konfiguration (Standard: {DEFAULT_CONFIG_PATH})",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("run", help="LANaxy dauerhaft starten")
    subparsers.add_parser("once", help="Alle Guardians einmal ausführen")
    subparsers.add_parser("version", help="Version anzeigen")
    subparsers.add_parser("list", help="Geladene Guardians anzeigen")
    subparsers.add_parser("doctor", help="Installation und Konfiguration prüfen")

    control_parser = subparsers.add_parser(
        "control",
        help="Control Engine lokal aufrufen",
    )
    control_parser.add_argument(
        "payload",
        help="JSON-Befehl, z. B. '{\"command\":\"get_status\"}'",
    )

    return parser.parse_args()


def create_runtime(config: dict):
    lanaxy_config = config.get("lanaxy", {})
    state_file = lanaxy_config.get("state_file", "/var/lib/lanaxy/state.json")
    log_file = lanaxy_config.get("log_file", "/var/log/lanaxy.log")

    database_file = lanaxy_config.get(
        "database_file",
        "/var/lib/lanaxy/lanaxy.db",
    )

    logger = setup_logger(log_file)
    state = StateStore(state_file)
    database = Database(database_file)
    publisher = MqttPublisher(config.get("mqtt", {}))

    return logger, state, database, publisher


def execute_results(
    checks: list,
    results: list,
    state: StateStore,
    database: Database,
    publisher: MqttPublisher,
    event_bus: EventBus,
    logger,
    log_all_checks: bool = True,
):
    for check, result in zip(checks, results):
        result.details.setdefault("group", check.get("group") or "Ohne Gruppe")
        retries = int(check.get("retries", 1))

        (
            changed,
            result,
            old_status,
            new_status,
        ) = state.update_result(result, retries)

        publisher.publish_result(result)
        database.add_result(result, log_event=log_all_checks)

        line = f"{result.status.upper()}: {result.name} - {result.message}"
        print(line, flush=True)
        logger.info(line)

        if changed:
            # Stable dependency signature and strongest failing ancestor are
            # attached before incident synchronization. This lets the database
            # bundle consequential failures below one root incident.
            by_id = {str(item.get("id")): item for item in checks}
            state_checks = state.data.get("checks", {})
            dependency_chain = []
            queue = [(str(dep), 1) for dep in check.get("depends_on", [])]
            seen_dependencies = set()
            while queue:
                dependency_id, depth = queue.pop(0)
                if dependency_id in seen_dependencies:
                    continue
                seen_dependencies.add(dependency_id)
                dependency_state = state_checks.get(dependency_id, {})
                dependency_chain.append({
                    "id": dependency_id,
                    "depth": depth,
                    "status": dependency_state.get("status", "unknown"),
                })
                queue.extend(
                    (str(parent), depth + 1)
                    for parent in by_id.get(dependency_id, {}).get("depends_on", [])
                )
            failing = [
                item for item in dependency_chain
                if item["status"] in {"critical", "warning", "blocked"}
            ]
            failing.sort(key=lambda item: (
                0 if item["status"] == "critical" else 1,
                -item["depth"],
            ))
            root_cause_id = failing[0]["id"] if failing else result.id
            result.details["dependency_chain"] = dependency_chain
            result.details["root_cause_id"] = root_cause_id
            result.details["correlation_key"] = "dependency:" + root_cause_id
            event = Event(
                type="STATUS_CHANGED",
                source=result.id,
                device_id=result.device_id,
                old_status=old_status,
                new_status=new_status,
                level=result.level,
                message=(
                    f"{result.name}: {old_status} -> {new_status} - "
                    f"{result.message}"
                ),
                details=result.to_dict(),
            )

            incident = database.sync_incident(event)
            if incident:
                event.details["incident"] = incident
                event.details["incident_id"] = incident["id"]

            database.add_status_change(result, old_status, new_status)
            event_bus.emit(event)
            logger.warning(event.message)


def run_once(config: dict) -> int:
    logger, state, database, publisher = create_runtime(config)
    checks = [check for check in config.get("checks", []) if check.get("enabled", True)]
    event_bus = EventBus()
    notification_dispatcher = NotificationDispatcher(config, database)

    try:
        publisher.connect()
        event_bus.subscribe(publisher.publish_event)
        event_bus.subscribe(notification_dispatcher.handle_event)

        results = run_checks(checks)
        results = apply_runtime_policies(
            checks,
            results,
            state.data.get("checks", {}),
            config.get("maintenance_windows", []),
        )
        execute_results(
            checks,
            results,
            state,
            database,
            publisher,
            event_bus,
            logger,
            log_all_checks=bool(
                config.get("lanaxy", {}).get("log_all_checks", True)
            ),
        )
        publisher.publish_system(results)

        return 0 if all(result.level == 0 for result in results) else 1
    finally:
        publisher.disconnect()


def run_service(config: dict) -> None:
    pid_path = "/run/lanaxy/lanaxy.pid"
    os.makedirs(os.path.dirname(pid_path), exist_ok=True)
    with open(pid_path, "w", encoding="utf-8") as pid_file:
        pid_file.write(str(os.getpid()))

    reload_requested = False

    def request_reload(signum, frame):
        nonlocal reload_requested
        reload_requested = True

    signal.signal(signal.SIGHUP, request_reload)

    lanaxy_config = config.get("lanaxy", {})

    loop_interval = int(lanaxy_config.get("loop_interval", 5))
    heartbeat_interval = int(
        lanaxy_config.get("heartbeat_interval", 30)
    )
    info_interval = int(lanaxy_config.get("info_interval", 300))

    logger, state, database, publisher = create_runtime(config)
    guardian_test_server = GuardianTestServer()
    guardian_test_server.start()
    publisher.connect()

    event_bus = EventBus()
    event_bus.subscribe(publisher.publish_event)
    notification_dispatcher = NotificationDispatcher(config, database)
    event_bus.subscribe(notification_dispatcher.handle_event)

    checks = [check for check in config.get("checks", []) if check.get("enabled", True)]
    last_run: dict[str, float] = {}
    last_heartbeat = 0.0
    last_info = 0.0
    started_at = time.time()
    last_reload = ""

    guardians = get_guardian_metadata(checks)
    write_runtime_status(
        started_at,
        len(checks),
        publisher.connected.is_set(),
        last_reload,
    )

    retention_days = int(lanaxy_config.get("retention_days", 90))
    log_all_checks = bool(lanaxy_config.get("log_all_checks", True))
    last_cleanup = 0.0

    database.add_event(
        "SYSTEM_START",
        f"{APP_NAME} {APP_VERSION} gestartet",
        status="ok",
    )
    logger.info("%s %s gestartet", APP_NAME, APP_VERSION)

    try:
        while True:
            if reload_requested:
                new_config = load_config(DEFAULT_CONFIG_PATH)
                config.clear()
                config.update(new_config)
                lanaxy_config = config.get("lanaxy", {})
                loop_interval = int(
                    lanaxy_config.get("loop_interval", 5)
                )
                heartbeat_interval = int(
                    lanaxy_config.get("heartbeat_interval", 30)
                )
                info_interval = int(
                    lanaxy_config.get("info_interval", 300)
                )
                retention_days = int(
                    lanaxy_config.get("retention_days", 90)
                )
                log_all_checks = bool(
                    lanaxy_config.get("log_all_checks", True)
                )
                checks = [
                    check
                    for check in config.get("checks", [])
                    if check.get("enabled", True)
                ]
                guardians = get_guardian_metadata(checks)
                valid_ids = {check["id"] for check in checks}
                last_run = {
                    key: value
                    for key, value in last_run.items()
                    if key in valid_ids
                }
                notification_dispatcher.shutdown()
                notification_dispatcher = NotificationDispatcher(
                    config,
                    database,
                )
                event_bus = EventBus()
                event_bus.subscribe(publisher.publish_event)
                event_bus.subscribe(
                    notification_dispatcher.handle_event
                )
                last_reload = datetime.now().isoformat(
                    timespec="seconds"
                )
                reload_requested = False
                database.add_event(
                    "CONFIG_RELOAD",
                    "Konfiguration ohne Dienstneustart neu geladen",
                    status="ok",
                )
                logger.info("Konfiguration per SIGHUP neu geladen")

            now = time.time()
            write_runtime_status(
                started_at,
                len(checks),
                publisher.connected.is_set(),
                last_reload,
            )

            if now - last_heartbeat >= heartbeat_interval:
                publisher.publish_heartbeat()
                last_heartbeat = now

            if now - last_info >= info_interval:
                publisher.publish_info(build_info(checks, started_at))
                publisher.publish_guardians(guardians)
                last_info = now

            if now - last_cleanup >= 86400:
                database.cleanup(retention_days)
                last_cleanup = now

            due_checks = []

            for check in checks:
                check_id = check["id"]
                interval = int(check.get("interval", 60))
                previous = last_run.get(check_id, 0.0)

                if now - previous >= interval:
                    due_checks.append(check)
                    last_run[check_id] = now

            if due_checks:
                results = run_checks(due_checks)
                results = apply_runtime_policies(
                    due_checks,
                    results,
                    state.data.get("checks", {}),
                    config.get("maintenance_windows", []),
                )

                execute_results(
                    due_checks,
                    results,
                    state,
                    database,
                    publisher,
                    event_bus,
                    logger,
                    log_all_checks=log_all_checks,
                )
                publisher.publish_system(results)

            time.sleep(loop_interval)

    except KeyboardInterrupt:
        logger.info("%s manuell beendet", APP_NAME)

    finally:
        database.add_event(
            "SYSTEM_STOP",
            f"{APP_NAME} {APP_VERSION} gestoppt",
            level=1,
            status="warning",
        )
        notification_dispatcher.shutdown()
        guardian_test_server.stop()
        publisher.disconnect()
        RUNTIME_STATUS_PATH.unlink(missing_ok=True)
        try:
            os.unlink(pid_path)
        except FileNotFoundError:
            pass
        logger.info("%s gestoppt", APP_NAME)


def list_guardians(config: dict) -> int:
    guardians = get_guardian_metadata(config.get("checks", []))

    print(f"{APP_NAME} {APP_VERSION}\n")

    for guardian in guardians:
        status = guardian.get("status", "unknown")
        check_name = guardian.get("check_name", guardian.get("check_id"))
        guardian_name = guardian.get("name", guardian.get("id"))
        version = guardian.get("version", "?")

        print(f"[{status}] {check_name}: {guardian_name} {version}")

    return 0


def doctor(config: dict) -> int:
    errors = 0
    checks = config.get("checks", [])

    print(f"{APP_NAME} {APP_VERSION}\n")
    print("Konfiguration: OK")

    try:
        service_user = pwd.getpwnam("lanlord")
        print(
            "LANLord: OK "
            f"(UID {service_user.pw_uid}, Home {service_user.pw_dir})"
        )
    except KeyError:
        errors += 1
        print("LANLord: FEHLER - Systembenutzer lanlord fehlt")

    current_user = pwd.getpwuid(os.geteuid()).pw_name
    print(f"Ausgeführt als: {current_user}")

    log_file = config.get("lanaxy", {}).get(
        "log_file",
        "/var/log/lanaxy/lanaxy.log",
    )
    required_paths = (
        ("/etc/lanaxy/config.yaml", os.R_OK | os.W_OK),
        ("/etc/lanaxy/guardians.d", os.R_OK | os.W_OK),
        ("/etc/lanaxy/beacons.d", os.R_OK | os.W_OK),
        ("/etc/lanaxy/portals.d", os.R_OK | os.W_OK),
        ("/etc/lanaxy/backups", os.R_OK | os.W_OK),
        ("/var/lib/lanaxy", os.R_OK | os.W_OK),
        (str(Path(log_file).parent), os.R_OK | os.W_OK),
    )
    for required_path, mode in required_paths:
        if os.access(required_path, mode):
            print(f"Rechte {required_path}: OK")
        else:
            errors += 1
            print(f"Rechte {required_path}: FEHLER")

    for check in checks:
        missing_secrets = check.get("_import_missing_secrets", [])
        if missing_secrets and not check.get("enabled", True):
            print(
                f"Guardian {check.get('id', 'unknown')}: DEAKTIVIERT - "
                "Zugangsdaten fehlen: " + ", ".join(missing_secrets)
            )
            continue
        try:
            guardian = load_guardian(check)
            metadata = guardian.GUARDIAN
            print(
                f"Guardian {check['id']}: OK "
                f"({metadata['name']} {metadata['version']})"
            )
        except Exception as error:
            errors += 1
            print(f"Guardian {check.get('id', 'unknown')}: FEHLER - {error}")

    mqtt_config = config.get("mqtt", {})
    if not mqtt_config.get("enabled", False):
        print("MQTT: deaktiviert (optional)")
    else:
        publisher = MqttPublisher(mqtt_config)
        try:
            publisher.connect()
            print("MQTT: OK")
        except Exception as error:
            errors += 1
            print(f"MQTT: FEHLER - {error}")
        finally:
            try:
                publisher.disconnect()
            except Exception:
                pass

    return 0 if errors == 0 else 1


def main() -> int:
    args = parse_arguments()
    command = args.command or "run"

    if command == "version":
        print(f"{APP_NAME} {APP_VERSION}")
        return 0

    try:
        config = load_config(args.config)
    except Exception as error:
        print(f"Konfigurationsfehler: {error}", file=sys.stderr)
        return 2

    if command == "run":
        run_service(config)
        return 0
    if command == "once":
        return run_once(config)
    if command == "list":
        return list_guardians(config)
    if command == "doctor":
        return doctor(config)
    if command == "control":
        from control import ControlEngine
        try:
            payload = json.loads(args.payload)
            database = Database(
                config.get("lanaxy", {}).get(
                    "database_file",
                    "/var/lib/lanaxy/lanaxy.db",
                )
            )
            result = ControlEngine(
                args.config,
                database,
            ).execute(
                payload,
                "cli",
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("ok") else 1
        except Exception as error:
            print(f"Control-Fehler: {error}", file=sys.stderr)
            return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
