import copy
import hashlib
import difflib
import json
import os
import signal
import platform
import re
import secrets
import socket
import time
import tempfile
import uuid
import shlex
from datetime import datetime, timedelta
import subprocess
from pathlib import Path

from flask import Response
from werkzeug.datastructures import MultiDict
from database import Database
from dashboard_widgets import WIDGET_CATALOG, default_layout, normalize_layout
from topology import maintenance_active, scheduled_maintenance_for, topology_diagnostics
from notifications import load_status as load_notification_status, record_channel_result, test_channel, discover_telegram_chats
from notification_config import SECRET_PLACEHOLDER as NOTIFICATION_SECRET, beacon_catalog, build_channel, find_channel, next_name
from custom_beacons import custom_path as custom_beacon_path, delete_custom_beacon, install_source as install_beacon_source, beacon_template, validate_module_name as validate_beacon_module_name, discover_beacons

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    jsonify,
    session,
    send_file,
    url_for,
)

from config import DEFAULT_CONFIG_PATH
from lanaxy import APP_VERSION
from werkzeug.security import generate_password_hash
from custom_guardians import install_source, delete_custom_guardian, guardian_template, custom_path, validate_module_name
from guardians.proxmox_api import Guardian as ProxmoxApiGuardian
from guardians.proxmox_backup_server import Guardian as PbsGuardian
from guardian_test_ipc import test_guardian_via_service
from state import StateStore
from models.result import Result
from launchpad_help import enrich_schema
from module_manager import (
    aggregate_modules,
    find_module,
    module_in_use,
    require_compatible_version,
)
from routing_safety import analyze_config, analyze_rule, blocking_findings
from launchpad import (
    delete_mission,
    form_values,
    load_mission,
    new_mission,
    save_mission,
    store_form,
    value_list,
)
from web.security import enabled as auth_enabled, valid as auth_valid, csrf_token, verify_csrf, limited, failed, clear, verify
from i18n import SUPPORTED_LANGUAGES, localize_plugin, resolve_language, translate

# Runtime paths may be redirected for CI, containers or custom deployments.
# When LANAXY_ETC_DIR is omitted, keep the web secret next to the selected
# config file. Production therefore still defaults to /etc/lanaxy.
LANAXY_CONFIG_PATH = Path(os.environ.get("LANAXY_CONFIG", DEFAULT_CONFIG_PATH))
LANAXY_ETC_DIR = Path(
    os.environ.get("LANAXY_ETC_DIR") or LANAXY_CONFIG_PATH.parent
)
LANAXY_DATA_DIR = Path(os.environ.get("LANAXY_DATA_DIR", "/var/lib/lanaxy"))
LANAXY_LOG_DIR = Path(os.environ.get("LANAXY_LOG_DIR", "/var/log/lanaxy"))

from miniguard_manager import (
    ALL_ACTIONS as MINIGUARD_ACTIONS,
    DEFAULT_ACTION_PERMISSIONS as MINIGUARD_DEFAULT_ACTION_PERMISSIONS,
    create_agent as create_miniguard,
    delete_agent as delete_miniguard,
    enqueue_action as enqueue_miniguard_action,
    get_agent as get_miniguard,
    heartbeat as miniguard_heartbeat,
    list_agents as list_miniguards,
    poll_check as miniguard_poll_check,
    complete_check as miniguard_complete_check,
    execute_remote_check as miniguard_execute_remote_check,
    recent_tasks as miniguard_recent_tasks,
    register_agent as register_miniguard,
    set_action_permissions as set_miniguard_action_permissions,
    set_agent_enabled as set_miniguard_enabled,
    set_inventory_alias as set_miniguard_inventory_alias,
    acknowledge_inventory_changes as acknowledge_miniguard_inventory_changes,
    wait_for_task as wait_for_miniguard_task,
)
from miniguard_compat import evaluate_agent as evaluate_miniguard_compatibility, policy_for as miniguard_policy_for
from maintenance import BACKUP_DIR, create_backup, create_diagnostic_bundle, database_stats, list_backups, prune_backups, restore_backup, validate_backup
from system_health import build_health
from help_content import SELECTION_HELP, help_for_endpoint
from plugin_packages import build_package_bytes, default_manifest, default_readme, parse_package_bytes, package_metadata_for_storage, save_package_metadata, template_package
from cluster import status as cluster_status, configure as configure_cluster, create_join_token, public_snapshot as cluster_public_snapshot
from incident_intelligence import analyze_root_causes, incident_signature
from assistant_planner import pve_existing as planner_pve_existing, pbs_existing as planner_pbs_existing, build_preview as build_assistant_preview
from control import ControlEngine, generate_control_token, runtime_maintenance, verify_control_token
from control import CONTROL_COMMANDS
from custom_portals import custom_path as custom_portal_path, delete_custom_portal, discover_portals, install_source as install_portal_source, portal_template, validate_module_name as validate_portal_module_name
from portal_config import SECRET_PLACEHOLDER as PORTAL_SECRET, build_portal
from portal_manager import PortalManager
from ai_planner import AI_SECRET_PLACEHOLDER, provider_catalog as ai_provider_catalog, generate_plan as ai_generate_plan, validate_plan as ai_validate_plan, apply_plan as ai_apply_plan
from web.config_service import (
    ConfigService,
    configuration_inventory,
    prune_configuration_history,
    SECRET_PLACEHOLDER,
    build_check_from_form,
    discover_guardians,
    get_nested,
)


def _host_timezone() -> str:
    try:
        result = subprocess.run(
            ["timedatectl", "show", "--property=Timezone", "--value"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return result.stdout.strip() or "UTC"
    except Exception:
        return time.tzname[0] if time.tzname else "UTC"


def _available_timezones() -> list[str]:
    try:
        result = subprocess.run(
            ["timedatectl", "list-timezones"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        return ["UTC", "Europe/Berlin"]


def _system_helper(action: str, value: str | None = None) -> None:
    command = ["sudo", "/usr/local/sbin/lanaxy-system-helper", action]
    if value is not None:
        command.append(value)
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Systemaktion fehlgeschlagen.").strip())


def _service_active(name: str) -> bool:
    return subprocess.run(
        ["systemctl", "is-active", "--quiet", name],
        capture_output=True, timeout=5,
    ).returncode == 0


def _guardian_form_values(form, schema: dict, base: dict | None = None) -> dict:
    """Build a render-only Guardian dict from submitted values.

    This deliberately performs no validation so a failed save can render exactly
    what the user entered instead of falling back to an empty/default form.
    """
    values = copy.deepcopy(base or {})
    for key, field in schema.items():
        if key == "device_id":
            continue
        if field.get("type") == "checkbox":
            value = form.get(key) in {"1", "true", "on", "yes"}
        else:
            value = form.get(key)
            if value is None:
                continue
        parts = key.split(".")
        target = values
        for part in parts[:-1]:
            child = target.get(part)
            if not isinstance(child, dict):
                child = {}
                target[part] = child
            target = child
        target[parts[-1]] = value

    values["enabled"] = form.get("enabled") in {"1", "true", "on", "yes"}
    values["group"] = form.get("group", "")
    values["depends_on"] = list(form.getlist("depends_on"))
    return values


def create_app() -> Flask:
    app = Flask(__name__)
    secret_path = LANAXY_ETC_DIR / "web-secret"
    if not secret_path.exists():
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        secret_path.write_text(__import__("secrets").token_urlsafe(48), encoding="utf-8")
        secret_path.chmod(0o600)
    app.secret_key = secret_path.read_text(encoding="utf-8").strip()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=32 * 1024 * 1024,
    )

    @app.after_request
    def apply_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'",
        )
        if request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response

    config_path = DEFAULT_CONFIG_PATH
    backup_dir = str(LANAXY_ETC_DIR / "backups")
    state_path = LANAXY_DATA_DIR / "state.json"
    service = ConfigService(config_path, backup_dir)
    initial_config = service.load()
    database = Database(
        initial_config.get("lanaxy", {}).get(
            "database_file",
            str(LANAXY_DATA_DIR / "lanaxy.db"),
        )
    )

    control_engine = ControlEngine(config_path, database)
    portal_manager = PortalManager(
        control_engine.execute,
        lambda token: verify_control_token(service.load(), token),
    )
    portal_manager.start(initial_config)

    def terminate_service(pid_path, service_name):
        path = Path(pid_path)
        if not path.exists():
            raise RuntimeError(
                f"{service_name} PID-Datei wurde nicht gefunden."
            )
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError) as error:
            raise RuntimeError(
                f"{service_name} konnte nicht neu gestartet werden: {error}"
            ) from error

    def restart_lanaxy():
        # Reload the monitoring configuration without interrupting checks,
        # MQTT or pending notification jobs.
        path = Path("/run/lanaxy/lanaxy.pid")
        if not path.exists():
            raise RuntimeError(
                "lanaxy.service PID-Datei wurde nicht gefunden."
            )
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
            os.kill(pid, signal.SIGHUP)
        except (OSError, ValueError) as error:
            raise RuntimeError(
                "LANaxy-Konfiguration konnte nicht neu geladen werden: "
                + str(error)
            ) from error

    def schedule_restart_all():
        # Use a detached LANLord-owned helper process. It survives the web
        # process terminating itself and systemd then restarts both services.
        subprocess.Popen(
            [
                "/bin/sh",
                "-c",
                "sleep 2; "
                "test ! -f /run/lanaxy/lanaxy.pid || "
                "kill -TERM $(cat /run/lanaxy/lanaxy.pid); "
                "test ! -f /run/lanaxy/lanaxy-web.pid || "
                "kill -TERM $(cat /run/lanaxy/lanaxy-web.pid)",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def load_state():
        if not state_path.exists():
            return {"checks": {}}
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"checks": {}}

    def invalidate_guardian_state(check_id, check_name=""):
        """Discard a result that belongs to an older Guardian configuration."""
        state_store = StateStore(str(state_path))
        checks = state_store.data.setdefault("checks", {})
        old = checks.get(check_id, {})
        checks[check_id] = {
            "device_id": old.get("device_id", check_id),
            "status": "pending",
            "level": None,
            "message": (
                f"{check_name or check_id}: Konfiguration geändert – neue Prüfung steht aus"
            ),
            "last_check": "",
            "last_error": old.get("last_error", ""),
            "last_recovery": old.get("last_recovery", ""),
            "total_checks": old.get("total_checks", 0),
            "ok_checks": old.get("ok_checks", 0),
            "failed_count": 0,
            "uptime": old.get("uptime"),
            "details": {},
        }
        state_store.save()

        portal_manager.start(service.load())

    def load_runtime_status():
        runtime_path = Path("/run/lanaxy/runtime.json")
        if not runtime_path.exists():
            return {}
        try:
            return json.loads(
                runtime_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return {}

    def process_running(pid_path):
        path = Path(pid_path)
        if not path.exists():
            return False
        try:
            os.kill(
                int(path.read_text(encoding="utf-8").strip()),
                0,
            )
            return True
        except (OSError, ValueError):
            return False

    def current_language():
        return resolve_language(
            service.load(),
            request=request,
            session=session,
        )

    GUARDIAN_CATEGORY_ORDER = [
        ("network", "Netzwerk"),
        ("smart_home", "Smart Home"),
        ("system", "System"),
        ("hardware", "Hardware"),
        ("virtualization", "Virtualisierung & Container"),
        ("other", "Sonstige"),
    ]
    GUARDIAN_CATEGORY_ALIASES = {
        "network": "network",
        "netzwerk": "network",
        "smart_home": "smart_home",
        "smart home": "smart_home",
        "dienste": "smart_home",
        "system": "system",
        "storage": "system",
        "backup": "system",
        "hardware": "hardware",
        "virtualization": "virtualization",
        "virtualisierung": "virtualization",
        "container": "virtualization",
    }


    def guardian_category_key(value):
        normalized = str(value or "").strip().lower().replace("-", "_")
        return GUARDIAN_CATEGORY_ALIASES.get(normalized, "other")

    def grouped_guardians(items):
        grouped = {key: [] for key, _label in GUARDIAN_CATEGORY_ORDER}
        for item in items:
            enriched = dict(item)
            category_key = guardian_category_key(item.get("category"))
            enriched["category_key"] = category_key
            grouped[category_key].append(enriched)
        result = []
        for key, label in GUARDIAN_CATEGORY_ORDER:
            entries = sorted(grouped[key], key=lambda entry: entry.get("name", "").lower())
            if entries:
                result.append({"key": key, "label": label, "items": entries})
        return result

    def guardian_catalog():
        language = current_language()
        catalog = {}
        for item in discover_guardians():
            module_name = item["module"]
            custom_file = None
            if module_name.startswith("custom:"):
                custom_file = LANAXY_ETC_DIR / "guardians.d" / (
                    module_name.split(":", 1)[1] + ".py"
                )
            localized = localize_plugin(
                item,
                "guardians",
                module_name,
                language,
                custom_file,
            )
            if localized.get("internal"):
                continue
            schema = localized.get("schema", {})
            if "miniguard_id" in schema:
                agents = [a for a in list_miniguards() if a.get("registered") and a.get("enabled", True)]
                schema["miniguard_id"]["options"] = [
                    {"value": "", "label": "MiniGuard auswählen"},
                    *[{"value": a["id"], "label": f"{a['name']} ({'online' if a.get('online') else 'offline'})"} for a in agents],
                ]
            catalog[module_name] = localized
        return catalog

    def localized_beacon_catalog():
        language = current_language()
        catalog = {}
        for item in beacon_catalog().values():
            module_name = item["module"]
            custom_file = None
            if module_name.startswith("custom:"):
                custom_file = LANAXY_ETC_DIR / "beacons.d" / (
                    module_name.split(":", 1)[1] + ".py"
                )
            catalog[module_name] = localize_plugin(
                item,
                "beacons",
                module_name,
                language,
                custom_file,
            )
        return catalog

    def module_inventory(config=None):
        config = config or service.load()
        return aggregate_modules(
            discover_guardians(),
            discover_beacons(),
            discover_portals(),
            config,
            custom_path,
            custom_beacon_path,
            custom_portal_path,
        )

    def routing_findings(config=None):
        config = config or service.load()
        return analyze_config(
            config,
            guardian_catalog(),
            localized_beacon_catalog(),
        )

    def enforce_routing_safety(config, show_warnings=True):
        findings = routing_findings(config)
        hard_conflicts = blocking_findings(findings)
        if hard_conflicts:
            raise ValueError(
                "Unsichere Benachrichtigungsroute: "
                + hard_conflicts[0]["message"]
            )
        if show_warnings:
            for finding in findings:
                if finding.get("level") == "warning":
                    flash(
                        "Hinweis zur Benachrichtigungsroute: "
                        + finding["message"],
                        "warning",
                    )
        return findings

    def launchpad_multidict(values):
        pairs = []
        for key, value in values.items():
            if isinstance(value, list):
                pairs.extend((key, item) for item in value)
            else:
                pairs.append((key, value))
        return MultiDict(pairs)

    def launchpad_rule_from_values(
        values,
        rules,
        guardian_id,
        beacon_id,
    ):
        from notification_config import next_id

        name = str(values.get("name", "")).strip()
        if not name:
            raise ValueError("Bitte einen Namen für die Rule eingeben.")

        statuses = value_list(values, "statuses")
        if not statuses:
            raise ValueError("Mindestens einen Status auswählen.")

        all_channels = str(
            values.get("all_channels", "")
        ) == "1"
        channels = value_list(values, "channels")
        if beacon_id and not all_channels and beacon_id not in channels:
            channels.append(beacon_id)

        if not all_channels and not channels:
            raise ValueError(
                "Bitte mindestens einen Beacon für die Rule auswählen."
            )

        all_guardians = str(
            values.get("all_guardians", "")
        ) == "1"
        guardians = value_list(values, "guardians")
        if guardian_id and not all_guardians and guardian_id not in guardians:
            guardians.append(guardian_id)

        rule = {
            "id": next_id(rules, name),
            "name": name,
            "enabled": str(values.get("enabled", "1")) == "1",
            "statuses": statuses,
            "all_channels": all_channels,
            "channels": channels,
            "all_groups": str(
                values.get("all_groups", "1")
            ) == "1",
            "groups": value_list(values, "groups"),
            "all_guardians": all_guardians,
            "guardians": guardians,
            "root_cause_only": str(
                values.get("root_cause_only", "")
            ) == "1",
            "quiet_hours_enabled": str(
                values.get("quiet_hours_enabled", "")
            ) == "1",
            "quiet_start": str(
                values.get("quiet_start", "22:00")
            ),
            "quiet_end": str(
                values.get("quiet_end", "07:00")
            ),
            "delay_seconds": max(
                0,
                int(values.get("delay_seconds", 0) or 0),
            ),
            "repeat_minutes": max(
                0,
                int(values.get("repeat_minutes", 0) or 0),
            ),
            "repeat_count": max(
                0,
                int(values.get("repeat_count", 0) or 0),
            ),
            "escalation_steps": [],
        }

        for index in (1, 2):
            minutes = max(
                0,
                int(
                    values.get(
                        f"escalation_{index}_minutes",
                        0,
                    )
                    or 0
                ),
            )
            step_channels = value_list(
                values,
                f"escalation_{index}_channels",
            )
            if minutes and step_channels:
                rule["escalation_steps"].append(
                    {
                        "after_minutes": minutes,
                        "channels": step_channels,
                    }
                )

        return rule

    @app.before_request
    def protect_web():
        if request.endpoint in {
            "login",
            "static",
            "control_http_command",
            "health",
            "miniguard_register_api",
            "miniguard_heartbeat_api",
            "miniguard_next_check_api",
            "miniguard_check_result_api",
            "miniguard_install_script",
            "miniguard_agent_download",
        }:
            return None
        config = service.load()
        if not auth_valid(config):
            return redirect(url_for("login", next=request.full_path))
        if request.method == "POST":
            verify_csrf()
        return None

    def localized_portal_catalog():
        language = current_language()
        result = {}
        for item in discover_portals():
            module_name = item["module"]
            custom_file = None
            if module_name.startswith("custom:"):
                custom_file = LANAXY_ETC_DIR / "portals.d" / (
                    module_name.split(":", 1)[1] + ".py"
                )
            result[module_name] = localize_plugin(
                item,
                "portals",
                module_name,
                language,
                custom_file,
            )
        return result

    @app.context_processor
    def inject_globals():
        config = service.load()
        language = resolve_language(
            config,
            request=request,
            session=session,
        )

        def t(key, default=None, **values):
            return translate(
                language,
                key,
                default=default,
                **values,
            )

        def format_duration_seconds(value):
            try:
                total_seconds = max(0, int(float(str(value).replace(",", "."))))
            except (TypeError, ValueError):
                return str(value)

            days, remainder = divmod(total_seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)

            if days:
                parts = [f"{days} Tag" if days == 1 else f"{days} Tage"]
                if hours:
                    parts.append(f"{hours} h")
                return " ".join(parts)

            if hours:
                parts = [f"{hours} h"]
                if minutes:
                    parts.append(f"{minutes} min")
                return " ".join(parts)

            if minutes:
                parts = [f"{minutes} min"]
                if seconds:
                    parts.append(f"{seconds} s")
                return " ".join(parts)

            return f"{seconds} s"

        miniguard_compatibility_issues = []
        for miniguard_agent in list_miniguards():
            compatibility = evaluate_miniguard_compatibility(miniguard_agent, APP_VERSION)
            if miniguard_agent.get("registered") and not compatibility.get("compatible"):
                miniguard_compatibility_issues.append({
                    "id": miniguard_agent.get("id"),
                    "name": miniguard_agent.get("name") or miniguard_agent.get("hostname") or "MiniGuard",
                    **compatibility,
                })

        return {
            "app_name": "Guardians of the LANaxy",
            "app_version": APP_VERSION,
            "miniguard_compatibility_issues": miniguard_compatibility_issues,
            "csrf_token": csrf_token,
            "authentication_enabled": auth_enabled(config),
            "developer_mode": bool(config.get("web", {}).get("developer_mode", False)),
            "language": language,
            "supported_languages": SUPPORTED_LANGUAGES,
            "t": t,
            "format_duration_seconds": format_duration_seconds,
            "datetime_formats": {
                "date": config.get("web", {}).get("datetime", {}).get("date_format", "dd.mm.yyyy"),
                "time": config.get("web", {}).get("datetime", {}).get("time_format", "HH:MM:ss"),
                "datetime": config.get("web", {}).get("datetime", {}).get("datetime_format", "dd.mm.yyyy, HH:MM:ss"),
            },
            "page_help": help_for_endpoint(request.endpoint),
            "selection_help": SELECTION_HELP,
        }

    @app.get("/modules")
    def modules_page():
        config = service.load()
        modules = module_inventory(config)
        selected_type = request.args.get("type", "")
        selected_source = request.args.get("source", "")
        query = request.args.get("q", "").strip().lower()

        filtered = []
        for item in modules:
            if selected_type and item["type"] != selected_type:
                continue
            if selected_source and item["source"] != selected_source:
                continue
            haystack = " ".join(
                str(item.get(key, ""))
                for key in (
                    "name",
                    "description",
                    "author",
                    "module",
                    "category",
                )
            ).lower()
            if query and query not in haystack:
                continue
            filtered.append(item)

        return render_template(
            "modules.html",
            modules=filtered,
            total_modules=len(modules),
            custom_count=sum(
                1 for item in modules if item["source"] == "custom"
            ),
            guardian_count=sum(
                1 for item in modules if item["type"] == "guardian"
            ),
            beacon_count=sum(
                1 for item in modules if item["type"] == "beacon"
            ),
            portal_count=sum(
                1 for item in modules if item["type"] == "portal"
            ),
            selected_type=selected_type,
            selected_source=selected_source,
            query=request.args.get("q", ""),
        )

    @app.get("/modules/<module_type>/<path:module_name>")
    def module_detail(module_type, module_name):
        module = find_module(
            module_inventory(),
            module_type,
            module_name,
        )
        if module is None:
            abort(404)
        return render_template(
            "module_detail.html",
            module=module,
        )

    @app.post("/modules/install")
    def module_install():
        package_file = request.files.get("package")
        if package_file is None or not package_file.filename:
            flash("Bitte ein Modul-Paket auswählen.", "error")
            return redirect(url_for("modules_page"))

        try:
            package = parse_package_bytes(package_file.read())
            manifest = package["manifest"]
            module_type = manifest["type"]
            module_name = manifest["module"]
            overwrite = request.form.get("overwrite") == "1"
            require_compatible_version(
                "1.18.6",
                manifest.get("minimum_lanaxy_version", ""),
            )

            if module_type == "guardian":
                install_source(
                    package["source"],
                    module_name,
                    overwrite=overwrite,
                )
                plugin_file = custom_path(module_name)
            elif module_type == "beacon":
                install_beacon_source(
                    package["source"],
                    module_name,
                    overwrite=overwrite,
                )
                plugin_file = custom_beacon_path(module_name)
            elif module_type == "portal":
                install_portal_source(
                    package["source"],
                    module_name,
                    overwrite=overwrite,
                )
                plugin_file = custom_portal_path(module_name)
            else:
                raise ValueError("Unbekannter Modul-Typ.")

            save_package_metadata(
                plugin_file,
                manifest,
                package["translations"],
                package["readme"],
            )
            schedule_restart_all()
            flash(
                f"Modul „{manifest['name']}“ wurde "
                + ("aktualisiert." if overwrite else "installiert."),
                "success",
            )
        except Exception as error:
            flash(f"Modul konnte nicht installiert werden: {error}", "error")

        return redirect(url_for("modules_page"))

    @app.post("/modules/<module_type>/<path:module_name>/delete")
    def module_delete(module_type, module_name):
        config = service.load()
        module = find_module(
            module_inventory(config),
            module_type,
            module_name,
        )
        if module is None:
            abort(404)
        if module["source"] != "custom":
            flash("Integrierte Module können nicht entfernt werden.", "error")
            return redirect(url_for("module_detail", module_type=module_type, module_name=module_name))
        if module_in_use(module_type, module_name, config):
            flash(
                "Das Modul wird noch von mindestens einer Instanz verwendet.",
                "error",
            )
            return redirect(url_for("module_detail", module_type=module_type, module_name=module_name))

        try:
            file_module = module["file_module"]
            if module_type == "guardian":
                delete_custom_guardian(file_module)
            elif module_type == "beacon":
                delete_custom_beacon(file_module)
            elif module_type == "portal":
                delete_custom_portal(file_module)
            else:
                raise ValueError("Unbekannter Modul-Typ.")
            schedule_restart_all()
            flash("Modul wurde entfernt.", "success")
            return redirect(url_for("modules_page"))
        except Exception as error:
            flash(f"Modul konnte nicht entfernt werden: {error}", "error")
            return redirect(url_for("module_detail", module_type=module_type, module_name=module_name))

    @app.get("/launchpad")
    def launchpad_start():
        mission = new_mission()
        return redirect(
            url_for(
                "launchpad_guardian_select",
                mission_id=mission["id"],
            )
        )

    @app.get("/launchpad/<mission_id>/guardian")
    def launchpad_guardian_select(mission_id):
        mission = load_mission(mission_id)
        return render_template(
            "launchpad_select.html",
            mission=mission,
            step="guardian",
            step_number=1,
            title="Was möchtest du überwachen?",
            subtitle=(
                "Wähle den passenden Guardian. "
                "Die Konfiguration folgt im nächsten Schritt."
            ),
            guardian_groups=grouped_guardians(guardian_catalog().values()),
            existing=[],
            allow_none=False,
            next_endpoint="launchpad_guardian_config",
        )

    @app.route(
        "/launchpad/<mission_id>/guardian/<path:guardian_type>",
        methods=["GET", "POST"],
    )
    def launchpad_guardian_config(mission_id, guardian_type):
        mission = load_mission(mission_id)
        catalog = guardian_catalog()
        metadata = catalog.get(guardian_type)
        if metadata is None:
            abort(404)

        values = form_values(mission, "guardian")
        if request.method == "POST":
            store_form(mission, "guardian", request.form)
            mission["guardian_type"] = guardian_type
            save_mission(mission)
            return redirect(
                url_for(
                    "launchpad_beacon_select",
                    mission_id=mission_id,
                )
            )

        return render_template(
            "launchpad_schema_form.html",
            mission=mission,
            step="guardian",
            step_number=1,
            title=metadata["name"],
            subtitle=metadata.get("description", ""),
            schema=enrich_schema(metadata["schema"]),
            values=values,
            secret_placeholder=SECRET_PLACEHOLDER,
            back_url=url_for(
                "launchpad_guardian_select",
                mission_id=mission_id,
            ),
            submit_label="Weiter zu Beacons",
            extra_kind="guardian",
            return_to=return_to,
            groups=sorted({
                item.get("group")
                for item in service.load().get("checks", [])
                if item.get("group")
            }),
        )

    @app.route(
        "/launchpad/<mission_id>/beacon",
        methods=["GET", "POST"],
    )
    def launchpad_beacon_select(mission_id):
        mission = load_mission(mission_id)
        config = service.load()
        channels = config.get(
            "notifications",
            {},
        ).get("channels", [])

        if request.method == "POST":
            mode = request.form.get("mode", "none")
            mission["beacon_mode"] = mode
            mission["beacon_existing"] = request.form.get(
                "existing_id",
                "",
            )
            beacon_type = request.form.get("type", "")
            mission["beacon_type"] = beacon_type
            save_mission(mission)

            if mode == "new":
                return redirect(
                    url_for(
                        "launchpad_beacon_config",
                        mission_id=mission_id,
                        beacon_type=beacon_type,
                    )
                )
            return redirect(
                url_for(
                    "launchpad_rule_select",
                    mission_id=mission_id,
                )
            )

        return render_template(
            "launchpad_component_select.html",
            mission=mission,
            step="beacon",
            step_number=2,
            title="Wie möchtest du benachrichtigt werden?",
            subtitle=(
                "Nutze einen vorhandenen Beacon, "
                "lege einen neuen an oder überspringe den Schritt."
            ),
            existing=channels,
            types=list(localized_beacon_catalog().values()),
            selected_mode=mission.get("beacon_mode", "none"),
            selected_existing=mission.get("beacon_existing", ""),
            selected_type=mission.get("beacon_type", ""),
            back_url=url_for(
                "launchpad_guardian_config",
                mission_id=mission_id,
                guardian_type=mission.get("guardian_type", ""),
            ),
            next_label="Weiter",
        )

    @app.route(
        "/launchpad/<mission_id>/beacon/<path:beacon_type>",
        methods=["GET", "POST"],
    )
    def launchpad_beacon_config(mission_id, beacon_type):
        mission = load_mission(mission_id)
        catalog = localized_beacon_catalog()
        schema = catalog.get(beacon_type)
        if schema is None:
            abort(404)
        values = form_values(mission, "beacon")
        if request.method == "POST":
            store_form(mission, "beacon", request.form)
            mission["beacon_type"] = beacon_type
            mission["beacon_mode"] = "new"
            save_mission(mission)
            return redirect(
                url_for(
                    "launchpad_rule_select",
                    mission_id=mission_id,
                )
            )
        return render_template(
            "launchpad_schema_form.html",
            mission=mission,
            step="beacon",
            step_number=2,
            title=schema["name"],
            subtitle=schema.get("description", ""),
            schema=enrich_schema(schema["schema"]),
            values=values,
            secret_placeholder=NOTIFICATION_SECRET,
            back_url=url_for(
                "launchpad_beacon_select",
                mission_id=mission_id,
            ),
            submit_label="Weiter zu Portals",
            extra_kind="beacon",
        )

    @app.route(
        "/launchpad/<mission_id>/portal",
        methods=["GET", "POST"],
    )
    def launchpad_portal_select(mission_id):
        mission = load_mission(mission_id)
        config = service.load()
        portals = config.get("control", {}).get("portals", [])

        if request.method == "POST":
            mode = request.form.get("mode", "none")
            mission["portal_mode"] = mode
            mission["portal_existing"] = request.form.get(
                "existing_id",
                "",
            )
            portal_type = request.form.get("type", "")
            mission["portal_type"] = portal_type
            save_mission(mission)

            if mode == "new":
                return redirect(
                    url_for(
                        "launchpad_portal_config",
                        mission_id=mission_id,
                        portal_type=portal_type,
                    )
                )
            return redirect(
                url_for(
                    "launchpad_rule_select",
                    mission_id=mission_id,
                )
            )

        return render_template(
            "launchpad_component_select.html",
            mission=mission,
            step="portal",
            step_number=3,
            title="Soll LANaxy steuerbar sein?",
            subtitle=(
                "Portals sind optional. Du kannst einen vorhandenen "
                "Zugang nutzen oder einen neuen anlegen."
            ),
            existing=portals,
            types=list(localized_portal_catalog().values()),
            selected_mode=mission.get("portal_mode", "none"),
            selected_existing=mission.get("portal_existing", ""),
            selected_type=mission.get("portal_type", ""),
            back_url=url_for(
                "launchpad_beacon_select",
                mission_id=mission_id,
            ),
            next_label="Weiter",
        )

    @app.route(
        "/launchpad/<mission_id>/portal/<path:portal_type>",
        methods=["GET", "POST"],
    )
    def launchpad_portal_config(mission_id, portal_type):
        mission = load_mission(mission_id)
        catalog = localized_portal_catalog()
        schema = catalog.get(portal_type)
        if schema is None:
            abort(404)
        values = form_values(mission, "portal")
        if request.method == "POST":
            store_form(mission, "portal", request.form)
            mission["portal_type"] = portal_type
            mission["portal_mode"] = "new"
            save_mission(mission)
            return redirect(
                url_for(
                    "launchpad_rule_select",
                    mission_id=mission_id,
                )
            )
        return render_template(
            "launchpad_schema_form.html",
            mission=mission,
            step="portal",
            step_number=3,
            title=schema["name"],
            subtitle=schema.get("description", ""),
            schema=enrich_schema(schema["schema"]),
            values=values,
            secret_placeholder=PORTAL_SECRET,
            back_url=url_for(
                "launchpad_beacon_select",
                mission_id=mission_id,
            ),
            submit_label="Weiter zu Rules",
            extra_kind="portal",
        )

    @app.route(
        "/launchpad/<mission_id>/rule",
        methods=["GET", "POST"],
    )
    def launchpad_rule_select(mission_id):
        mission = load_mission(mission_id)
        config = service.load()
        rules = config.get(
            "notifications",
            {},
        ).get("rules", [])

        if request.method == "POST":
            mode = request.form.get("mode", "default")
            mission["rule_mode"] = mode
            mission["rule_existing"] = request.form.get(
                "existing_id",
                "",
            )
            save_mission(mission)

            if mode == "new":
                return redirect(
                    url_for(
                        "launchpad_rule_config",
                        mission_id=mission_id,
                    )
                )
            return redirect(
                url_for(
                    "launchpad_review",
                    mission_id=mission_id,
                )
            )

        return render_template(
            "launchpad_rule_select.html",
            mission=mission,
            step_number=4,
            rules=rules,
            selected_mode=mission.get("rule_mode", "default"),
            selected_existing=mission.get("rule_existing", ""),
            back_url=url_for(
                "launchpad_portal_select",
                mission_id=mission_id,
            ),
        )

    @app.route(
        "/launchpad/<mission_id>/rule/new",
        methods=["GET", "POST"],
    )
    def launchpad_rule_config(mission_id):
        mission = load_mission(mission_id)
        config = service.load()
        values = form_values(mission, "rule")
        if request.method == "POST":
            store_form(mission, "rule", request.form)
            mission["rule_mode"] = "new"
            save_mission(mission)
            return redirect(
                url_for(
                    "launchpad_review",
                    mission_id=mission_id,
                )
            )

        return render_template(
            "launchpad_rule_form.html",
            mission=mission,
            step_number=4,
            values=values,
            channels=config.get(
                "notifications",
                {},
            ).get("channels", []),
            checks=config.get("checks", []),
            groups=sorted({
                item.get("group")
                for item in config.get("checks", [])
                if item.get("group")
            }),
            back_url=url_for(
                "launchpad_rule_select",
                mission_id=mission_id,
            ),
        )

    @app.get("/launchpad/<mission_id>/review")
    def launchpad_review(mission_id):
        mission = load_mission(mission_id)
        config = service.load()
        guardian_meta = guardian_catalog().get(
            mission.get("guardian_type"),
            {},
        )
        beacon_meta = localized_beacon_catalog().get(
            mission.get("beacon_type"),
            {},
        )
        return render_template(
            "launchpad_review.html",
            mission=mission,
            guardian_meta=guardian_meta,
            beacon_meta=beacon_meta,
            config=config,
        )

    @app.post("/launchpad/<mission_id>/launch")
    def launchpad_finish(mission_id):
        mission = load_mission(mission_id)
        config = service.load()

        try:
            guardian_type = mission.get("guardian_type")
            guardian_metadata = guardian_catalog().get(
                guardian_type,
            )
            if guardian_metadata is None:
                raise ValueError("Guardian-Typ wurde nicht gefunden.")

            guardian = build_check_from_form(
                launchpad_multidict(
                    form_values(mission, "guardian")
                ),
                guardian_type,
                guardian_metadata["schema"],
                config=config,
            )

            checks = config.setdefault("checks", [])
            if any(
                item.get("id") == guardian["id"]
                for item in checks
            ):
                raise ValueError(
                    f"Guardian-ID bereits vorhanden: {guardian['id']}"
                )
            checks.append(guardian)

            notifications = config.setdefault(
                "notifications",
                {},
            )
            channels = notifications.setdefault("channels", [])
            rules = notifications.setdefault("rules", [])
            beacon_id = ""

            if mission.get("beacon_mode") == "existing":
                beacon_id = mission.get("beacon_existing", "")
                if not any(
                    item.get("id") == beacon_id
                    for item in channels
                ):
                    raise ValueError(
                        "Der ausgewählte Beacon existiert nicht mehr."
                    )
            elif mission.get("beacon_mode") == "new":
                beacon = build_channel(
                    launchpad_multidict(
                        form_values(mission, "beacon")
                    ),
                    mission.get("beacon_type"),
                    all_channels=channels,
                )
                channels.append(beacon)
                beacon_id = beacon["id"]

            rule_id = ""
            rule_mode = mission.get("rule_mode", "default")
            if rule_mode == "existing":
                rule_id = mission.get("rule_existing", "")
                rule = next(
                    (
                        item
                        for item in rules
                        if item.get("id") == rule_id
                    ),
                    None,
                )
                if rule is None:
                    raise ValueError(
                        "Die ausgewählte Rule existiert nicht mehr."
                    )
                if not rule.get("all_guardians", True):
                    guardian_ids = rule.setdefault("guardians", [])
                    if guardian["id"] not in guardian_ids:
                        guardian_ids.append(guardian["id"])
                if beacon_id and not rule.get(
                    "all_channels",
                    True,
                ):
                    channel_ids = rule.setdefault("channels", [])
                    if beacon_id not in channel_ids:
                        channel_ids.append(beacon_id)
            elif rule_mode == "new":
                rule = launchpad_rule_from_values(
                    form_values(mission, "rule"),
                    rules,
                    guardian["id"],
                    beacon_id,
                )
                rules.append(rule)
                rule_id = rule["id"]
            elif rule_mode == "default":
                rule = next(
                    (
                        item
                        for item in rules
                        if item.get("id") == "default_1"
                    ),
                    None,
                )
                if rule is None:
                    rule = {
                        "id": "default_1",
                        "name": "Default",
                        "enabled": True,
                        "statuses": [
                            "warning",
                            "critical",
                            "recovery",
                        ],
                        "all_channels": True,
                        "channels": [],
                        "all_groups": True,
                        "groups": [],
                        "all_guardians": True,
                        "guardians": [],
                        "root_cause_only": False,
                    }
                    rules.append(rule)
                rule_id = rule["id"]

            enforce_routing_safety(config)

            service.save(config)
            portal_manager.start(config)
            restart_lanaxy()
            delete_mission(mission_id)

            flash(
                "Launchpad abgeschlossen. Die Überwachung wurde gestartet.",
                "success",
            )
            return redirect(
                url_for(
                    "guardian_detail",
                    check_id=guardian["id"],
                )
            )
        except Exception as error:
            flash(
                f"Launchpad konnte nicht abgeschlossen werden: {error}",
                "error",
            )
            return redirect(
                url_for(
                    "launchpad_review",
                    mission_id=mission_id,
                )
            )

    @app.post("/launchpad/<mission_id>/cancel")
    def launchpad_cancel(mission_id):
        delete_mission(mission_id)
        flash("Launchpad-Mission wurde verworfen.", "success")
        return redirect(url_for("dashboard"))

    def health_payload():
        try:
            config = service.load()
            return build_health(
                app_version=APP_VERSION,
                config=config,
                runtime=load_runtime_status(),
                state=load_state().get("checks", {}),
                agents=list_miniguards(),
                monitoring_running=process_running("/run/lanaxy/lanaxy.pid"),
                web_running=process_running("/run/lanaxy/lanaxy-web.pid"),
            )
        except Exception as error:
            app.logger.exception("LANaxy-Healthcheck fehlgeschlagen")
            return {
                "status": "critical",
                "readiness": "warning",
                "version": APP_VERSION,
                "error": str(error),
                "checks": [{
                    "id": "health",
                    "label": "Healthcheck",
                    "ok": False,
                    "message": str(error),
                }],
            }

    @app.get("/health")
    def health():
        payload = health_payload()
        return payload, 200 if payload.get("status") == "ok" else 503

    @app.get("/readiness")
    def readiness():
        payload = health_payload()
        return payload, 200 if payload.get("readiness") == "ready" else 503

    @app.get("/api/guardians/status")
    def guardian_status_api():
        config = service.load()
        state = load_state().get("checks", {})
        result = {}
        for check in config.get("checks", []):
            check_id = check.get("id")
            check_state = state.get(check_id, {})
            result[check_id] = {
                "id": check_id,
                "name": check.get("name", check_id),
                "enabled": check.get("enabled", True),
                "status": check_state.get(
                    "status",
                    "pending",
                ),
                "level": int(
                    check_state.get("level", 0) or 0
                ),
                "message": check_state.get(
                    "message",
                    "Guardian wird geprüft.",
                ),
                "last_check": check_state.get(
                    "last_check",
                    "",
                ),
                "uptime": check_state.get("uptime"),
                "guardian": check.get("guardian"),
                "details": check_state.get("details", {}),
                "response_time": check_state.get(
                    "details",
                    {},
                ).get(
                    "response_time",
                    check_state.get("response_time"),
                ),
            }
        return {
            "ok": True,
            "timestamp": int(time.time()),
            "guardians": result,
        }

    @app.get("/favicon.ico")
    def favicon():
        return send_file(
            Path(app.static_folder) / "favicon.svg",
            mimetype="image/svg+xml",
        )

    @app.get("/")
    def dashboard():
        config = service.load()
        state = load_state().get("checks", {})
        catalog = guardian_catalog()

        guardians = []
        for check in config.get("checks", []):
            check_state = state.get(check.get("id"), {})
            guardians.append({
                "check": check,
                "state": check_state,
                "metadata": catalog.get(check.get("guardian"), {}),
                "maintenance_active": bool(
                    maintenance_active(check)
                    or runtime_maintenance(check.get("id"))
                ),
            })

        active_guardians = [
            item
            for item in guardians
            if item["check"].get("enabled", True)
        ]
        problem_guardians = [
            item
            for item in active_guardians
            if int(item["state"].get("level", 0) or 0) > 0
            or item["state"].get("status") in {"critical", "warning", "blocked"}
        ]

        notifications = config.get("notifications", {})
        channels = notifications.get("channels", [])
        rules = notifications.get("rules", [])
        portal_items = config.get("control", {}).get("portals", [])
        portal_runtime = portal_manager.status()
        beacon_status = load_notification_status()

        active_beacons = [
            item for item in channels if item.get("enabled", True)
        ]
        beacon_errors = [
            item
            for item in active_beacons
            if beacon_status.get(item.get("id"), {}).get("last_error")
        ]
        active_portals = [
            item for item in portal_items if item.get("enabled", True)
        ]
        portal_errors = [
            item
            for item in active_portals
            if portal_runtime.get(item.get("id"), {}).get("last_error")
            or not portal_runtime.get(item.get("id"), {}).get("running", False)
        ]

        latest_events = database.query_events(
            page=1,
            per_page=8,
        ).get("rows", [])

        control_runtime = control_engine.state.snapshot()

        check_by_id = {
            item["check"].get("id"): item
            for item in guardians
        }
        maintenance_items = {}

        for item in guardians:
            if not item["maintenance_active"]:
                continue
            check = item["check"]
            maintenance = check.get("maintenance", {})
            maintenance_items[check.get("id")] = {
                "id": check.get("id"),
                "name": check.get("name", check.get("id")),
                "until": maintenance.get("until", ""),
                "reason": maintenance.get("reason", ""),
                "source": "guardian",
            }

        for check_id, maintenance in control_runtime.get(
            "maintenance",
            {},
        ).items():
            guardian = check_by_id.get(check_id, {})
            check = guardian.get("check", {})
            maintenance_items[check_id] = {
                "id": check_id,
                "name": check.get("name", check_id),
                "until": maintenance.get("until", ""),
                "reason": maintenance.get("reason", ""),
                "source": "control",
            }

        maintenance_items = list(maintenance_items.values())

        latest_checks = [
            item["state"].get("last_check")
            for item in active_guardians
            if item["state"].get("last_check")
        ]

        dashboard_config = config.setdefault(
            "web",
            {},
        ).setdefault(
            "dashboard",
            {},
        )
        dashboard_layout = normalize_layout(
            dashboard_config.get("widgets")
        )

        guardian_groups = {}
        for item in guardians:
            group_name = item["check"].get("group") or "Ohne Gruppe"
            guardian_groups.setdefault(group_name, []).append(item)

        portal_catalog_data = localized_portal_catalog()
        beacon_catalog_data = localized_beacon_catalog()

        open_incidents = database.query_incidents(
            status="open",
            page=1,
            per_page=20,
        )
        dashboard_health = build_health(
            app_version=APP_VERSION,
            config=config,
            runtime=load_runtime_status(),
            state=state,
            agents=list_miniguards(),
            monitoring_running=process_running("/run/lanaxy/lanaxy.pid"),
            web_running=process_running("/run/lanaxy/lanaxy-web.pid"),
        )

        return render_template(
            "dashboard.html",
            dashboard_health=dashboard_health,
            open_incident_count=open_incidents["total"],
            open_incidents=open_incidents["rows"],
            dashboard_layout=dashboard_layout,
            widget_catalog=WIDGET_CATALOG,
            guardian_groups=guardian_groups,
            channels=channels,
            beacon_status=beacon_status,
            beacon_catalog=beacon_catalog_data,
            portal_items=portal_items,
            portal_runtime=portal_runtime,
            portal_catalog=portal_catalog_data,
            rules=rules,
            guardians=guardians,
            problem_guardians=problem_guardians,
            active_guardian_count=len(active_guardians),
            ok_guardian_count=max(
                0,
                len(active_guardians) - len(problem_guardians),
            ),
            active_beacon_count=len(active_beacons),
            beacon_error_count=len(beacon_errors),
            active_portal_count=len(active_portals),
            portal_error_count=len(portal_errors),
            active_rule_count=len([
                rule for rule in rules if rule.get("enabled", True)
            ]),
            maintenance_count=len(maintenance_items),
            maintenance_items=maintenance_items,
            paused_rule_count=len(
                control_runtime.get("paused_rules", {})
            ),
            mute_active=bool(
                control_runtime.get("mute", {}).get("all")
            ),
            latest_events=latest_events,
            last_check=max(latest_checks) if latest_checks else "—",
        )

    @app.post("/dashboard/layout/save")
    def dashboard_layout_save():
        config = service.load()
        try:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                raise ValueError("Ungültige Dashboard-Daten.")
            layout = normalize_layout(payload.get("widgets"))
            config.setdefault("web", {}).setdefault(
                "dashboard",
                {},
            )["widgets"] = layout
            service.save(config)
            return {
                "ok": True,
                "widgets": layout,
            }
        except Exception as error:
            return {
                "ok": False,
                "error": str(error),
            }, 400

    @app.post("/dashboard/layout/reset")
    def dashboard_layout_reset():
        config = service.load()
        config.setdefault("web", {}).setdefault(
            "dashboard",
            {},
        )["widgets"] = default_layout()
        service.save(config)
        flash("Dashboard wurde auf das Standardlayout zurückgesetzt.", "success")
        return redirect(url_for("dashboard"))

    @app.post("/dashboard/control/mute")
    def dashboard_control_mute():
        runtime = control_engine.state.snapshot()
        mute_active = bool(runtime.get("mute", {}).get("all"))
        command = "unmute" if mute_active else "mute"
        result = control_engine.execute(
            {
                "command": command,
                "reason": "Über das LANaxy-Dashboard geschaltet",
            },
            "web:dashboard",
        )
        if result.get("ok"):
            flash(
                "Globale Stummschaltung wurde "
                + ("aufgehoben." if mute_active else "aktiviert."),
                "success",
            )
        else:
            flash(
                "Stummschaltung konnte nicht geändert werden: "
                + result.get("error", "Unbekannter Fehler"),
                "error",
            )
        return redirect(url_for("dashboard"))

    @app.post("/api/proxmox/discover-guests")
    def proxmox_discover_guests():
        config = service.load()
        check_id = request.form.get("check_id", "").strip()
        existing = next((item for item in config.get("checks", []) if item.get("id") == check_id), {})
        token_secret = request.form.get("token_secret", "")
        if token_secret == SECRET_PLACEHOLDER or not token_secret:
            token_secret = existing.get("token_secret", "")
        check = {
            "api_url": request.form.get("api_url", "").strip(),
            "token_id": request.form.get("token_id", "").strip(),
            "token_secret": token_secret,
            "verify_tls": request.form.get("verify_tls") in {"1", "true", "on", "yes"},
            "timeout": request.form.get("timeout", "10").replace(",", "."),
            "node": request.form.get("node", "").strip(),
        }
        missing = [
            label for key, label in (
                ("api_url", "Proxmox API URL"),
                ("token_id", "API-Token-ID"),
                ("token_secret", "API-Token-Secret"),
            ) if not check.get(key)
        ]
        if missing:
            return jsonify({"ok": False, "error": "Fehlende Angaben: " + ", ".join(missing)}), 400
        try:
            selected_node, guests = ProxmoxApiGuardian.discover_guests(check, check.get("node"))
            return jsonify({
                "ok": True,
                "node": selected_node,
                "guests": guests,
                "auto_selected": guests[0] if len(guests) == 1 else None,
            })
        except Exception as error:
            return jsonify({"ok": False, "error": str(error)}), 400

    @app.post("/api/proxmox/discover-nodes")
    def proxmox_discover_nodes():
        config = service.load()
        check_id = request.form.get("check_id", "").strip()
        existing = next((item for item in config.get("checks", []) if item.get("id") == check_id), {})
        token_secret = request.form.get("token_secret", "")
        if token_secret == SECRET_PLACEHOLDER or not token_secret:
            token_secret = existing.get("token_secret", "")
        check = {
            "api_url": request.form.get("api_url", "").strip(),
            "token_id": request.form.get("token_id", "").strip(),
            "token_secret": token_secret,
            "verify_tls": request.form.get("verify_tls") in {"1", "true", "on", "yes"},
            "timeout": request.form.get("timeout", "10").replace(",", "."),
        }
        missing = [
            label for key, label in (
                ("api_url", "Proxmox API URL"),
                ("token_id", "API-Token-ID"),
                ("token_secret", "API-Token-Secret"),
            ) if not check.get(key)
        ]
        if missing:
            return jsonify({"ok": False, "error": "Fehlende Angaben: " + ", ".join(missing)}), 400
        try:
            nodes = ProxmoxApiGuardian.discover_nodes(check)
            if not nodes:
                return jsonify({"ok": False, "error": "Die Proxmox API hat keine Nodes zurückgegeben."}), 404
            return jsonify({"ok": True, "nodes": nodes, "auto_selected": nodes[0]["name"] if len(nodes) == 1 else None})
        except Exception as error:
            return jsonify({"ok": False, "error": str(error)}), 400

    @app.route("/guardian/add", methods=["GET", "POST"])
    def add_guardian():
        catalog = guardian_catalog()
        guardian_type = request.values.get("type")

        if not guardian_type:
            return redirect(url_for("guardian_types"))

        metadata = catalog.get(guardian_type)
        if metadata is None:
            abort(404)

        current_config = service.load()
        existing_names = {
            str(item.get("name", "")).strip().casefold()
            for item in current_config.get("checks", [])
            if str(item.get("name", "")).strip()
        }
        base_name = str(metadata.get("name") or guardian_type).strip()
        suggested_name = base_name
        suffix = 2
        while suggested_name.casefold() in existing_names:
            suggested_name = f"{base_name} {suffix}"
            suffix += 1

        render_check = {
            "guardian": guardian_type,
            "enabled": True,
            "name": suggested_name,
        }
        return_to = request.values.get("return_to", "").strip()
        if not return_to.startswith("/") or return_to.startswith("//"):
            return_to = ""
        preserve_submitted_secrets = False
        if request.method == "POST":
            render_check = _guardian_form_values(request.form, metadata["schema"], render_check)
            preserve_submitted_secrets = True
            try:
                current_config = service.load()
                check = build_check_from_form(
                    request.form,
                    guardian_type,
                    metadata["schema"],
                    config=current_config,
                )
                checks = current_config.setdefault("checks", [])
                if any(
                    item.get("id") == check.get("id")
                    for item in checks
                ):
                    raise ValueError(
                        f"Check-ID bereits vorhanden: {check['id']}"
                    )
                checks.append(check)
                enforce_routing_safety(current_config)
                service.save(current_config)
                restart_lanaxy()
                flash("Guardian wurde hinzugefügt.", "success")
                if return_to:
                    return redirect(return_to)
                return redirect(url_for("guardian_management"))
            except Exception as error:
                flash(str(error), "error")

        return render_template(
            "guardian_form.html",
            mode="add",
            metadata=metadata,
            check=render_check,
            preserve_submitted_secrets=preserve_submitted_secrets,
            secret_placeholder=SECRET_PLACEHOLDER,
            get_nested=get_nested,
            all_checks=service.load().get("checks", []),
            groups=sorted({
                item.get("group")
                for item in service.load().get("checks", [])
                if item.get("group")
            }),
        )

    @app.route("/guardian/<check_id>/edit", methods=["GET", "POST"])
    def edit_guardian(check_id):
        config = service.load()
        check = next(
            (item for item in config.get("checks", []) if item.get("id") == check_id),
            None,
        )
        if check is None:
            abort(404)

        catalog = guardian_catalog()
        metadata = catalog.get(check.get("guardian"))
        if metadata is None:
            abort(500)

        render_check = check
        preserve_submitted_secrets = False
        if request.method == "POST":
            render_check = _guardian_form_values(request.form, metadata["schema"], check)
            preserve_submitted_secrets = True
            try:
                updated = build_check_from_form(
                    request.form,
                    check["guardian"],
                    metadata["schema"],
                    existing=check,
                    config=config,
                )
                imported_missing = list(check.get("_import_missing_secrets", []))
                if imported_missing:
                    remaining_missing = [
                        path for path in imported_missing
                        if not _nested_value(updated, path)
                    ]
                    if remaining_missing:
                        updated["enabled"] = False
                        updated["_import_missing_secrets"] = remaining_missing
                    else:
                        updated.pop("_import_missing_secrets", None)
                        # Only imported Guardians carrying this marker are
                        # automatically re-enabled after all missing secrets
                        # have been supplied. Manually disabled Guardians do
                        # not enter this branch.
                        updated["enabled"] = True
                checks = config.setdefault("checks", [])
                for index, existing in enumerate(checks):
                    if existing.get("id") == check_id:
                        checks[index] = updated
                        break
                else:
                    raise ValueError(
                        f"Guardian nicht gefunden: {check_id}"
                    )
                enforce_routing_safety(config)
                service.save(config)
                invalidate_guardian_state(
                    updated.get("id", check_id),
                    updated.get("name", check_id),
                )
                restart_lanaxy()
                flash("Guardian wurde gespeichert.", "success")
                return redirect(url_for("guardian_management"))
            except Exception as error:
                flash(str(error), "error")

        return render_template(
            "guardian_form.html",
            mode="edit",
            metadata=metadata,
            check=render_check,
            preserve_submitted_secrets=preserve_submitted_secrets,
            secret_placeholder=SECRET_PLACEHOLDER,
            get_nested=get_nested,
            all_checks=config.get("checks", []),
            groups=sorted({
                item.get("group")
                for item in config.get("checks", [])
                if item.get("group")
            }),
        )

    @app.post("/guardian/<check_id>/delete")
    def delete_guardian(check_id):
        try:
            delete_incidents = request.form.get("delete_incidents") == "1"
            service.delete_check(check_id)

            # A reused Guardian ID must never inherit the previous runtime state.
            state_store = StateStore(str(state_path))
            state_store.data.setdefault("checks", {}).pop(check_id, None)
            state_store.save()

            smart_history = (
                LANAXY_DATA_DIR / "guardian-state" / "smart" / f"{check_id}.json"
            )
            smart_history.unlink(missing_ok=True)

            removed = {"incidents": 0, "members": 0}
            if delete_incidents:
                removed = database.delete_incidents_for_guardian(check_id)

            restart_lanaxy()
            if delete_incidents:
                flash(
                    "Guardian und zugehörige Incident-Daten wurden gelöscht "
                    f"({removed['incidents']} Incidents).",
                    "success",
                )
            else:
                flash("Guardian wurde gelöscht.", "success")
        except Exception as error:
            flash(str(error), "error")
        return redirect(url_for("guardian_management"))

    @app.post("/guardian/<check_id>/toggle")
    def toggle_guardian(check_id):
        try:
            service.toggle_check(check_id)
            restart_lanaxy()
            flash("Guardian-Status wurde geändert.", "success")
        except Exception as error:
            flash(str(error), "error")
        return redirect(url_for("guardian_management"))

    @app.post("/guardian/<check_id>/duplicate")
    def duplicate_guardian(check_id):
        try:
            new_id = service.duplicate_check(check_id)
            restart_lanaxy()
            flash("Guardian wurde dupliziert.", "success")
            return redirect(url_for("edit_guardian", check_id=new_id))
        except Exception as error:
            flash(str(error), "error")
            return redirect(url_for("guardian_management"))

    @app.get("/api/status")
    def api_status():
        config = service.load()
        state = load_state().get("checks", {})
        return {
            "guardians": [
                {
                    "id": check.get("id"),
                    "name": check.get("name"),
                    "enabled": check.get("enabled", True),
                    "status": state.get(check.get("id"), {}).get("status", "unknown"),
                    "level": state.get(check.get("id"), {}).get("level"),
                    "message": state.get(check.get("id"), {}).get("message", ""),
                    "last_check": state.get(check.get("id"), {}).get("last_check", ""),
                }
                for check in config.get("checks", [])
            ]
        }


    def protocol_filters():
        return {
            "search": request.args.get("search", "").strip(),
            "guardian_id": request.args.get("guardian_id", "").strip(),
            "level": request.args.get("level", "").strip(),
            "event_type": request.args.get("event_type", "").strip(),
            "date_from": request.args.get("date_from", "").strip(),
            "date_to": request.args.get("date_to", "").strip(),
        }

    @app.get("/protocol")
    def protocol():
        filters = protocol_filters()
        result = database.query_events(
            **filters,
            page=request.args.get("page", 1, type=int),
            per_page=request.args.get("per_page", 100, type=int),
        )
        return render_template(
            "protocol.html",
            result=result,
            filters=filters,
            filter_values=database.filter_values(),
        )

    @app.get("/protocol/export.<format_name>")
    def protocol_export(format_name):
        if format_name not in {"csv", "json"}:
            abort(404)
        filters = protocol_filters()
        content = database.export_events(filters, format_name)
        mimetype = (
            "text/csv; charset=utf-8"
            if format_name == "csv"
            else "application/json; charset=utf-8"
        )
        return Response(
            content,
            mimetype=mimetype,
            headers={
                "Content-Disposition":
                    f'attachment; filename="lanaxy-protokoll.{format_name}"'
            },
        )

    @app.get("/incidents")
    def incidents_page():
        status = request.args.get("status", "")
        guardian_id = request.args.get("guardian_id", "")
        priority = request.args.get("priority", "")
        acknowledged = request.args.get("acknowledged", "")
        assignee = request.args.get("assignee", "")
        page = max(1, int(request.args.get("page", 1)))
        incidents = database.query_incidents(
            status=status,
            guardian_id=guardian_id,
            priority=priority, acknowledged=acknowledged, assignee=assignee,
            page=page,
            per_page=50,
        )
        config = service.load()
        guardians = {
            item.get("id"): item.get("name", item.get("id"))
            for item in config.get("checks", [])
        }
        return render_template(
            "incidents.html",
            incidents=incidents,
            selected_status=status,
            selected_guardian=guardian_id, selected_priority=priority,
            selected_acknowledged=acknowledged, selected_assignee=assignee,
            guardians=guardians,
        )

    @app.get("/incidents/<int:incident_id>")
    def incident_detail(incident_id):
        incident = database.get_incident(incident_id)
        if incident is None:
            abort(404)
        deliveries = database.query_deliveries(
            incident_id=incident_id,
            page=1,
            per_page=250,
        )
        config = service.load()
        checks = {check.get("id"): check for check in config.get("checks", [])}
        root_check = checks.get(incident.get("guardian_id"), {})
        upstream = []
        visited = set()
        stack = list(root_check.get("depends_on", []) or [])
        while stack:
            guardian_id = stack.pop(0)
            if guardian_id in visited:
                continue
            visited.add(guardian_id)
            candidate = checks.get(guardian_id)
            if candidate:
                upstream.append(candidate)
                stack.extend(candidate.get("depends_on", []) or [])
        incident_notes = [
            item for item in incident.get("timeline", [])
            if item.get("event_kind") == "note"
        ]
        return render_template(
            "incident_detail.html",
            incident=incident,
            incident_notes=incident_notes,
            deliveries=deliveries["rows"],
            root_causes=analyze_root_causes(list(checks.values()), load_state().get("checks", {}), incident.get("guardian_id", "")),
            incident_signature=incident_signature(list(checks.values()), incident.get("guardian_id", "")),
            root_cause_candidates=upstream,
        )

    @app.post("/incidents/<int:incident_id>/note")
    def incident_add_note(incident_id):
        note = request.form.get("note", "").strip()
        actor = session.get("username", "Web UI")
        try:
            database.add_incident_note(incident_id, actor, note)
            flash("Notiz wurde zur Incident-Timeline hinzugefügt.", "success")
        except ValueError as error:
            flash(str(error), "error")
        return redirect(url_for("incident_detail", incident_id=incident_id) + "#incident-notes")

    @app.post("/incidents/<int:incident_id>/metadata")
    def incident_metadata(incident_id):
        try:
            database.update_incident_metadata(incident_id, actor=session.get("username","Web UI"), priority=request.form.get("priority"), assignee=request.form.get("assignee",""))
            flash("Incident-Zuordnung wurde aktualisiert.","success")
        except ValueError as error: flash(str(error),"error")
        return redirect(url_for("incident_detail",incident_id=incident_id))

    @app.post("/incidents/<int:incident_id>/split")
    def incident_split(incident_id):
        try:
            new_id=database.split_incident_member(incident_id,request.form.get("guardian_id",""),actor=session.get("username","Web UI"))
            flash(f"Neuer Incident #{new_id} wurde erzeugt.","success")
        except ValueError as error: flash(str(error),"error")
        return redirect(url_for("incident_detail",incident_id=incident_id))

    @app.post("/incidents/bulk")
    def incident_bulk():
        ids=[int(x) for x in request.form.getlist("incident_ids")]
        action=request.form.get("action","")
        if not ids: flash("Keine Incidents ausgewählt.","error"); return redirect(url_for("incidents_page"))
        for iid in ids:
            try:
                if action=="acknowledge": database.acknowledge_incident(iid,actor=session.get("username","Web UI"),note="Massenquittierung")
                elif action in {"low","normal","high","critical"}: database.update_incident_metadata(iid,actor=session.get("username","Web UI"),priority=action)
            except ValueError: pass
        flash(f"{len(ids)} Incidents wurden bearbeitet.","success")
        return redirect(url_for("incidents_page"))

    @app.post("/incidents/<int:incident_id>/acknowledge")
    def incident_acknowledge(incident_id):
        note = request.form.get("note", "").strip()
        actor = session.get("username", "Web UI")
        try:
            incident = database.acknowledge_incident(
                incident_id,
                actor=actor,
                note=note,
            )
            database.add_event(
                "INCIDENT_ACKNOWLEDGED",
                f"Incident #{incident_id} wurde quittiert.",
                level=incident.get("level", 0),
                status=incident.get("status", ""),
                guardian_id=incident.get("guardian_id", ""),
                guardian_name=incident.get("guardian_name", ""),
                details={
                    "incident_id": incident_id,
                    "actor": actor,
                    "note": note,
                },
            )
            flash(
                "Incident wurde quittiert. Ausstehende Wiederholungen wurden gestoppt.",
                "success",
            )
        except Exception as error:
            flash(str(error), "error")
        return redirect(
            request.form.get("next")
            or url_for("incident_detail", incident_id=incident_id)
        )

    @app.post("/incidents/<int:incident_id>/unacknowledge")
    def incident_unacknowledge(incident_id):
        try:
            database.unacknowledge_incident(incident_id)
            flash("Quittierung wurde aufgehoben.", "success")
        except Exception as error:
            flash(str(error), "error")
        return redirect(
            request.form.get("next")
            or url_for("incident_detail", incident_id=incident_id)
        )

    @app.get("/beacons/<channel_id>/deliveries")
    def beacon_deliveries(channel_id):
        config = service.load()
        channel = next(
            (
                item
                for item in config.get("notifications", {}).get(
                    "channels",
                    [],
                )
                if item.get("id") == channel_id
            ),
            None,
        )
        if channel is None:
            abort(404)
        page = max(1, int(request.args.get("page", 1)))
        deliveries = database.query_deliveries(
            channel_id=channel_id,
            page=page,
            per_page=100,
        )
        return render_template(
            "beacon_deliveries.html",
            channel=channel,
            deliveries=deliveries,
        )

    @app.get("/history")
    def history():
        config = service.load()
        guardians = [
            check for check in config.get("checks", [])
            if check.get("enabled", True)
        ]
        guardian_id = request.args.get("guardian_id", "")
        if not guardian_id and guardians:
            guardian_id = guardians[0].get("id", "")
        hours = request.args.get("hours", 24, type=int)
        if hours not in {3, 6, 12, 24, 168, 720, 2160, 4320, 8760}:
            hours = 24
        return render_template(
            "history.html",
            guardians=guardians,
            guardian_id=guardian_id,
            hours=hours,
        )

    @app.get("/api/history/<guardian_id>")
    def api_history(guardian_id):
        hours = request.args.get("hours", 24, type=int)
        if hours not in {3, 6, 12, 24, 168, 720, 2160, 4320, 8760}:
            hours = 24
        return database.history(guardian_id, hours)

    @app.route("/login", methods=["GET","POST"])
    def login():
        config=service.load()
        if not auth_enabled(config): return redirect(url_for("dashboard"))
        error=""
        if request.method=="POST":
            if limited(): error="Zu viele Fehlversuche. Bitte später erneut versuchen."
            elif verify(config,request.form.get("username",""),request.form.get("password","")):
                clear(); a=config.get("web",{}).get("authentication",{})
                session.clear(); session["authenticated"]=True; session["username"]=a.get("username"); session["session_version"]=int(a.get("session_version",1)); session.permanent=True
                app.permanent_session_lifetime=timedelta(minutes=int(a.get("session_lifetime_minutes",480)))
                return redirect(url_for("dashboard"))
            else: failed(); error="Benutzername oder Passwort ist falsch."
        return render_template("login.html",error=error)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    def _unique_guardian_id(checks, base):
        candidate = re.sub(r"[^a-z0-9_]+", "_", str(base).casefold()).strip("_") or "guardian"
        existing = {str(check.get("id")) for check in checks}
        if candidate not in existing:
            return candidate
        number = 2
        while f"{candidate}_{number}" in existing:
            number += 1
        return f"{candidate}_{number}"

    def _proxmox_source_check(config, source_id):
        source = next(
            (
                check for check in config.get("checks", [])
                if check.get("id") == source_id
                and check.get("guardian") == "proxmox_api"
            ),
            None,
        )
        if source is None:
            raise ValueError("Der gewählte Proxmox API Guardian wurde nicht gefunden.")
        return source

    def _proxmox_scan(source):
        nodes = ProxmoxApiGuardian.discover_nodes(source)
        result = {"nodes": [], "guests": [], "guest_configs": [], "storages": [], "backups": [], "backup_summary": [], "backup_jobs": [], "hardware": {"usb": [], "pci": [], "disks": [], "zfs_pools": [], "serial_by_id": [], "backup_files": []}}
        for node in nodes:
            node_name = node["name"]
            result["nodes"].append(node)
            _, guests = ProxmoxApiGuardian.discover_guests(source, node_name)
            _, storages = ProxmoxApiGuardian.discover_storages(source, node_name)
            result["guests"].extend(guests)
            result["guest_configs"].extend(ProxmoxApiGuardian.discover_guest_configs(source, node_name))
            result["storages"].extend(storages)
            result["backups"].extend(ProxmoxApiGuardian.discover_backups(source, node_name))
            result["backup_summary"].extend(ProxmoxApiGuardian.summarize_guest_backups(source, node_name))
        result["backup_jobs"] = ProxmoxApiGuardian.discover_backup_jobs(source)
        passthrough={}
        for guest in result["guest_configs"]:
            for item in guest.get("usb",[]): passthrough.setdefault("usb",[]).append({"guest":guest,"assignment":item})
            for item in guest.get("pci",[]): passthrough.setdefault("pci",[]).append({"guest":guest,"assignment":item})
        result["passthrough"] = passthrough
        return result

    def _proxmox_existing_keys(checks):
        return set(planner_pve_existing(checks))

    def _pbs_existing_keys(checks):
        return set(planner_pbs_existing(checks))

    def _api_assistant_error(exc, source, platform):
        raw = str(exc).strip() or "Unbekannter API-Fehler"
        lowered = raw.lower()
        title = f"{platform}-Verbindung fehlgeschlagen"
        explanation = "LANaxy konnte die API des ausgewählten Guardians nicht abfragen."
        hint = "Prüfe Adresse, Zugangsdaten und Berechtigungen des Guardians."

        if "401" in lowered or "unauthorized" in lowered:
            title = "Anmeldung an der API fehlgeschlagen"
            explanation = f"Der {platform}-Server hat die hinterlegten Zugangsdaten abgelehnt."
            hint = "Prüfe Benutzer, Realm sowie API-Token oder Passwort im Guardian."
        elif "403" in lowered or "forbidden" in lowered:
            title = "API-Zugriff nicht erlaubt"
            explanation = f"Die Anmeldung am {platform}-Server war möglich, aber dem Konto fehlen Rechte für diese Abfrage."
            hint = "Ergänze die benötigten Audit-/Leserechte oder verwende einen API-Token mit passenden Berechtigungen."
        elif "certificate" in lowered or "ssl" in lowered:
            title = "TLS-Zertifikat konnte nicht geprüft werden"
            explanation = f"LANaxy konnte die verschlüsselte Verbindung zum {platform}-Server nicht verifizieren."
            hint = "Prüfe Zertifikat, Hostnamen und die Einstellung zur Zertifikatsprüfung im Guardian."
        elif "connection" in lowered or "timed out" in lowered or "timeout" in lowered:
            title = f"{platform}-Server nicht erreichbar"
            explanation = "Die konfigurierte API-Adresse antwortet nicht oder die Verbindung wurde unterbrochen."
            hint = "Prüfe IP-Adresse, Port, Firewall und ob der API-Dienst läuft."
        elif "404" in lowered or "not found" in lowered:
            title = "API-Endpunkt nicht gefunden"
            explanation = f"Die konfigurierte Adresse verweist nicht auf einen erreichbaren {platform}-API-Endpunkt."
            hint = "Prüfe insbesondere Protokoll, Host und API-Port im Guardian."

        return {
            "title": title,
            "explanation": explanation,
            "hint": hint,
            "technical": raw,
            "source_id": str((source or {}).get("id", "")).strip(),
            "source_name": str((source or {}).get("name", "")).strip() or f"{platform} API Guardian",
        }

    @app.route("/guardians/proxmox-assistant", methods=["GET"])
    def proxmox_assistant():
        config = service.load()
        sources = [
            check for check in config.get("checks", [])
            if check.get("guardian") == "proxmox_api"
        ]
        source_id = request.args.get("source", "").strip()
        if not source_id and len(sources) == 1:
            source_id = str(sources[0].get("id", "")).strip()
        scan = None
        error = None
        miniguard_id = request.args.get("miniguard", "").strip()
        if source_id:
            source = None
            try:
                source = _proxmox_source_check(config, source_id)
                scan = _proxmox_scan(source)
                if miniguard_id:
                    inventory = miniguard_execute_remote_check(miniguard_id, "hardware_inventory", {"name": "Proxmox Hardwareinventar"}, 60)
                    if inventory.get("status") == "ok":
                        scan["hardware"] = inventory.get("details") or scan["hardware"]
                    else:
                        error = {
                            "title": "Hardwareinventar konnte nicht geladen werden",
                            "explanation": "Die API-Erkennung war erfolgreich, aber der ausgewählte MiniGuard konnte das Hardwareinventar nicht liefern.",
                            "hint": "Prüfe den Status und die Berechtigungen des MiniGuards oder starte die Erkennung ohne Hardwareinventar.",
                            "technical": inventory.get("message", "Hardwareinventar fehlgeschlagen"),
                            "source_id": "",
                            "source_name": "",
                        }
            except Exception as exc:
                error = _api_assistant_error(exc, source, "Proxmox")
        agents = [
            agent for agent in list_miniguards()
            if agent.get("registered") and agent.get("enabled", True)
        ]
        return render_template(
            "proxmox_assistant.html",
            sources=sources,
            source_id=source_id,
            miniguard_id=miniguard_id,
            scan=scan,
            agents=agents,
            existing_keys=_proxmox_existing_keys(config.get("checks", [])),
            error=error,
        )

    @app.post("/guardians/proxmox-assistant/apply")
    def proxmox_assistant_apply():
        config = service.load()
        checks = config.setdefault("checks", [])
        source = _proxmox_source_check(
            config,
            request.form.get("source_id", "").strip(),
        )
        selected = request.form.getlist("objects")
        group = request.form.get("group", "").strip() or "Proxmox"
        tags = [
            value.strip()
            for value in request.form.get("tags", "proxmox").split(",")
            if value.strip()
        ]
        create_dependencies = request.form.get("create_dependencies") == "1"
        if request.form.get("confirmed") != "1":
            common_preview = {"source_id": source.get("id"), "group": group, "tags": ", ".join(tags)}
            existing_map = planner_pve_existing(checks)
            def desired_for(value):
                parts=value.split("|"); kind=parts[0] if parts else ""
                if kind=="node" and len(parts)>=2:
                    node=parts[1]; return {"_key":f"node|{node}","guardian":"proxmox_api","name":f"Proxmox Node {node}","mode":"node","node":node}
                if kind=="guest" and len(parts)>=5:
                    node,gt,vmid,name=parts[1:5]; return {"_key":f"guest|{node}|{gt}|{vmid}","guardian":"proxmox_api","name":f"{'VM' if gt=='qemu' else 'LXC'} {vmid} – {name}","mode":"guest","node":node,"guest_type":gt,"vmid":int(vmid)}
                if kind=="storage" and len(parts)>=3:
                    node,store=parts[1:3]; return {"_key":f"storage|{node}|{store}","guardian":"proxmox_api","name":f"Proxmox Storage {store} ({node})","mode":"storage","node":node,"storage":store}
                if kind=="usb" and len(parts)>=4:
                    serial = parts[4] if len(parts) >= 5 else ""
                    serial_by_id = parts[5] if len(parts) >= 6 else ""
                    identity = serial_by_id or serial or f"{parts[1]}:{parts[2]}"
                    return {"_key":f"usb|{identity}","guardian":"usb","name":f"USB {parts[3]}","vendor_id":parts[1],"product_id":parts[2],"serial":serial,"serial_by_id":serial_by_id}
                if kind=="pci" and len(parts)>=3: return {"_key":f"pci|{parts[1]}","guardian":"pci_device","name":f"PCI {parts[2]}","pci_address":parts[1]}
                if kind=="disk" and len(parts)>=3: return {"_key":f"disk|{parts[1]}","guardian":"smart","name":f"SMART {parts[2]}","device":parts[1]}
                if kind=="zfs" and len(parts)>=2: return {"_key":f"zfs|{parts[1]}","guardian":"zfs_raid","name":f"ZFS Pool {parts[1]}","pool":parts[1]}
                if kind=="backup" and len(parts)>=2: return {"_key":f"backup|{parts[1]}","guardian":"backup","name":f"Backup {Path(parts[1]).name}","pattern":parts[1]}
            miniguard_id = request.form.get("miniguard_id", "").strip()
            wants_updates = request.form.get("create_updates") == "1"
            wants_zfs = request.form.get("create_zfs") == "1"
            if (wants_updates or wants_zfs) and not miniguard_id:
                flash("Für Updates-/Neustart- und ZFS-/RAID-Prüfungen muss ein MiniGuard ausgewählt werden.", "error")
                return redirect(url_for("proxmox_assistant", source=source.get("id"), miniguard=request.args.get("miniguard", "")))

            preview_rows=build_assistant_preview(selected,existing_map,desired_for,request.form.get("update_existing")=="1")

            def append_optional_preview(kind, desired):
                current = next((check for check in checks if check.get("guardian") == desired["guardian"] and check.get("execution_source") == "miniguard" and str(check.get("miniguard_id", "")) == miniguard_id and (kind != "zfs" or not str(check.get("pool", "")).strip())), None)
                if current:
                    fields = [key for key in desired if key not in {"guardian", "id"}]
                    changes = [
                        {"field": key, "old": current.get(key), "new": desired.get(key)}
                        for key in fields if current.get(key) != desired.get(key)
                    ]
                    action = "update" if request.form.get("update_existing") == "1" and changes else "skip"
                    preview_rows.append({"key": f"optional|{kind}", "action": action, "name": desired["name"], "guardian": desired["guardian"], "existing_id": current.get("id"), "changes": changes})
                else:
                    preview_rows.append({"key": f"optional|{kind}", "action": "create", "name": desired["name"], "guardian": desired["guardian"], "changes": []})

            if wants_updates:
                append_optional_preview("updates", {
                    "guardian": "package_updates",
                    "name": "Proxmox Updates / Neustart",
                    "execution_source": "miniguard",
                    "miniguard_id": miniguard_id,
                    "warning_updates": 1,
                    "critical_updates": 30,
                    "reboot_is_critical": True,
                    "interval": 21600,
                    "timeout": 60,
                    "retries": 2,
                    "group": group,
                    "tags": list(dict.fromkeys(tags + ["updates"])),
                })
            if wants_zfs:
                append_optional_preview("zfs", {
                    "guardian": "zfs_raid",
                    "name": "Proxmox ZFS / RAID",
                    "execution_source": "miniguard",
                    "miniguard_id": miniguard_id,
                    "mode": "zfs",
                    "pool": "",
                    "interval": 300,
                    "timeout": 20,
                    "retries": 2,
                    "group": group,
                    "tags": list(dict.fromkeys(tags + ["storage", "zfs"])),
                })
            return render_template("assistant_preview.html", assistant="proxmox", title="Proxmox-Assistent – Vorschau", rows=preview_rows, form=request.form, selected=selected, return_url=url_for("proxmox_assistant",source=source.get("id"), miniguard=miniguard_id))
        created = []
        skipped_existing = 0
        node_ids = {}

        # Existing node checks can be reused as dependency roots.
        for check in checks:
            if (
                check.get("guardian") == "proxmox_api"
                and check.get("mode", "node") == "node"
                and check.get("node")
            ):
                node_ids[str(check["node"])] = check.get("id")

        common = {
            "guardian": "proxmox_api",
            "enabled": True,
            "interval": int(float(source.get("interval", 60))),
            "timeout": int(float(source.get("timeout", 10))),
            "retries": int(float(source.get("retries", 3))),
            "api_url": source.get("api_url"),
            "token_id": source.get("token_id"),
            "token_secret": source.get("token_secret"),
            "verify_tls": bool(source.get("verify_tls", True)),
            "group": group,
            "tags": list(dict.fromkeys(tags)),
        }

        # Nodes first, so child dependencies are deterministic.
        for value in selected:
            parts = value.split("|")
            if parts[0] != "node" or len(parts) < 2:
                continue
            node = parts[1]
            if node in node_ids:
                if request.form.get("update_existing") == "1":
                    existing_node = next((c for c in checks if c.get("id") == node_ids[node]), None)
                    if existing_node:
                        existing_node.update({**copy.deepcopy(common), "name": f"Proxmox Node {node}", "mode": "node", "node": node})
                        skipped_existing += 1
                continue
            check_id = _unique_guardian_id(checks, f"proxmox_node_{node}")
            check = {
                **copy.deepcopy(common),
                "id": check_id,
                "name": f"Proxmox Node {node}",
                "mode": "node",
                "node": node,
                "minimum_uptime_minutes": 0,
            }
            checks.append(check)
            created.append(check)
            node_ids[node] = check_id

        for value in selected:
            parts = value.split("|")
            object_type = parts[0] if parts else ""
            if object_type == "guest" and len(parts) >= 5:
                node, guest_type, vmid, name = parts[1], parts[2], parts[3], parts[4]
                existing_check = next((c for c in checks if c.get("guardian")=="proxmox_api" and c.get("mode")=="guest" and str(c.get("node"))==node and str(c.get("guest_type"))==guest_type and str(c.get("vmid"))==vmid),None)
                if existing_check:
                    skipped_existing += 1
                    if request.form.get("update_existing")=="1": existing_check.update({**copy.deepcopy(common),"name":f"{'VM' if guest_type == 'qemu' else 'LXC'} {vmid} – {name}","node":node,"guest_type":guest_type,"vmid":int(vmid)})
                    continue
                check_id = _unique_guardian_id(checks, f"proxmox_{guest_type}_{vmid}")
                check = {
                    **copy.deepcopy(common),
                    "id": check_id,
                    "name": f"{'VM' if guest_type == 'qemu' else 'LXC'} {vmid} – {name}",
                    "mode": "guest",
                    "node": node,
                    "guest_type": guest_type,
                    "vmid": int(vmid),
                    "expected_status": "running",
                    "minimum_uptime_minutes": 0,
                }
                if create_dependencies and node in node_ids:
                    check["depends_on"] = [node_ids[node]]
                checks.append(check)
                created.append(check)
            elif object_type == "storage" and len(parts) >= 3:
                node, storage = parts[1], parts[2]
                existing_check = next((c for c in checks if c.get("guardian")=="proxmox_api" and c.get("mode")=="storage" and str(c.get("node"))==node and str(c.get("storage"))==storage),None)
                if existing_check:
                    skipped_existing += 1
                    if request.form.get("update_existing")=="1": existing_check.update({**copy.deepcopy(common),"name":f"Proxmox Storage {storage} ({node})","node":node,"storage":storage})
                    continue
                check_id = _unique_guardian_id(checks, f"proxmox_storage_{node}_{storage}")
                check = {
                    **copy.deepcopy(common),
                    "id": check_id,
                    "name": f"Proxmox Storage {storage} ({node})",
                    "mode": "storage",
                    "node": node,
                    "storage": storage,
                    "warning_used_percent": 80,
                    "critical_used_percent": 95,
                }
                if create_dependencies and node in node_ids:
                    check["depends_on"] = [node_ids[node]]
                checks.append(check)
                created.append(check)

        miniguard_id = request.form.get("miniguard_id", "").strip()
        if miniguard_id and request.form.get("create_updates") == "1":
            existing_optional = next((c for c in checks if c.get("guardian") == "package_updates" and c.get("execution_source") == "miniguard" and str(c.get("miniguard_id", "")) == miniguard_id), None)
            check_id = existing_optional.get("id") if existing_optional else _unique_guardian_id(checks, "proxmox_updates")
            check = {
                "guardian": "package_updates",
                "id": check_id,
                "name": "Proxmox Updates / Neustart",
                "enabled": True,
                "execution_source": "miniguard",
                "miniguard_id": miniguard_id,
                "warning_updates": 1,
                "critical_updates": 30,
                "reboot_is_critical": True,
                "interval": 21600,
                "timeout": 60,
                "retries": 2,
                "group": group,
                "tags": list(dict.fromkeys(tags + ["updates"])),
            }
            root_dependency = next(iter(node_ids.values()), None)
            if create_dependencies and root_dependency:
                check["depends_on"] = [root_dependency]
            if existing_optional:
                skipped_existing += 1
                if request.form.get("update_existing") == "1":
                    keep_enabled = existing_optional.get("enabled", True)
                    existing_optional.update(check)
                    existing_optional["enabled"] = keep_enabled
            else:
                checks.append(check)
                created.append(check)

        if miniguard_id and request.form.get("create_zfs") == "1":
            existing_optional = next((c for c in checks if c.get("guardian") == "zfs_raid" and c.get("execution_source") == "miniguard" and str(c.get("miniguard_id", "")) == miniguard_id and not str(c.get("pool", "")).strip()), None)
            check_id = existing_optional.get("id") if existing_optional else _unique_guardian_id(checks, "proxmox_zfs")
            check = {
                "guardian": "zfs_raid",
                "id": check_id,
                "name": "Proxmox ZFS / RAID",
                "enabled": True,
                "execution_source": "miniguard",
                "miniguard_id": miniguard_id,
                "mode": "zfs",
                "pool": "",
                "interval": 300,
                "timeout": 20,
                "retries": 2,
                "group": group,
                "tags": list(dict.fromkeys(tags + ["storage", "zfs"])),
            }
            root_dependency = next(iter(node_ids.values()), None)
            if create_dependencies and root_dependency:
                check["depends_on"] = [root_dependency]
            if existing_optional:
                skipped_existing += 1
                if request.form.get("update_existing") == "1":
                    keep_enabled = existing_optional.get("enabled", True)
                    existing_optional.update(check)
                    existing_optional["enabled"] = keep_enabled
            else:
                checks.append(check)
                created.append(check)

        # Hardwareobjekte aus dem MiniGuard-Inventar.
        for value in selected:
            parts = value.split("|")
            kind = parts[0] if parts else ""
            dependency = next(iter(node_ids.values()), None)
            if not miniguard_id:
                continue
            check = None
            if kind == "usb" and len(parts) >= 4:
                vid, pid, label = parts[1], parts[2], parts[3]
                serial = parts[4] if len(parts) >= 5 else ""
                serial_by_id = parts[5] if len(parts) >= 6 else ""
                check = {"guardian":"usb","name":f"USB {label}","vendor_id":vid,"product_id":pid,"serial":serial,"serial_by_id":serial_by_id,"execution_source":"miniguard","miniguard_id":miniguard_id,"interval":60,"timeout":15,"retries":2}
            elif kind == "pci" and len(parts) >= 3:
                address, label = parts[1], parts[2]
                check = {"guardian":"pci_device","name":f"PCI {label}","pci_address":address,"execution_source":"miniguard","miniguard_id":miniguard_id,"interval":60,"timeout":15,"retries":2}
            elif kind == "disk" and len(parts) >= 3:
                device, label = parts[1], parts[2]
                check = {"guardian":"smart","name":f"SMART {label}","device":device,"execution_source":"miniguard","miniguard_id":miniguard_id,"interval":300,"timeout":30,"retries":2,"track_history":True,"history_limit":500}
            elif kind == "zfs" and len(parts) >= 2:
                pool = parts[1]
                check = {"guardian":"zfs_raid","name":f"ZFS Pool {pool}","mode":"zfs","pool":pool,"execution_source":"miniguard","miniguard_id":miniguard_id,"interval":300,"timeout":20,"retries":2}
            elif kind == "backup" and len(parts) >= 2:
                path = parts[1]
                check = {"guardian":"backup","name":f"Backup {Path(path).name}","pattern":path,"execution_source":"miniguard","miniguard_id":miniguard_id,"warning_age_hours":26,"critical_age_hours":48,"minimum_size_mb":1,"retention_days":7,"minimum_count":1,"interval":1800,"timeout":30,"retries":2}
            if check:
                existing_key = None
                if kind == "usb":
                    existing_key = next((c for c in checks if c.get("guardian")=="usb" and str(c.get("miniguard_id", ""))==miniguard_id and ((check.get("serial_by_id") and str(c.get("serial_by_id", ""))==str(check.get("serial_by_id"))) or (check.get("serial") and str(c.get("serial", ""))==str(check.get("serial"))) or (not check.get("serial_by_id") and not check.get("serial") and str(c.get("vendor_id"))==str(check.get("vendor_id")) and str(c.get("product_id"))==str(check.get("product_id"))))), None)
                elif kind == "pci": existing_key = next((c for c in checks if c.get("guardian")=="pci_device" and str(c.get("pci_address"))==str(check.get("pci_address"))), None)
                elif kind == "disk": existing_key = next((c for c in checks if c.get("guardian")=="smart" and str(c.get("device"))==str(check.get("device"))), None)
                elif kind == "zfs": existing_key = next((c for c in checks if c.get("guardian")=="zfs_raid" and str(c.get("pool"))==str(check.get("pool"))), None)
                elif kind == "backup": existing_key = next((c for c in checks if c.get("guardian")=="backup" and str(c.get("pattern"))==str(check.get("pattern"))), None)
                if existing_key:
                    skipped_existing += 1
                    if request.form.get("update_existing") == "1":
                        keep_id=existing_key.get("id"); keep_enabled=existing_key.get("enabled",True)
                        existing_key.update(check); existing_key.update({"id":keep_id,"enabled":keep_enabled,"group":group,"tags":list(dict.fromkeys(tags+["hardware"]))})
                        if create_dependencies and dependency: existing_key["depends_on"]=[dependency]
                    continue
                check.update({"id":_unique_guardian_id(checks,check["name"]),"enabled":True,"group":group,"tags":list(dict.fromkeys(tags+["hardware"])),"device_id":""})
                check["device_id"] = check["id"]
                if create_dependencies and dependency: check["depends_on"]=[dependency]
                checks.append(check); created.append(check)

        if not created and not (skipped_existing and request.form.get("update_existing")=="1"):
            flash("Es wurden keine neuen Guardians ausgewählt. Bereits vorhandene Einträge wurden übersprungen.", "error")
            return redirect(url_for("proxmox_assistant", source=source.get("id")))

        enforce_routing_safety(config)
        service.save(config)
        restart_lanaxy()
        flash(f"{len(created)} Guardians angelegt, {skipped_existing if request.form.get('update_existing')=='1' else 0} vorhandene aktualisiert.", "success")
        return redirect(url_for("guardian_management"))

    def _pbs_source_check(config, source_id):
        source = next(
            (
                check for check in config.get("checks", [])
                if check.get("id") == source_id
                and check.get("guardian") == "proxmox_backup_server"
                and str(check.get("mode", "server") or "server") == "server"
            ),
            None,
        )
        if source is None:
            raise ValueError("Der gewählte Proxmox Backup Server Guardian wurde nicht gefunden.")
        return source

    @app.get("/guardians/pbs-assistant")
    def pbs_assistant():
        config = service.load()
        sources = [
            check for check in config.get("checks", [])
            if check.get("guardian") == "proxmox_backup_server"
            and str(check.get("mode", "server") or "server") == "server"
        ]
        source_id = request.args.get("source", "").strip()
        if not source_id and len(sources) == 1:
            source_id = str(sources[0].get("id", "")).strip()
        scan = None
        error = None
        miniguard_id = request.args.get("miniguard", "").strip()
        if source_id:
            source = None
            try:
                source = _pbs_source_check(config, source_id)
                scan = PbsGuardian.discover(source)
                if miniguard_id:
                    inventory = miniguard_execute_remote_check(miniguard_id, "hardware_inventory", {"name": "PBS Hardwareinventar"}, 60)
                    if inventory.get("status") == "ok":
                        scan["hardware"] = inventory.get("details") or {}
                    else:
                        error = {
                            "title": "Hardwareinventar konnte nicht geladen werden",
                            "explanation": "Die API-Erkennung war erfolgreich, aber der ausgewählte MiniGuard konnte das Hardwareinventar nicht liefern.",
                            "hint": "Prüfe den Status und die Berechtigungen des MiniGuards oder starte die Erkennung ohne Hardwareinventar.",
                            "technical": inventory.get("message", "Hardwareinventar fehlgeschlagen"),
                            "source_id": "",
                            "source_name": "",
                        }
            except Exception as exc:
                error = _api_assistant_error(exc, source, "Proxmox Backup Server")
        agents = [
            agent for agent in list_miniguards()
            if agent.get("registered") and agent.get("enabled", True)
        ]
        return render_template(
            "pbs_assistant.html",
            sources=sources,
            source_id=source_id,
            miniguard_id=miniguard_id,
            scan=scan,
            agents=agents,
            existing_keys=_pbs_existing_keys(config.get("checks", [])),
            error=error,
        )

    @app.post("/guardians/pbs-assistant/apply")
    def pbs_assistant_apply():
        config = service.load()
        checks = config.setdefault("checks", [])
        source = _pbs_source_check(config, request.form.get("source_id", "").strip())
        selected = request.form.getlist("objects")
        group = request.form.get("group", "").strip() or "Proxmox Backup Server"
        tags = [value.strip() for value in request.form.get("tags", "pbs, backup").split(",") if value.strip()]
        create_dependencies = request.form.get("create_dependencies") == "1"
        if request.form.get("confirmed") != "1":
            existing_map=planner_pbs_existing(checks)
            update_existing=request.form.get("update_existing")=="1"
            def desired_for(value):
                parts=value.split("|"); kind=parts[0] if parts else ""
                if kind=="datastore" and len(parts)>=2:
                    store=parts[1]; return {"_key":f"datastore|{store}","guardian":"proxmox_backup_server","name":f"PBS Datastore {store}","mode":"datastore","datastore":store}
                if kind=="backup" and len(parts)>=5:
                    store,ns,bt,bi=parts[1:5]; return {"_key":f"backup|{store}|{ns}|{bt}|{bi}","guardian":"proxmox_backup_server","name":f"PBS Backup {bt}/{bi}","mode":"backup","datastore":store,"namespace":ns,"backup_type":bt,"backup_id":bi}
                if kind=="job" and len(parts)>=3:
                    jt,jid=parts[1:3]; return {"_key":f"job|{jt}|{jid}","guardian":"proxmox_backup_server","name":f"PBS {jt.title()} {jid}","mode":"job","job_type":jt,"job_id":jid}
                if kind=="remote" and len(parts)>=2:
                    remote=parts[1]; return {"_key":f"remote|{remote}","guardian":"proxmox_backup_server","name":f"PBS Remote {remote}","mode":"remote","remote":remote}
                if kind=="usb" and len(parts)>=4:
                    serial = parts[4] if len(parts) >= 5 else ""
                    serial_by_id = parts[5] if len(parts) >= 6 else ""
                    identity = serial_by_id or serial or f"{parts[1]}:{parts[2]}"
                    return {"_key":f"usb|{identity}","guardian":"usb","name":f"USB {parts[3]}","vendor_id":parts[1],"product_id":parts[2],"serial":serial,"serial_by_id":serial_by_id}
                if kind=="pci" and len(parts)>=3: return {"_key":f"pci|{parts[1]}","guardian":"pci_device","name":f"PCI {parts[2]}","pci_address":parts[1]}
                if kind=="disk" and len(parts)>=3: return {"_key":f"disk|{parts[1]}","guardian":"smart","name":f"SMART {parts[2]}","device":parts[1]}
                if kind=="zfs" and len(parts)>=2: return {"_key":f"zfs|{parts[1]}","guardian":"zfs_raid","name":f"ZFS Pool {parts[1]}","pool":parts[1]}
            miniguard_id = request.form.get("miniguard_id", "").strip()
            wants_updates = request.form.get("create_updates") == "1"
            if wants_updates and not miniguard_id:
                flash("Für den Updates-/Neustart-Guardian muss ein MiniGuard ausgewählt werden.", "error")
                return redirect(url_for("pbs_assistant", source=source.get("id")))

            rows=build_assistant_preview(selected,existing_map,desired_for,update_existing)
            if wants_updates:
                desired = {
                    "guardian": "package_updates",
                    "name": "PBS Updates / Neustart",
                    "execution_source": "miniguard",
                    "miniguard_id": miniguard_id,
                    "warning_updates": 1,
                    "critical_updates": 30,
                    "reboot_is_critical": True,
                    "interval": 21600,
                    "timeout": 60,
                    "retries": 2,
                    "group": group,
                    "tags": list(dict.fromkeys(tags + ["updates"])),
                }
                current = next((
                    check for check in checks
                    if check.get("guardian") == "package_updates"
                    and check.get("execution_source") == "miniguard"
                    and str(check.get("miniguard_id", "")) == miniguard_id
                ), None)
                if current:
                    fields = [key for key in desired if key not in {"guardian", "id"}]
                    changes = [
                        {"field": key, "old": current.get(key), "new": desired.get(key)}
                        for key in fields if current.get(key) != desired.get(key)
                    ]
                    action = "update" if update_existing and changes else "skip"
                    rows.append({"key": "optional|updates", "action": action, "name": desired["name"], "guardian": desired["guardian"], "existing_id": current.get("id"), "changes": changes})
                else:
                    rows.append({"key": "optional|updates", "action": "create", "name": desired["name"], "guardian": desired["guardian"], "changes": []})
            return render_template("assistant_preview.html",assistant="pbs",title="PBS-Assistent – Vorschau",rows=rows,form=request.form,selected=selected,return_url=url_for("pbs_assistant",source=source.get("id")))
        created = []
        skipped_existing = 0
        datastore_ids = {}

        for check in checks:
            if check.get("guardian") == "proxmox_backup_server" and check.get("mode") == "datastore" and check.get("datastore"):
                datastore_ids[str(check["datastore"])] = check.get("id")

        common = {
            "guardian": "proxmox_backup_server",
            "enabled": True,
            "api_url": source.get("api_url"),
            "token_id": source.get("token_id"),
            "token_secret": source.get("token_secret"),
            "verify_tls": bool(source.get("verify_tls", True)),
            "interval": 300,
            "timeout": int(float(source.get("timeout", 15))),
            "retries": 2,
            "group": group,
            "tags": list(dict.fromkeys(tags)),
        }

        server_id = source.get("id")
        for value in selected:
            parts = value.split("|")
            if parts[0] != "datastore" or len(parts) < 2:
                continue
            store = parts[1]
            if store in datastore_ids:
                skipped_existing += 1
                if request.form.get("update_existing") == "1":
                    existing_store = next((c for c in checks if c.get("id") == datastore_ids[store]), None)
                    if existing_store:
                        existing_store.update({**copy.deepcopy(common), "name": f"PBS Datastore {store}", "mode": "datastore", "datastore": store})
                continue
            check = {
                **copy.deepcopy(common),
                "id": _unique_guardian_id(checks, f"pbs_datastore_{store}"),
                "name": f"PBS Datastore {store}",
                "mode": "datastore",
                "datastore": store,
                "warning_used_percent": 80,
                "critical_used_percent": 95,
            }
            if create_dependencies and server_id and server_id != check["id"]:
                check["depends_on"] = [server_id]
            checks.append(check); created.append(check); datastore_ids[store] = check["id"]

        warning_age = int(float(request.form.get("warning_age_hours", 26) or 26))
        critical_age = int(float(request.form.get("critical_age_hours", 48) or 48))
        for value in selected:
            parts = value.split("|")
            kind = parts[0] if parts else ""
            if kind == "backup" and len(parts) >= 5:
                store, namespace, backup_type, backup_id = parts[1], parts[2], parts[3], parts[4]
                existing_check = next((c for c in checks if c.get("guardian")=="proxmox_backup_server" and c.get("mode")=="backup" and str(c.get("datastore"))==store and str(c.get("namespace", ""))==namespace and str(c.get("backup_type"))==backup_type and str(c.get("backup_id"))==backup_id), None)
                if existing_check:
                    skipped_existing += 1
                    if request.form.get("update_existing") == "1":
                        existing_check.update({**copy.deepcopy(common), "name":f"PBS Backup {backup_type}/{backup_id}", "mode":"backup", "datastore":store, "namespace":namespace, "backup_type":backup_type, "backup_id":backup_id, "warning_age_hours":warning_age, "critical_age_hours":critical_age, "interval":1800})
                    continue
                check = {
                    **copy.deepcopy(common),
                    "id": _unique_guardian_id(checks, f"pbs_backup_{backup_type}_{backup_id}"),
                    "name": f"PBS Backup {backup_type}/{backup_id}",
                    "mode": "backup",
                    "datastore": store,
                    "namespace": namespace,
                    "backup_type": backup_type,
                    "backup_id": backup_id,
                    "warning_age_hours": warning_age,
                    "critical_age_hours": critical_age,
                    "interval": 1800,
                }
                dependency = datastore_ids.get(store) or server_id
                if create_dependencies and dependency:
                    check["depends_on"] = [dependency]
                checks.append(check); created.append(check)
            elif kind == "job" and len(parts) >= 3:
                job_type, job_id = parts[1], parts[2]
                existing_check = next((c for c in checks if c.get("guardian")=="proxmox_backup_server" and c.get("mode")=="job" and str(c.get("job_type"))==job_type and str(c.get("job_id"))==job_id), None)
                if existing_check:
                    skipped_existing += 1
                    if request.form.get("update_existing") == "1":
                        existing_check.update({**copy.deepcopy(common), "name":f"PBS {job_type.title()} {job_id}", "mode":"job", "job_type":job_type, "job_id":job_id, "interval":900})
                    continue
                check = {
                    **copy.deepcopy(common),
                    "id": _unique_guardian_id(checks, f"pbs_{job_type}_{job_id}"),
                    "name": f"PBS {job_type.title()} {job_id}",
                    "mode": "job",
                    "job_type": job_type,
                    "job_id": job_id,
                    "interval": 900,
                }
                dependency = datastore_ids.get(job_id) if job_type == "gc" else server_id
                if create_dependencies and dependency:
                    check["depends_on"] = [dependency]
                checks.append(check); created.append(check)

        for value in selected:
            parts=value.split("|")
            if not parts or parts[0]!="remote" or len(parts)<2: continue
            remote_name=parts[1]
            existing_check=next((c for c in checks if c.get("guardian")=="proxmox_backup_server" and c.get("mode")=="remote" and str(c.get("remote"))==remote_name),None)
            if existing_check:
                skipped_existing += 1
                if request.form.get("update_existing")=="1": existing_check.update({**copy.deepcopy(common),"name":f"PBS Remote {remote_name}","remote":remote_name,"mode":"remote"})
                continue
            check={**copy.deepcopy(common),"id":_unique_guardian_id(checks,f"pbs_remote_{remote_name}"),"name":f"PBS Remote {remote_name}","mode":"remote","remote":remote_name}
            if create_dependencies and server_id: check["depends_on"]=[server_id]
            checks.append(check); created.append(check)

        miniguard_id = request.form.get("miniguard_id", "").strip()

        # Hardwareobjekte aus dem MiniGuard-Inventar des PBS-Hosts.
        for value in selected:
            parts = value.split("|")
            kind = parts[0] if parts else ""
            if not miniguard_id or kind not in {"usb", "pci", "disk", "zfs"}:
                continue
            check = None
            if kind == "usb" and len(parts) >= 4:
                vid, pid, label = parts[1], parts[2], parts[3]
                serial = parts[4] if len(parts) >= 5 else ""
                serial_by_id = parts[5] if len(parts) >= 6 else ""
                check = {"guardian":"usb","name":f"USB {label}","vendor_id":vid,"product_id":pid,"serial":serial,"serial_by_id":serial_by_id,"execution_source":"miniguard","miniguard_id":miniguard_id,"interval":60,"timeout":15,"retries":2}
            elif kind == "pci" and len(parts) >= 3:
                address, label = parts[1], parts[2]
                check = {"guardian":"pci_device","name":f"PCI {label}","pci_address":address,"execution_source":"miniguard","miniguard_id":miniguard_id,"interval":60,"timeout":15,"retries":2}
            elif kind == "disk" and len(parts) >= 3:
                device, label = parts[1], parts[2]
                check = {"guardian":"smart","name":f"SMART {label}","device":device,"execution_source":"miniguard","miniguard_id":miniguard_id,"interval":300,"timeout":30,"retries":2,"track_history":True,"history_limit":500}
            elif kind == "zfs" and len(parts) >= 2:
                pool = parts[1]
                check = {"guardian":"zfs_raid","name":f"ZFS Pool {pool}","mode":"zfs","pool":pool,"execution_source":"miniguard","miniguard_id":miniguard_id,"interval":300,"timeout":20,"retries":2}
            if not check:
                continue
            existing_key = None
            if kind == "usb":
                existing_key = next((c for c in checks if c.get("guardian")=="usb" and str(c.get("miniguard_id", ""))==miniguard_id and ((check.get("serial_by_id") and str(c.get("serial_by_id", ""))==str(check.get("serial_by_id"))) or (check.get("serial") and str(c.get("serial", ""))==str(check.get("serial"))) or (not check.get("serial_by_id") and not check.get("serial") and str(c.get("vendor_id"))==str(check.get("vendor_id")) and str(c.get("product_id"))==str(check.get("product_id"))))), None)
            elif kind == "pci": existing_key = next((c for c in checks if c.get("guardian")=="pci_device" and str(c.get("pci_address"))==str(check.get("pci_address")) and str(c.get("miniguard_id", ""))==miniguard_id), None)
            elif kind == "disk": existing_key = next((c for c in checks if c.get("guardian")=="smart" and str(c.get("device"))==str(check.get("device")) and str(c.get("miniguard_id", ""))==miniguard_id), None)
            elif kind == "zfs": existing_key = next((c for c in checks if c.get("guardian")=="zfs_raid" and str(c.get("pool"))==str(check.get("pool")) and str(c.get("miniguard_id", ""))==miniguard_id), None)
            if existing_key:
                skipped_existing += 1
                if request.form.get("update_existing") == "1":
                    keep_id=existing_key.get("id"); keep_enabled=existing_key.get("enabled",True)
                    existing_key.update(check); existing_key.update({"id":keep_id,"enabled":keep_enabled,"group":group,"tags":list(dict.fromkeys(tags+["hardware"]))})
                    if create_dependencies and server_id: existing_key["depends_on"]=[server_id]
                continue
            check.update({"id":_unique_guardian_id(checks,check["name"]),"enabled":True,"group":group,"tags":list(dict.fromkeys(tags+["hardware"])),"device_id":""})
            check["device_id"] = check["id"]
            if create_dependencies and server_id: check["depends_on"]=[server_id]
            checks.append(check); created.append(check)

        if request.form.get("create_updates") == "1":
            if not miniguard_id:
                flash("Für den Updates-/Neustart-Guardian muss ein MiniGuard ausgewählt werden.", "error")
                return redirect(url_for("pbs_assistant", source=source.get("id")))
            desired_updates = {
                "guardian": "package_updates",
                "name": "PBS Updates / Neustart",
                "enabled": True,
                "execution_source": "miniguard",
                "miniguard_id": miniguard_id,
                "warning_updates": 1,
                "critical_updates": 30,
                "reboot_is_critical": True,
                "interval": 21600,
                "timeout": 60,
                "retries": 2,
                "group": group,
                "tags": list(dict.fromkeys(tags + ["updates"])),
            }
            if create_dependencies and server_id:
                desired_updates["depends_on"] = [server_id]
            existing_updates = next((
                check for check in checks
                if check.get("guardian") == "package_updates"
                and check.get("execution_source") == "miniguard"
                and str(check.get("miniguard_id", "")) == miniguard_id
            ), None)
            if existing_updates:
                skipped_existing += 1
                if request.form.get("update_existing") == "1":
                    existing_updates.update(copy.deepcopy(desired_updates))
            else:
                check = {**copy.deepcopy(desired_updates), "id": _unique_guardian_id(checks, "pbs_updates")}
                checks.append(check); created.append(check)

        if not created and not (skipped_existing and request.form.get("update_existing") == "1"):
            flash("Es wurden keine neuen PBS-Guardians ausgewählt. Bereits vorhandene Einträge wurden übersprungen.", "error")
            return redirect(url_for("pbs_assistant", source=source.get("id")))
        enforce_routing_safety(config)
        service.save(config)
        restart_lanaxy()
        flash(f"{len(created)} PBS-Guardians angelegt, {skipped_existing if request.form.get('update_existing')=='1' else 0} vorhandene aktualisiert.", "success")
        return redirect(url_for("guardian_management"))


    def _guardian_secret_fields(metadata):
        schema = metadata.get("schema", {}) if isinstance(metadata, dict) else {}
        result = []
        for path, field in schema.items():
            if not isinstance(field, dict) or not field.get("secret"):
                continue
            result.append({
                "path": str(path),
                "label": str(field.get("label") or path),
                "required": bool(field.get("required")),
            })
        return result

    def _nested_value(mapping, path):
        current = mapping
        for part in str(path).split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    def _remove_nested_value(mapping, path):
        parts = str(path).split(".")
        current = mapping
        for part in parts[:-1]:
            if not isinstance(current, dict):
                return
            current = current.get(part)
        if isinstance(current, dict):
            current.pop(parts[-1], None)

    def _missing_import_secrets(check, metadata):
        missing = []
        for field in _guardian_secret_fields(metadata):
            value = _nested_value(check, field["path"])
            if value == "__REDACTED__" or (field["required"] and not value):
                missing.append(field)
                _remove_nested_value(check, field["path"])
        return missing

    @app.get("/guardians/export.json")
    def guardian_export():
        config = service.load()
        ids = [
            value.strip()
            for value in request.args.get("ids", "").split(",")
            if value.strip()
        ]
        checks = config.get("checks", [])
        if ids:
            wanted = set(ids)
            checks = [check for check in checks if check.get("id") in wanted]
        include_secrets = request.args.get("include_secrets") == "1"
        secret_keys = {"token_secret","access_token","password","api_key","token","secret","bearer_token","bot_token","webhook_url"}
        def protected(value):
            if isinstance(value, dict):
                return {
                    key: (
                        item if include_secrets or key not in secret_keys else "__REDACTED__"
                    ) if not isinstance(item, (dict, list)) else protected(item)
                    for key, item in value.items()
                    if key != "_import_missing_secrets"
                }
            if isinstance(value, list): return [protected(item) for item in value]
            return value
        payload = {
            "format": "lanaxy-guardians",
            "version": 2,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "contains_secrets": include_secrets,
            "checks": protected(checks),
        }
        return Response(
            json.dumps(payload, ensure_ascii=False, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=lanaxy-guardians.json"},
        )

    @app.post("/guardians/import")
    def guardian_import():
        upload = request.files.get("file")
        if not upload or not upload.filename:
            flash("Bitte eine JSON-Datei auswählen.", "error")
            return redirect(url_for("guardian_management"))
        try:
            payload = json.loads(upload.read().decode("utf-8"))
            imported = payload.get("checks") if isinstance(payload, dict) else None
            if not isinstance(imported, list):
                raise ValueError("Die Datei enthält keine Guardian-Liste.")

            config = service.load()
            existing = config.get("checks", [])
            catalog = guardian_catalog()
            preview = []
            compatible = []
            existing_ids = {str(check.get("id")) for check in existing}
            for incoming in imported:
                if not isinstance(incoming, dict):
                    continue
                guardian_type = incoming.get("guardian")
                if guardian_type not in catalog:
                    preview.append({
                        "status": "skip",
                        "name": incoming.get("name") or incoming.get("id") or "Unbekannt",
                        "guardian": guardian_type or "—",
                        "reason": "Guardian-Typ ist nicht installiert.",
                    })
                    continue
                check = copy.deepcopy(incoming)
                original_id = str(check.get("id") or "")
                proposed_id = _unique_guardian_id(
                    [*existing, *compatible],
                    original_id or check.get("name") or guardian_type,
                )
                check["id"] = proposed_id
                check["name"] = check.get("name") or proposed_id
                missing_secrets = _missing_import_secrets(check, catalog[guardian_type])
                if missing_secrets:
                    check["enabled"] = False
                    check["_import_missing_secrets"] = [field["path"] for field in missing_secrets]
                compatible.append(check)
                renamed = bool(original_id and original_id != proposed_id)
                reason_parts = []
                if renamed:
                    reason_parts.append("ID-Konflikt wird automatisch aufgelöst.")
                if missing_secrets:
                    labels = ", ".join(field["label"] for field in missing_secrets)
                    reason_parts.append(
                        "Fehlende Zugangsdaten: " + labels + ". "
                        "Der Guardian wird deaktiviert importiert und muss anschließend bearbeitet werden."
                    )
                preview.append({
                    "status": "secrets" if missing_secrets else ("rename" if renamed else "new"),
                    "name": check["name"],
                    "guardian": guardian_type,
                    "old_id": original_id,
                    "new_id": proposed_id,
                    "missing_secrets": [field["label"] for field in missing_secrets],
                    "reason": " ".join(reason_parts),
                })

            if not compatible:
                raise ValueError("Keine kompatiblen Guardians gefunden.")

            token = uuid.uuid4().hex
            preview_dir = LANAXY_DATA_DIR / "import-previews"
            preview_dir.mkdir(parents=True, exist_ok=True)
            preview_file = preview_dir / f"{token}.json"
            preview_file.write_text(
                json.dumps({"checks": compatible}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.chmod(preview_file, 0o600)
            for old in preview_dir.glob("*.json"):
                if time.time() - old.stat().st_mtime > 3600:
                    old.unlink(missing_ok=True)

            return render_template(
                "guardian_import_preview.html",
                preview=preview,
                token=token,
                import_count=len(compatible),
            )
        except Exception as exc:
            flash(f"Import fehlgeschlagen: {exc}", "error")
            return redirect(url_for("guardian_management"))

    @app.post("/guardians/import/confirm")
    def guardian_import_confirm():
        token = request.form.get("token", "")
        if not re.fullmatch(r"[a-f0-9]{32}", token):
            abort(400)
        preview_file = LANAXY_DATA_DIR / "import-previews" / f"{token}.json"
        try:
            payload = json.loads(preview_file.read_text(encoding="utf-8"))
            imported = payload.get("checks", [])
            config = service.load()
            checks = config.setdefault("checks", [])
            checks.extend(copy.deepcopy(imported))
            enforce_routing_safety(config)
            service.save(config)
            restart_lanaxy()
            missing_count = sum(1 for item in imported if item.get("_import_missing_secrets"))
            message = f"{len(imported)} Guardians wurden importiert."
            if missing_count:
                message += (
                    f" {missing_count} davon bleiben wegen fehlender Zugangsdaten deaktiviert. "
                    "Bitte die markierten Guardians bearbeiten und anschließend aktivieren."
                )
            flash(message, "warning" if missing_count else "success")
        except Exception as exc:
            flash(f"Import fehlgeschlagen: {exc}", "error")
        finally:
            preview_file.unlink(missing_ok=True)
        return redirect(url_for("guardian_management"))

    @app.get("/guardians/group/<path:group_name>")
    def guardian_group_detail(group_name):
        config = service.load()
        state = load_state().get("checks", {})
        catalog = guardian_catalog()
        checks = [
            check for check in config.get("checks", [])
            if (check.get("group") or "Ohne Gruppe") == group_name
        ]
        if not checks:
            abort(404)
        return render_template(
            "guardian_group.html",
            group_name=group_name,
            guardians=[
                {
                    "check": check,
                    "state": state.get(check.get("id"), {}),
                    "metadata": catalog.get(check.get("guardian"), {}),
                }
                for check in checks
            ],
        )

    @app.post("/guardians/group/<path:group_name>/edit")
    def guardian_group_edit(group_name):
        config=service.load(); checks=[c for c in config.get("checks",[]) if (c.get("group") or "Ohne Gruppe")==group_name]
        action=request.form.get("action","")
        for check in checks:
            if action=="enable": check["enabled"]=True
            elif action=="disable": check["enabled"]=False
            elif action=="rename":
                new=request.form.get("new_group","").strip()
                if new: check["group"]=new
            elif action=="settings":
                for key in ("interval","timeout","retries"):
                    raw=request.form.get(key,"").strip()
                    if raw: check[key]=max(1,int(float(raw.replace(",","."))))
        service.save(config); restart_lanaxy(); flash(f"Gruppe {group_name} wurde aktualisiert.","success")
        return redirect(url_for("guardian_management" if action=="rename" else "guardian_group_detail",group_name=request.form.get("new_group",group_name) or group_name))

    @app.post("/guardians/group/<path:group_name>/test")
    def guardian_group_test(group_name):
        checks = [
            check for check in service.load().get("checks", [])
            if (check.get("group") or "Ohne Gruppe") == group_name
            and check.get("enabled", True)
        ]
        success = 0
        failed_count = 0
        for check in checks:
            try:
                test_guardian_via_service(
                    check,
                    timeout=max(15, int(float(check.get("timeout", 3))) * 5),
                )
                success += 1
            except Exception:
                failed_count += 1
        flash(
            f"Gruppentest abgeschlossen: {success} erfolgreich, {failed_count} fehlgeschlagen.",
            "success" if not failed_count else "error",
        )
        return redirect(url_for("guardian_group_detail", group_name=group_name))

    @app.post("/guardians/bulk")
    def guardian_bulk():
        ids = request.form.getlist("guardian_ids")
        action = request.form.get("action", "")
        if not ids:
            flash("Bitte mindestens einen Guardian auswählen.", "error")
            return redirect(url_for("guardian_management"))
        config = service.load()
        checks = config.get("checks", [])
        selected = [check for check in checks if check.get("id") in ids]
        if action == "enable":
            for check in selected: check["enabled"] = True
        elif action == "disable":
            for check in selected: check["enabled"] = False
        elif action == "group":
            group = request.form.get("bulk_group", "").strip()
            for check in selected:
                if group: check["group"] = group
                else: check.pop("group", None)
        elif action == "tags":
            tags = [item.strip() for item in request.form.get("bulk_tags", "").split(",") if item.strip()]
            for check in selected: check["tags"] = list(dict.fromkeys(tags))
        elif action == "settings":
            for check in selected:
                for key in ("interval","timeout","retries"):
                    raw=request.form.get(f"bulk_{key}","").strip()
                    if raw: check[key]=max(1,int(float(raw.replace(",","."))))
                source=request.form.get("bulk_execution_source","").strip()
                if source: check["execution_source"]=source
                miniguard=request.form.get("bulk_miniguard_id","").strip()
                if miniguard: check["miniguard_id"]=miniguard
        elif action == "dependencies":
            deps=[x for x in request.form.getlist("bulk_dependencies") if x not in ids]
            for check in selected: check["depends_on"]=list(dict.fromkeys(deps))
        elif action == "duplicate":
            originals = list(selected)
            for original in originals:
                duplicate = copy.deepcopy(original)
                duplicate["id"] = _unique_guardian_id(
                    config.get("checks", []),
                    f"{original.get('id', 'guardian')}_copy",
                )
                duplicate["name"] = f"{original.get('name', duplicate['id'])} (Kopie)"
                config.setdefault("checks", []).append(duplicate)
        elif action == "test":
            successful = 0
            failed_tests = 0
            for check in selected:
                try:
                    test_guardian_via_service(
                        check,
                        timeout=max(15, int(float(check.get("timeout", 3))) * 5),
                    )
                    successful += 1
                except Exception:
                    failed_tests += 1
            flash(
                f"Test abgeschlossen: {successful} erfolgreich, {failed_tests} fehlgeschlagen.",
                "success" if not failed_tests else "error",
            )
            return redirect(url_for("guardian_management"))
        elif action == "delete":
            selected_ids = {check.get("id") for check in selected}
            config["checks"] = [check for check in checks if check.get("id") not in selected_ids]
            for check in config["checks"]:
                if check.get("depends_on"):
                    check["depends_on"] = [dep for dep in check["depends_on"] if dep not in selected_ids]
        else:
            flash("Unbekannte Massenaktion.", "error")
            return redirect(url_for("guardian_management"))
        enforce_routing_safety(config)
        service.save(config)
        if action not in {"delete", "duplicate"}:
            for check in selected:
                invalidate_guardian_state(
                    check.get("id", ""),
                    check.get("name", check.get("id", "")),
                )
        restart_lanaxy()
        flash(f"{len(selected)} Guardians wurden aktualisiert.", "success")
        return redirect(url_for("guardian_management"))

    @app.post("/api/pbs/discover-targets")
    def pbs_discover_targets():
        config = service.load()
        check_id = request.form.get("check_id", "").strip()
        existing = next((item for item in config.get("checks", []) if item.get("id") == check_id), {})
        token_secret = request.form.get("token_secret", "")
        if token_secret == SECRET_PLACEHOLDER or not token_secret:
            token_secret = existing.get("token_secret", "")
        check = {
            "api_url": request.form.get("api_url", "").strip(),
            "token_id": request.form.get("token_id", "").strip(),
            "token_secret": token_secret,
            "verify_tls": request.form.get("verify_tls") in {"1", "true", "on", "yes"},
            "timeout": request.form.get("timeout", "15").replace(",", "."),
        }
        missing = [
            label for key, label in (
                ("api_url", "PBS API URL"),
                ("token_id", "API-Token-ID"),
                ("token_secret", "API-Token-Secret"),
            ) if not check.get(key)
        ]
        if missing:
            return jsonify({"ok": False, "error": "Fehlende Angaben: " + ", ".join(missing)}), 400
        try:
            scan = PbsGuardian.discover(check)
            datastores = [{
                "name": str(row.get("name") or row.get("store") or ""),
                "used_percent": row.get("used_percent"),
            } for row in scan.get("datastores", []) if row.get("name") or row.get("store")]
            groups = []
            for row in scan.get("groups", []):
                backup_type = str(row.get("backup-type") or row.get("backup_type") or "")
                backup_id = str(row.get("backup-id") or row.get("backup_id") or "")
                if not backup_type or not backup_id:
                    continue
                groups.append({
                    "datastore": str(row.get("datastore") or row.get("store") or ""),
                    "namespace": str(row.get("namespace") or row.get("ns") or ""),
                    "backup_type": backup_type,
                    "backup_id": backup_id,
                })
            jobs = [{
                "job_type": str(row.get("job_type") or ""),
                "job_id": str(row.get("job_id") or ""),
                "store": str(row.get("store") or ""),
            } for row in scan.get("jobs", []) if row.get("job_type") and row.get("job_id")]
            remotes = [{
                "name": str(row.get("name") or row.get("remote") or ""),
                "host": str(row.get("host") or ""),
            } for row in scan.get("remotes", []) if row.get("name") or row.get("remote")]
            return jsonify({"ok": True, "datastores": datastores, "groups": groups, "jobs": jobs, "remotes": remotes})
        except Exception as error:
            return jsonify({"ok": False, "error": str(error)}), 400

    @app.post("/api/proxmox/discover-storages")
    def proxmox_discover_storages():
        config = service.load()
        check_id = request.form.get("check_id", "").strip()
        existing = next((item for item in config.get("checks", []) if item.get("id") == check_id), {})
        token_secret = request.form.get("token_secret", "")
        if token_secret == SECRET_PLACEHOLDER or not token_secret:
            token_secret = existing.get("token_secret", "")
        check = {
            "api_url": request.form.get("api_url", "").strip(),
            "token_id": request.form.get("token_id", "").strip(),
            "token_secret": token_secret,
            "verify_tls": request.form.get("verify_tls") in {"1", "true", "on", "yes"},
            "timeout": request.form.get("timeout", "10").replace(",", "."),
            "node": request.form.get("node", "").strip(),
        }
        try:
            node, storages = ProxmoxApiGuardian.discover_storages(check, check.get("node"))
            return jsonify({"ok": True, "node": node, "storages": storages, "auto_selected": storages[0]["storage"] if len(storages) == 1 else None})
        except Exception as error:
            return jsonify({"ok": False, "error": str(error)}), 400


    def _guardian_notification_dependencies(config, check):
        notifications = config.get("notifications", {})
        channels = notifications.get("channels", [])
        channel_map = {
            str(channel.get("id")): channel
            for channel in channels
            if channel.get("id")
        }
        runtime_status = load_notification_status()
        muted_beacons = control_engine.state.snapshot().get("muted_beacons", {})
        guardian_group = check.get("group", "")
        dependencies = []

        def beacon_entry(channel_id, kind, delay_minutes=0):
            channel = channel_map.get(channel_id)
            status = runtime_status.get(channel_id, {})
            missing = channel is None
            enabled = bool(channel and channel.get("enabled", True))
            muted = bool(muted_beacons.get(channel_id))
            last_error = str(status.get("last_error") or "").strip()
            reachable = bool(not missing and enabled and not muted and not last_error)
            return {
                "id": channel_id,
                "name": (channel or {}).get("name") or channel_id,
                "type": (channel or {}).get("type", "unbekannt"),
                "enabled": enabled,
                "missing": missing,
                "muted": muted,
                "last_error": last_error,
                "reachable": reachable,
                "delay_minutes": delay_minutes,
                "kind": kind,
            }

        for rule in notifications.get("rules", []):
            groups = [str(value) for value in rule.get("groups", []) if value]
            guardians = [str(value) for value in rule.get("guardians", []) if value]
            group_matches = (
                rule.get("all_groups", True)
                or not groups
                or guardian_group in groups
            )
            guardian_matches = (
                rule.get("all_guardians", True)
                or not guardians
                or check.get("id") in guardians
            )
            if not (group_matches and guardian_matches):
                continue

            if rule.get("all_channels", False):
                primary_ids = [
                    str(channel.get("id"))
                    for channel in channels
                    if channel.get("id")
                ]
            else:
                primary_ids = [
                    str(value)
                    for value in rule.get("channels", [])
                    if value
                ]

            primary_beacons = [
                beacon_entry(channel_id, "primary")
                for channel_id in dict.fromkeys(primary_ids)
            ]

            escalation_groups = []
            for index, step in enumerate(rule.get("escalation_steps", []), start=1):
                after_minutes = max(0, int(step.get("after_minutes", 0) or 0))
                step_beacons = [
                    beacon_entry(channel_id, "escalation", after_minutes)
                    for channel_id in dict.fromkeys(
                        str(value)
                        for value in step.get("channels", [])
                        if value
                    )
                ]
                if step_beacons:
                    escalation_groups.append({
                        "index": index,
                        "after_minutes": after_minutes,
                        "beacons": step_beacons,
                    })

            dependencies.append({
                "id": str(rule.get("id", "")),
                "name": rule.get("name") or rule.get("id") or "Unbenannte Rule",
                "enabled": rule.get("enabled", True),
                "statuses": rule.get("statuses", []),
                "delay_seconds": max(0, int(rule.get("delay_seconds", 0) or 0)),
                "primary_beacons": primary_beacons,
                "escalation_groups": escalation_groups,
            })

        all_beacons = []
        for dependency in dependencies:
            if not dependency["enabled"]:
                continue
            all_beacons.extend(dependency["primary_beacons"])
            for group in dependency["escalation_groups"]:
                all_beacons.extend(group["beacons"])

        unique_beacons = {item["id"]: item for item in all_beacons}.values()
        reachable_count = sum(1 for item in unique_beacons if item["reachable"])
        unavailable_count = sum(1 for item in unique_beacons if not item["reachable"])

        can_alert = False
        can_recover = False
        for dependency in dependencies:
            if not dependency["enabled"]:
                continue
            rule_beacons = list(dependency["primary_beacons"])
            for group in dependency["escalation_groups"]:
                rule_beacons.extend(group["beacons"])
            if not any(beacon["reachable"] for beacon in rule_beacons):
                continue
            statuses = {str(status).lower() for status in dependency["statuses"]}
            can_alert = can_alert or bool(statuses & {"warning", "critical"})
            can_recover = can_recover or bool(statuses & {"recovery", "ok"})

        if can_alert and can_recover:
            coverage_state = "ok"
            coverage_message = "Alarm- und OK-Meldungen möglich"
        elif can_alert:
            coverage_state = "warning"
            coverage_message = "Keine OK-Meldung möglich"
        elif can_recover:
            coverage_state = "warning"
            coverage_message = "Keine Warning- oder Critical-Meldung möglich"
        else:
            coverage_state = "critical"
            coverage_message = "Keine Meldung möglich"

        return dependencies, {
            "total": reachable_count + unavailable_count,
            "reachable": reachable_count,
            "unavailable": unavailable_count,
            "none_reachable": bool(reachable_count == 0),
            "can_alert": can_alert,
            "can_recover": can_recover,
            "coverage_state": coverage_state,
            "coverage_message": coverage_message,
        }

    @app.get("/guardians")
    def guardian_management():
        _remove_legacy_miniguard_guardians()
        config = service.load()
        state = load_state().get("checks", {})
        catalog = guardian_catalog()
        guardians = []

        for check in config.get("checks", []):
            _, beacon_health = _guardian_notification_dependencies(config, check)
            guardians.append({
                "check": check,
                "state": state.get(check.get("id"), {}),
                "metadata": catalog.get(check.get("guardian"), {}),
                "maintenance_active": bool(
                    maintenance_active(check)
                    or runtime_maintenance(check.get("id"))
                ),
                "beacon_health": beacon_health,
            })

        groups = sorted({
            item["check"].get("group") or "Ohne Gruppe"
            for item in guardians
        })
        tags = sorted({
            tag
            for item in guardians
            for tag in item["check"].get("tags", [])
        }, key=str.casefold)

        active = [
            item
            for item in guardians
            if item["check"].get("enabled", True)
        ]
        direct_add_groups = sorted(
            grouped_guardians(catalog.values()),
            key=lambda group: group["label"].casefold(),
        )
        return render_template(
            "guardians.html",
            guardians=guardians,
            groups=groups,
            tags=tags,
            direct_add_groups=direct_add_groups,
            all_checks=config.get("checks", []),
            miniguards=list_miniguards(),
            guardian_count=len(guardians),
            ok_count=len([
                item
                for item in active
                if int(item["state"].get("level", 0) or 0) == 0
            ]),
            warning_count=len([
                item
                for item in active
                if int(item["state"].get("level", 0) or 0) == 1
            ]),
            critical_count=len([
                item
                for item in active
                if int(item["state"].get("level", 0) or 0) >= 2
            ]),
        )

    @app.get("/guardians/routing")
    def guardian_routing_overview():
        config = service.load()
        state = load_state().get("checks", {})
        catalog = guardian_catalog()
        guardian_routes = []

        for check in config.get("checks", []):
            dependencies, beacon_health = (
                _guardian_notification_dependencies(config, check)
            )
            guardian_routes.append({
                "check": check,
                "state": state.get(check.get("id"), {}),
                "metadata": catalog.get(check.get("guardian"), {}),
                "dependencies": dependencies,
                "beacon_health": beacon_health,
            })

        guardian_routes.sort(
            key=lambda item: str(item["check"].get("name", "")).casefold()
        )
        return render_template(
            "guardian_routing_overview.html",
            guardian_routes=guardian_routes,
        )

    @app.get("/guardians/types")
    def guardian_types():
        catalog = list(guardian_catalog().values())
        return render_template(
            "guardian_management.html",
            guardian_groups=grouped_guardians(catalog),
            guardian_count=len(catalog),
        )

    @app.post("/plugins/package/preview/<plugin_type>")
    def plugin_package_preview(plugin_type):
        if plugin_type not in {"guardian", "beacon", "portal"}:
            abort(404)
        upload = request.files.get("package")
        if upload is None or not upload.filename:
            return {"ok": False, "error": "Keine ZIP-Datei ausgewählt."}, 400
        try:
            parsed = parse_package_bytes(
                upload.read(),
                expected_type=plugin_type,
            )
            return {
                "ok": True,
                "manifest": parsed["manifest"],
                "source": parsed["source"],
                "readme": parsed["readme"],
                "translations": parsed["translations"],
            }
        except Exception as error:
            return {"ok": False, "error": str(error)}, 400

    @app.route("/guardians/custom/import",methods=["GET","POST"])
    def custom_guardian_import():
        if request.method=="POST":
            try:
                name=validate_module_name(request.form.get("module_name",""))
                source = request.form.get("source", "")

                if not source.strip():
                    raise ValueError(
                        "Der Quellcode ist leer. Bitte eine Datei laden "
                        "oder Quellcode in das Textfeld einfügen."
                    )

                install_source(
                    source,
                    name,
                    request.form.get("overwrite") == "1",
                )
                guardian_file = custom_path(name)
                translations = {}
                for language in ("de", "en"):
                    raw = request.form.get(
                        f"translation_{language}",
                        "",
                    ).strip()
                    if raw:
                        translations[language] = json.loads(raw)
                manifest_raw = request.form.get("manifest_json", "").strip()
                manifest = (
                    json.loads(manifest_raw)
                    if manifest_raw
                    else default_manifest("guardian", name)
                )
                manifest["module"] = name
                manifest["entrypoint"] = "guardian.py"
                save_package_metadata(
                    guardian_file,
                    manifest,
                    translations,
                    request.form.get("readme_md", ""),
                )
                flash("Custom Guardian installiert.","success")
                return redirect(url_for("guardian_types"))
            except Exception as error: flash(str(error),"error")
        return render_template("custom_guardian_import.html",template_source=guardian_template())

    @app.get("/guardians/custom/template.zip")
    def custom_guardian_template():
        package = template_package(
            "guardian",
            "mein_guardian",
            guardian_template(),
        )
        return send_file(
            package,
            as_attachment=True,
            download_name="mein_guardian.zip",
            mimetype="application/zip",
        )

    @app.get("/guardians/custom/<name>/export")
    def custom_guardian_export(name):
        plugin_file = custom_path(name)
        if not plugin_file.is_file():
            abort(404)
        manifest, translations, readme = (
            package_metadata_for_storage(plugin_file)
        )
        package = build_package_bytes(
            "guardian",
            name,
            plugin_file.read_text(encoding="utf-8"),
            translations=translations,
            manifest=manifest or default_manifest("guardian", name),
            readme=readme or default_readme("guardian", name),
        )
        return send_file(
            package,
            as_attachment=True,
            download_name=f"{name}.zip",
            mimetype="application/zip",
        )

    @app.post("/guardians/custom/<path:name>/delete")
    def custom_guardian_delete(name):
        module_name = (
            name.split(":", 1)[1]
            if name.startswith("custom:")
            else name
        )
        reference = f"custom:{module_name}"

        if any(
            item.get("guardian") == reference
            for item in service.load().get("checks", [])
        ):
            flash(
                "Der Custom Guardian wird noch von einer Instanz verwendet.",
                "error",
            )
        else:
            try:
                delete_custom_guardian(module_name)
                flash("Custom Guardian gelöscht.", "success")
            except Exception as error:
                flash(
                    f"Custom Guardian konnte nicht gelöscht werden: {error}",
                    "error",
                )
        return redirect(url_for("guardian_types"))

    @app.get("/guardian/<check_id>")
    def guardian_detail(check_id):
        config = service.load()
        state = load_state().get("checks", {})
        check = next(
            (
                item
                for item in config.get("checks", [])
                if item.get("id") == check_id
            ),
            None,
        )
        if not check:
            abort(404)

        meta = guardian_catalog().get(check.get("guardian"), {})
        events = database.query_events(
            guardian_id=check_id,
            page=1,
            per_page=20,
        )["rows"]

        notification_dependencies, beacon_health = (
            _guardian_notification_dependencies(config, check)
        )

        smart_history = []
        if check.get("guardian") == "smart":
            history_path = (
                LANAXY_DATA_DIR / "guardian-state" / "smart"
                / f"{check_id}.json"
            )
            try:
                smart_history = json.loads(
                    history_path.read_text(encoding="utf-8")
                )[-100:]
            except (OSError, json.JSONDecodeError):
                smart_history = []

        return render_template(
            "guardian_detail.html",
            check=check,
            state=state.get(check_id, {}),
            metadata=meta,
            events=events,
            maintenance_active=maintenance_active(check),
            smart_history=smart_history,
            notification_dependencies=notification_dependencies,
            beacon_health=beacon_health,
        )

    @app.post("/guardian/<check_id>/test")
    def test_guardian(check_id):
        check = next(
            (
                item
                for item in service.load().get("checks", [])
                if item.get("id") == check_id
            ),
            None,
        )
        if check is None:
            abort(404)

        try:
            payload = test_guardian_via_service(
                check,
                timeout=max(
                    15,
                    int(float(str(check.get("timeout", 3)).replace(",", "."))) * 5,
                ),
            )
            result_payload = payload.get("result") if isinstance(payload, dict) else None
            if isinstance(result_payload, dict):
                result = Result(
                    id=result_payload.get("id") or check_id,
                    name=result_payload.get("name") or check.get("name") or check_id,
                    status=result_payload.get("status", "critical"),
                    level=int(result_payload.get("level", 2)),
                    message=result_payload.get("message", "Manueller Test abgeschlossen"),
                    device_id=result_payload.get("device_id") or check.get("device_id") or check_id,
                    response_time=int(result_payload.get("response_time", 0) or 0),
                    uptime=float(result_payload.get("uptime", 100.0) or 100.0),
                    last_error=result_payload.get("last_error", ""),
                    last_recovery=result_payload.get("last_recovery", ""),
                    details=result_payload.get("details") or {},
                    last_check=result_payload.get("last_check") or datetime.now().isoformat(timespec="seconds"),
                )
                state_store = StateStore(str(state_path))
                retries = int(float(str(check.get("retries", 1)).replace(",", ".")))
                _, result, _, _ = state_store.update_result(result, retries)
                payload["result"] = result.to_dict()
            return payload
        except Exception as error:
            return {
                "ok": False,
                "error": (
                    "Der Guardian-Testdienst ist nicht erreichbar: "
                    + str(error)
                ),
                "result": {
                    "status": "critical",
                    "level": 2,
                    "message": (
                        "Manueller Test konnte nicht ausgeführt werden"
                    ),
                    "response_time": 0,
                    "details": {
                        "error": str(error),
                    },
                },
            }, 503

    @app.post("/guardian/<check_id>/maintenance/start")
    def maintenance_start(check_id):
        config = service.load()
        check = next(
            (item for item in config.get("checks", []) if item.get("id") == check_id),
            None,
        )
        if check is None:
            abort(404)

        until = request.form.get("until", "").strip()
        control_engine.execute(
            {
                "command": "end_maintenance",
                "target": check_id,
            },
            "web:guardian",
        )
        check["maintenance"] = {
            "active": True,
            "until": until,
        }
        service.save(config)
        database.add_event(
            "MAINTENANCE_START",
            f"Wartungsmodus für {check.get('name', check_id)} aktiviert",
            status="maintenance",
            guardian_id=check_id,
            guardian_name=check.get("name", check_id),
            details={"until": until},
        )
        restart_lanaxy()
        flash("Wartungsmodus aktiviert.", "success")
        return redirect(url_for("guardian_detail", check_id=check_id))

    @app.post("/guardian/<check_id>/maintenance/stop")
    def maintenance_stop(check_id):
        config = service.load()
        check = next(
            (item for item in config.get("checks", []) if item.get("id") == check_id),
            None,
        )
        if check is None:
            abort(404)

        check.pop("maintenance", None)
        service.save(config)

        # Maintenance may have been activated through the Control Engine
        # (HTTP, MQTT, CLI or Dashboard) instead of the Guardian form.
        control_engine.execute(
            {
                "command": "end_maintenance",
                "target": check_id,
            },
            "web:guardian",
        )

        database.add_event(
            "MAINTENANCE_STOP",
            f"Wartungsmodus für {check.get('name', check_id)} beendet",
            status="ok",
            guardian_id=check_id,
            guardian_name=check.get("name", check_id),
        )
        restart_lanaxy()
        flash("Wartungsmodus beendet.", "success")
        return redirect(url_for("guardian_detail", check_id=check_id))


    @app.get("/beacons")
    def beacons_page():
        config = service.load()
        notifications = config.setdefault("notifications", {})
        channels = notifications.setdefault("channels", [])
        rules = notifications.setdefault("rules", [])

        if not notifications.get("default_rule_initialized") and not rules:
            rules.append({
                "id": "default_1",
                "name": "Default",
                "enabled": True,
                "statuses": ["warning", "critical", "recovery"],
                "all_channels": True,
                "channels": [],
                "all_groups": True,
                "groups": [],
                "all_guardians": True,
                "guardians": [],
                "root_cause_only": False,
            })
            notifications["default_rule_initialized"] = True
            service.save(config)
        elif not notifications.get("default_rule_initialized"):
            notifications["default_rule_initialized"] = True
            service.save(config)

        rule_usage = {}
        for rule in rules:
            channel_ids = (
                [channel.get("id") for channel in channels]
                if rule.get("all_channels")
                else rule.get("channels", [])
            )
            for channel_id in channel_ids:
                rule_usage[channel_id] = rule_usage.get(channel_id, 0) + 1

        return render_template(
            "beacons.html",
            channels=channels,
            status=load_notification_status(),
            beacon_types=list(localized_beacon_catalog().values()),
            rule_usage=rule_usage,
            missing_rule_warning=bool(channels and not rules),
            muted_beacons=control_engine.state.snapshot().get(
                "muted_beacons",
                {},
            ),
        )

    @app.route("/ai", methods=["GET", "POST"])
    def ai_assistant():
        config = service.load()
        ai_config = config.setdefault("ai", {})
        plan = None
        request_text = ""
        if request.method == "POST":
            request_text = request.form.get("request_text", "").strip()
            if not request_text:
                flash("Bitte beschreibe, was LANaxy anlegen soll.", "error")
            else:
                try:
                    plan = ai_generate_plan(ai_config, request_text, guardian_catalog(), config)
                    plan = ai_validate_plan(plan, guardian_catalog(), config)
                    session["ai_plan"] = plan
                    session["ai_request"] = request_text
                except Exception as error:
                    flash(str(error), "error")
        elif session.get("ai_plan"):
            plan = session.get("ai_plan")
            request_text = session.get("ai_request", "")
        if plan:
            catalog = guardian_catalog()
            for guardian in plan.get("guardians", []):
                metadata = catalog.get(guardian.get("type"), {})
                guardian["category_key"] = guardian_category_key(metadata.get("category"))
                schema = metadata.get("schema", {})
                editable_keys = []
                for key, field in schema.items():
                    if key in {"name", "id", "device_id"} or field.get("type") == "hidden":
                        continue
                    if key in guardian.get("config", {}) or key in guardian.get("missing_fields", []):
                        editable_keys.append(key)
                guardian["editable_field_definitions"] = [
                    {
                        "key": key,
                        "label": schema.get(key, {}).get("label") or key.replace("_", " ").title(),
                        "type": schema.get(key, {}).get("type", "text"),
                        "options": schema.get(key, {}).get("options", []),
                        "secret": schema.get(key, {}).get("secret", False) or any(part in key.lower() for part in ("secret", "password")),
                        "required": key in guardian.get("missing_fields", []),
                    }
                    for key in editable_keys
                ]
        existing_beacons = [
            {
                "id": beacon.get("id"),
                "name": beacon.get("name"),
                "type": beacon.get("type"),
                "enabled": beacon.get("enabled", True),
            }
            for beacon in config.get("notifications", {}).get("channels", [])
        ]
        return render_template(
            "ai_assistant.html",
            plan=plan,
            request_text=request_text,
            ai_config=ai_config,
            existing_beacons=existing_beacons,
        )

    def update_ai_plan_from_form(plan):
        catalog = guardian_catalog()
        for index, guardian in enumerate(plan.get("guardians", [])):
            schema = catalog.get(guardian.get("type"), {}).get("schema", {})
            config = guardian.setdefault("config", {})
            for key, field in schema.items():
                if key in {"name", "id", "device_id"} or field.get("type") == "hidden":
                    continue
                form_key = f"guardian_{index}_{key}"
                if form_key not in request.form:
                    continue
                raw = request.form.get(form_key, "").strip()
                secret = field.get("secret", False) or any(part in key.lower() for part in ("secret", "password"))
                if raw == "" and secret and config.get(key):
                    continue
                if raw == "":
                    config.pop(key, None)
                    continue
                field_type = field.get("type", "text")
                if field_type in {"number", "integer"}:
                    try:
                        numeric = float(raw.replace(",", "."))
                        value = int(numeric) if numeric.is_integer() else numeric
                        if field_type == "integer" and not numeric.is_integer():
                            raise ValueError
                    except ValueError:
                        raise ValueError(f"{guardian.get('name')}: {key} ist keine gültige Zahl.")
                elif field_type == "checkbox":
                    value = raw.lower() in {"1", "true", "on", "yes"}
                else:
                    value = raw
                config[key] = value
        return ai_validate_plan(plan, catalog, service.load())

    @app.post("/ai/apply")
    def ai_apply():
        plan = session.get("ai_plan")
        if not plan:
            flash("Es liegt kein KI-Plan zur Bestätigung vor.", "error")
            return redirect(url_for("ai_assistant"))
        try:
            plan = update_ai_plan_from_form(plan)
            session["ai_plan"] = plan
            config = ai_apply_plan(plan, service.load())
            enforce_routing_safety(config)
            service.save(config)
            restart_lanaxy()
            session.pop("ai_plan", None)
            session.pop("ai_request", None)
            flash("Der KI-Plan wurde vollständig angelegt.", "success")
            return redirect(url_for("guardian_management"))
        except Exception as error:
            flash(str(error), "error")
            return redirect(url_for("ai_assistant"))

    @app.post("/ai/discard")
    def ai_discard():
        session.pop("ai_plan", None)
        session.pop("ai_request", None)
        flash("Der KI-Plan wurde verworfen.", "success")
        return redirect(url_for("ai_assistant"))

    @app.route("/settings/ai", methods=["GET", "POST"])
    def ai_settings():
        config = service.load()
        ai_config = config.setdefault("ai", {})
        if request.method == "POST":
            provider = request.form.get("provider", "openai")
            info = ai_provider_catalog().get(provider)
            if not info:
                flash("Unbekannter KI-Anbieter.", "error")
            else:
                ai_config["provider"] = provider
                ai_config["base_url"] = request.form.get("base_url", "").strip() or info["default_base_url"]
                ai_config["model"] = request.form.get("model", "").strip() or info["default_model"]
                key = request.form.get("api_key", "")
                if key and key != AI_SECRET_PLACEHOLDER:
                    ai_config["api_key"] = key.strip()
                service.save(config)
                flash("KI-Einstellungen wurden gespeichert.", "success")
                return redirect(url_for("ai_settings"))
        display = dict(ai_config)
        if display.get("api_key"):
            display["api_key"] = AI_SECRET_PLACEHOLDER
        return render_template("ai_settings.html", ai=display, providers=ai_provider_catalog(),
                               secret_placeholder=AI_SECRET_PLACEHOLDER)

    @app.get("/settings")
    def settings_redirect():
        return redirect(url_for("rules_page"))

    @app.get("/rules")
    def rules_page():
        config = service.load()
        notifications = config.setdefault("notifications", {})
        channels = notifications.setdefault("channels", [])
        rules = notifications.setdefault("rules", [])
        channel_map = {channel.get("id"): channel for channel in channels}
        rule_beacon_status = {}
        for rule in rules:
            if rule.get("all_channels"):
                selected_ids = [channel.get("id") for channel in channels if channel.get("id")]
            else:
                selected_ids = [str(channel_id) for channel_id in rule.get("channels", []) if channel_id]
            active_ids = [
                channel_id for channel_id in selected_ids
                if channel_map.get(channel_id, {}).get("enabled", True)
            ]
            rule_beacon_status[str(rule.get("id", ""))] = {
                "selected": len(selected_ids),
                "active": len(active_ids),
            }
        safety_findings = routing_findings(config)
        return render_template(
            "rules.html",
            safety_findings=safety_findings,
            rules=rules,
            channels=channel_map,
            rule_beacon_status=rule_beacon_status,
            paused_rules=control_engine.state.snapshot().get(
                "paused_rules",
                {},
            ),
        )

    @app.route("/settings/system-mqtt", methods=["GET", "POST"])
    def system_mqtt_settings():
        config = service.load()
        mqtt_config = config.setdefault("mqtt", {})

        if request.method == "POST":
            try:
                password = request.form.get("password", "")
                mqtt_config.update({
                    "enabled": request.form.get("enabled") == "1",
                    "host": request.form.get("host", "").strip(),
                    "port": int(request.form.get("port", 1883)),
                    "user": request.form.get("user", "").strip(),
                    "base_topic": request.form.get("base_topic", "lanaxy").strip(),
                    "retain": request.form.get("retain") == "1",
                    "keepalive": int(request.form.get("keepalive", 60)),
                    "homeassistant_discovery": request.form.get("homeassistant_discovery") == "1",
                    "discovery_prefix": request.form.get("discovery_prefix", "homeassistant").strip() or "homeassistant",
                })
                if password and password != NOTIFICATION_SECRET:
                    mqtt_config["password"] = password
                service.save(config)
                restart_lanaxy()
                flash("System-MQTT wurde gespeichert.", "success")
                return redirect(url_for("system_page") + "#system-mqtt")
            except Exception as error:
                flash(str(error), "error")

        return render_template(
            "system_mqtt_form.html",
            mqtt=mqtt_config,
            secret_placeholder=NOTIFICATION_SECRET,
        )

    @app.post("/beacons/<channel_id>/mute")
    def notification_channel_mute(channel_id):
        duration = max(
            1,
            min(
                10080,
                int(request.form.get("duration_minutes", 60)),
            ),
        )
        result = control_engine.execute(
            {
                "command": "mute_beacon",
                "target": channel_id,
                "duration_minutes": duration,
                "reason": request.form.get(
                    "reason",
                    "Über die Weboberfläche stummgeschaltet",
                ),
            },
            "web:beacons",
        )
        flash(
            (
                f"Beacon wurde für {duration} Minuten stummgeschaltet."
                if result.get("ok")
                else result.get("error", "Beacon konnte nicht stummgeschaltet werden.")
            ),
            "success" if result.get("ok") else "error",
        )
        return redirect(url_for("beacons_page"))

    @app.post("/beacons/<channel_id>/unmute")
    def notification_channel_unmute(channel_id):
        result = control_engine.execute(
            {
                "command": "unmute_beacon",
                "target": channel_id,
            },
            "web:beacons",
        )
        flash(
            (
                "Beacon-Stummschaltung wurde aufgehoben."
                if result.get("ok")
                else result.get("error", "Stummschaltung konnte nicht aufgehoben werden.")
            ),
            "success" if result.get("ok") else "error",
        )
        return redirect(url_for("beacons_page"))

    @app.post("/rules/<rule_id>/pause")
    def notification_rule_pause(rule_id):
        duration = max(
            1,
            min(
                10080,
                int(request.form.get("duration_minutes", 60)),
            ),
        )
        result = control_engine.execute(
            {
                "command": "pause_rule",
                "target": rule_id,
                "duration_minutes": duration,
                "reason": request.form.get(
                    "reason",
                    "Über die Weboberfläche pausiert",
                ),
            },
            "web:rules",
        )
        flash(
            (
                f"Rule wurde für {duration} Minuten pausiert."
                if result.get("ok")
                else result.get("error", "Rule konnte nicht pausiert werden.")
            ),
            "success" if result.get("ok") else "error",
        )
        return redirect(url_for("rules_page"))

    @app.post("/rules/<rule_id>/resume")
    def notification_rule_resume(rule_id):
        result = control_engine.execute(
            {
                "command": "resume_rule",
                "target": rule_id,
            },
            "web:rules",
        )
        flash(
            (
                "Rule wurde fortgesetzt."
                if result.get("ok")
                else result.get("error", "Rule konnte nicht fortgesetzt werden.")
            ),
            "success" if result.get("ok") else "error",
        )
        return redirect(url_for("rules_page"))

    @app.route("/settings/channel/add/<channel_type>", methods=["GET", "POST"])
    def notification_channel_add(channel_type):
        catalog = localized_beacon_catalog()
        if channel_type not in catalog:
            abort(404)
        config = service.load()
        channels = config.setdefault("notifications", {}).setdefault("channels", [])

        if request.method == "POST":
            try:
                channel = build_channel(
                    request.form,
                    channel_type,
                    all_channels=channels,
                )
                channels.append(channel)
                enforce_routing_safety(config)
                service.save(config)
                restart_lanaxy()
                flash("Benachrichtigungskanal wurde angelegt.", "success")
                return redirect(url_for("beacons_page"))
            except Exception as error:
                flash(str(error), "error")

        default_channel = {
            "name": next_name(channels, catalog[channel_type].get("name", channel_type)),
            "enabled": True,
        }
        return render_template(
            "notification_channel_form.html",
            mode="add",
            channel=default_channel,
            channel_type=channel_type,
            schema=catalog[channel_type],
            secret_placeholder=NOTIFICATION_SECRET,
        )

    @app.route("/settings/channel/<channel_id>/edit", methods=["GET", "POST"])
    def notification_channel_edit(channel_id):
        config = service.load()
        channels = config.setdefault("notifications", {}).setdefault("channels", [])
        channel = find_channel(config, channel_id)
        if channel is None:
            abort(404)

        if request.method == "POST":
            try:
                updated = build_channel(
                    request.form,
                    channel["type"],
                    existing=channel,
                    all_channels=channels,
                )
                channels[channels.index(channel)] = updated
                enforce_routing_safety(config)
                service.save(config)
                restart_lanaxy()
                flash("Benachrichtigungskanal wurde gespeichert.", "success")
                return redirect(url_for("beacons_page"))
            except Exception as error:
                flash(str(error), "error")

        return render_template(
            "notification_channel_form.html",
            mode="edit",
            channel=channel,
            channel_type=channel["type"],
            schema=localized_beacon_catalog()[channel["type"]],
            secret_placeholder=NOTIFICATION_SECRET,
        )

    @app.post("/settings/channel/<channel_id>/test")
    def notification_channel_test(channel_id):
        config = service.load()
        channel = find_channel(config, channel_id)
        if channel is None:
            abort(404)
        try:
            started = time.perf_counter()
            test_channel(channel, current_language())
            duration_ms = round((time.perf_counter() - started) * 1000)
            database.record_delivery(
                {
                    "source": "Beacon-Test",
                    "kind": "test",
                    "message": "Testnachricht",
                },
                {
                    "id": "manual_test",
                    "name": "Manueller Test",
                },
                channel,
                True,
            )
            record_channel_result(channel_id, True)
            flash(
                translate(
                    current_language(),
                    "beacons.test_success",
                )
                + " "
                + translate(
                    current_language(),
                    "beacons.test_duration",
                    duration=duration_ms,
                ),
                "success",
            )
        except Exception as error:
            database.record_delivery(
                {
                    "source": "Beacon-Test",
                    "kind": "test",
                    "message": "Testnachricht",
                },
                {
                    "id": "manual_test",
                    "name": "Manueller Test",
                },
                channel,
                False,
                str(error),
            )
            record_channel_result(channel_id, False, str(error))
            flash(
                translate(
                    current_language(),
                    "beacons.test_failed",
                    error=str(error),
                ),
                "error",
            )
        return redirect(url_for("beacons_page"))

    @app.post("/beacons/test-live/<path:channel_type>")
    def notification_channel_live_test(channel_type):
        config = service.load()
        channels = config.setdefault(
            "notifications",
            {},
        ).setdefault("channels", [])
        existing_id = request.form.get("_channel_id", "").strip()
        existing = (
            find_channel(config, existing_id)
            if existing_id
            else None
        )

        try:
            temporary = build_channel(
                request.form,
                channel_type,
                existing=existing,
                all_channels=channels,
            )
            temporary["id"] = existing_id or "temporary_test"
            started = time.perf_counter()
            test_channel(temporary, current_language())
            duration_ms = round(
                (time.perf_counter() - started) * 1000
            )
            return {
                "ok": True,
                "message": translate(
                    current_language(),
                    "beacons.test_success",
                ),
                "duration_ms": duration_ms,
            }
        except Exception as error:
            return {
                "ok": False,
                "error": str(error),
            }, 400

    @app.post("/settings/channel/<channel_id>/toggle")
    def notification_channel_toggle(channel_id):
        config = service.load()
        channel = find_channel(config, channel_id)
        if channel is None:
            abort(404)
        channel["enabled"] = not channel.get("enabled", True)
        service.save(config)
        restart_lanaxy()
        return redirect(url_for("beacons_page"))

    @app.post("/settings/channel/<channel_id>/duplicate")
    def notification_channel_duplicate(channel_id):
        config = service.load()
        channels = config.setdefault("notifications", {}).setdefault("channels", [])
        channel = find_channel(config, channel_id)
        if channel is None:
            abort(404)
        duplicate = dict(channel)
        duplicate["name"] = f"{channel.get('name', channel_id)} Kopie"
        from notification_config import next_id
        duplicate["id"] = next_id(channels, duplicate["name"])
        channels.append(duplicate)
        service.save(config)
        restart_lanaxy()
        flash("Kanal wurde dupliziert.", "success")
        return redirect(url_for("beacons_page"))

    @app.post("/settings/channel/<channel_id>/delete")
    def notification_channel_delete(channel_id):
        config = service.load()
        notifications = config.setdefault("notifications", {})
        channels = notifications.setdefault("channels", [])
        notifications["channels"] = [
            channel for channel in channels if channel.get("id") != channel_id
        ]
        for rule in notifications.setdefault("rules", []):
            rule["channels"] = [
                item for item in rule.get("channels", []) if item != channel_id
            ]
        service.save(config)
        restart_lanaxy()
        flash("Kanal wurde gelöscht.", "success")
        return redirect(url_for("beacons_page"))

    @app.route("/settings/rule/add", methods=["GET", "POST"])
    @app.route("/settings/rule/<rule_id>/edit", methods=["GET", "POST"])
    def notification_rule_form(rule_id=None):
        config = service.load()
        notifications = config.setdefault("notifications", {})
        rules = notifications.setdefault("rules", [])
        channels = notifications.setdefault("channels", [])
        checks = config.get("checks", [])
        groups = sorted({check.get("group") for check in checks if check.get("group")})
        rule = next((item for item in rules if item.get("id") == rule_id), None) if rule_id else None

        if request.method == "POST":
            try:
                name = request.form.get("name", "").strip()
                if not name:
                    raise ValueError("Bitte einen Namen eingeben.")

                valid_channel_ids = {
                    str(item.get("id")) for item in channels if item.get("id")
                }
                valid_guardian_ids = {
                    str(item.get("id")) for item in checks if item.get("id")
                }
                selected_channels = list(dict.fromkeys(
                    value for value in request.form.getlist("channels")
                    if value in valid_channel_ids
                ))
                selected_guardians = list(dict.fromkeys(
                    value for value in request.form.getlist("guardians")
                    if value in valid_guardian_ids
                ))

                updated = dict(rule or {})
                updated.update({
                    "name": name,
                    "enabled": request.form.get("enabled") == "1",
                    "statuses": request.form.getlist("statuses"),
                    "all_channels": request.form.get("all_channels") == "1",
                    "channels": selected_channels,
                    "all_groups": request.form.get("all_groups") == "1",
                    "groups": request.form.getlist("groups"),
                    "all_guardians": request.form.get("all_guardians") == "1",
                    "guardians": selected_guardians,
                    "root_cause_only": request.form.get("root_cause_only") == "1",
                    "quiet_hours_enabled": request.form.get("quiet_hours_enabled") == "1",
                    "quiet_start": request.form.get("quiet_start", "").strip(),
                    "quiet_end": request.form.get("quiet_end", "").strip(),
                    "delay_seconds": max(0, int(request.form.get("delay_seconds", 0) or 0)),
                    "repeat_minutes": max(0, int(request.form.get("repeat_minutes", 0) or 0)),
                    "repeat_count": max(0, int(request.form.get("repeat_count", 0) or 0)),
                    "escalation_steps": [
                        {
                            "after_minutes": max(
                                0,
                                int(
                                    request.form.get(
                                        f"escalation_{index}_minutes",
                                        0,
                                    )
                                    or 0
                                ),
                            ),
                            "channels": request.form.getlist(
                                f"escalation_{index}_channels"
                            ),
                        }
                        for index in (1, 2)
                        if int(
                            request.form.get(
                                f"escalation_{index}_minutes",
                                0,
                            )
                            or 0
                        ) > 0
                        and request.form.getlist(
                            f"escalation_{index}_channels"
                        )
                    ],
                })
                if not updated["statuses"]:
                    raise ValueError("Mindestens einen Status auswählen.")
                if not updated["all_channels"] and not updated["channels"]:
                    raise ValueError(
                        "Bitte 'Alle Kanäle' aktivieren oder mindestens "
                        "einen Kanal auswählen."
                    )
                if not updated.get("id"):
                    from notification_config import next_id
                    updated["id"] = next_id(rules, name)
                    rules.append(updated)
                else:
                    rules[rules.index(rule)] = updated
                safety_findings = analyze_rule(
                    updated,
                    config,
                    guardian_catalog(),
                    localized_beacon_catalog(),
                )
                hard_conflicts = blocking_findings(safety_findings)
                if hard_conflicts:
                    raise ValueError(
                        "Unsichere Benachrichtigungsroute: "
                        + hard_conflicts[0]["message"]
                    )
                for finding in safety_findings:
                    if finding.get("level") == "warning":
                        flash(
                            "Hinweis zur Benachrichtigungsroute: "
                            + finding["message"],
                            "warning",
                        )

                service.save(config)
                restart_lanaxy()
                flash("Rule wurde gespeichert.", "success")
                return redirect(url_for("rules_page"))
            except Exception as error:
                flash(str(error), "error")
                rule = updated if "updated" in locals() else {
                    "name": request.form.get("name", ""),
                    "statuses": request.form.getlist("statuses"),
                    "all_channels": request.form.get("all_channels") == "1",
                    "channels": request.form.getlist("channels"),
                    "all_groups": request.form.get("all_groups") == "1",
                    "groups": request.form.getlist("groups"),
                    "all_guardians": request.form.get("all_guardians") == "1",
                    "guardians": request.form.getlist("guardians"),
                    "enabled": request.form.get("enabled") == "1",
                }

        return render_template(
            "notification_rule_form.html",
            rule=rule or {},
            channels=channels,
            checks=checks,
            groups=groups,
        )

    @app.post("/rules/<rule_id>/test")
    def notification_rule_test(rule_id):
        config = service.load()
        notifications = config.setdefault("notifications", {})
        rules = notifications.setdefault("rules", [])
        channels = notifications.setdefault("channels", [])
        rule = next((item for item in rules if item.get("id") == rule_id), None)
        if rule is None:
            abort(404)

        selected_ids = (
            {str(channel.get("id")) for channel in channels}
            if rule.get("all_channels")
            else {str(item) for item in rule.get("channels", [])}
        )
        selected = [
            channel for channel in channels
            if str(channel.get("id")) in selected_ids
            and channel.get("enabled", True)
        ]
        if not selected:
            flash("Rule-Test nicht möglich: Kein ausgewählter Beacon ist aktiv.", "warning")
            return redirect(url_for("rules_page"))

        successes = 0
        errors = []
        for channel in selected:
            try:
                test_channel(channel, current_language())
                database.record_delivery(
                    {
                        "source": "Rule-Test",
                        "guardian_name": "Beispiel-Guardian",
                        "guardian_id": "rule_test",
                        "kind": "test",
                        "message": f"Test der Rule {rule.get('name', rule_id)}",
                    },
                    {"id": rule_id, "name": rule.get("name", rule_id)},
                    channel,
                    True,
                )
                record_channel_result(channel.get("id", ""), True)
                successes += 1
            except Exception as error:
                record_channel_result(channel.get("id", ""), False, str(error))
                try:
                    database.record_delivery(
                        {
                            "source": "Rule-Test",
                            "guardian_name": "Beispiel-Guardian",
                            "guardian_id": "rule_test",
                            "kind": "test",
                            "message": f"Test der Rule {rule.get('name', rule_id)}",
                        },
                        {"id": rule_id, "name": rule.get("name", rule_id)},
                        channel,
                        False,
                        str(error),
                    )
                except Exception:
                    pass
                errors.append(f"{channel.get('name', channel.get('id'))}: {error}")

        if errors:
            flash(
                f"Rule-Test: {successes} Beacon(s) erfolgreich, {len(errors)} fehlgeschlagen. "
                + " | ".join(errors),
                "warning",
            )
        else:
            flash(f"Rule-Test über {successes} aktive Beacon(s) erfolgreich.", "success")
        return redirect(url_for("rules_page"))

    @app.post("/rules/<rule_id>/toggle")
    def notification_rule_toggle(rule_id):
        config = service.load()
        rules = config.setdefault("notifications", {}).setdefault("rules", [])
        rule = next((item for item in rules if item.get("id") == rule_id), None)
        if rule is None:
            abort(404)
        rule["enabled"] = not rule.get("enabled", True)
        try:
            if rule["enabled"]:
                enforce_routing_safety(config)
            service.save(config)
        except Exception as error:
            rule["enabled"] = not rule["enabled"]
            flash(str(error), "error")
            return redirect(url_for("rules_page"))
        restart_lanaxy()
        return redirect(url_for("rules_page"))

    @app.post("/rules/<rule_id>/duplicate")
    def notification_rule_duplicate(rule_id):
        config = service.load()
        rules = config.setdefault("notifications", {}).setdefault("rules", [])
        rule = next((item for item in rules if item.get("id") == rule_id), None)
        if rule is None:
            abort(404)
        from notification_config import next_id
        duplicate = dict(rule)
        duplicate["name"] = f"{rule.get('name', rule_id)} Kopie"
        duplicate["id"] = next_id(rules, duplicate["name"])
        rules.append(duplicate)
        service.save(config)
        restart_lanaxy()
        flash("Rule wurde dupliziert.", "success")
        return redirect(url_for("rules_page"))

    @app.post("/settings/rule/<rule_id>/delete")
    def notification_rule_delete(rule_id):
        config = service.load()
        notifications = config.setdefault("notifications", {})
        notifications["rules"] = [
            rule for rule in notifications.get("rules", []) if rule.get("id") != rule_id
        ]
        service.save(config)
        restart_lanaxy()
        return redirect(url_for("rules_page"))


    @app.post("/settings/telegram/discover")
    def telegram_discover():
        config = service.load()
        token = request.form.get("bot_token", "").strip()
        channel_id = request.form.get("channel_id", "").strip()

        if token == NOTIFICATION_SECRET and channel_id:
            channel = find_channel(config, channel_id)
            if channel and channel.get("type") == "telegram":
                token = channel.get("bot_token", "")

        try:
            return discover_telegram_chats(token)
        except Exception as error:
            return {
                "ok": False,
                "error": str(error),
                "chats": [],
            }, 400


    @app.get("/settings/beacons")
    def beacon_management():
        beacons = list(localized_beacon_catalog().values())
        return render_template(
            "beacon_management.html",
            builtin=[item for item in beacons if item.get("source") == "builtin"],
            custom=[item for item in beacons if item.get("source") == "custom"],
        )

    @app.route("/settings/beacons/custom/import", methods=["GET", "POST"])
    def custom_beacon_import():
        if request.method == "POST":
            try:
                module_name = validate_beacon_module_name(
                    request.form.get("module_name", "")
                )
                source = request.form.get("source", "")
                if not source.strip():
                    raise ValueError(
                        "Der Quellcode ist leer. Bitte eine Datei laden "
                        "oder Quellcode einfügen."
                    )
                metadata = install_beacon_source(
                    source,
                    module_name,
                    request.form.get("overwrite") == "1",
                )
                beacon_file = custom_beacon_path(module_name)
                translations = {}
                for language in ("de", "en"):
                    raw = request.form.get(
                        f"translation_{language}",
                        "",
                    ).strip()
                    if raw:
                        translations[language] = json.loads(raw)
                manifest_raw = request.form.get("manifest_json", "").strip()
                manifest = (
                    json.loads(manifest_raw)
                    if manifest_raw
                    else default_manifest("beacon", module_name)
                )
                manifest["module"] = module_name
                manifest["entrypoint"] = "beacon.py"
                save_package_metadata(
                    beacon_file,
                    manifest,
                    translations,
                    request.form.get("readme_md", ""),
                )
                flash(
                    f"Custom Beacon '{metadata.get('name', module_name)}' installiert.",
                    "success",
                )
                return redirect(url_for("beacon_management"))
            except Exception as error:
                flash(str(error), "error")

        return render_template(
            "custom_beacon_import.html",
            template_source=beacon_template(),
        )

    @app.get("/settings/beacons/custom/template.zip")
    def custom_beacon_template():
        package = template_package(
            "beacon",
            "mein_beacon",
            beacon_template(),
        )
        return send_file(
            package,
            as_attachment=True,
            download_name="mein_beacon.zip",
            mimetype="application/zip",
        )

    @app.get("/settings/beacons/custom/<module_name>/export")
    def custom_beacon_export(module_name):
        plugin_file = custom_beacon_path(module_name)
        if not plugin_file.is_file():
            abort(404)
        manifest, translations, readme = (
            package_metadata_for_storage(plugin_file)
        )
        package = build_package_bytes(
            "beacon",
            module_name,
            plugin_file.read_text(encoding="utf-8"),
            translations=translations,
            manifest=manifest or default_manifest(
                "beacon",
                module_name,
            ),
            readme=readme or default_readme(
                "beacon",
                module_name,
            ),
        )
        return send_file(
            package,
            as_attachment=True,
            download_name=f"{module_name}.zip",
            mimetype="application/zip",
        )

    @app.post("/settings/beacons/custom/<module_name>/delete")
    def custom_beacon_delete(module_name):
        config = service.load()
        reference = f"custom:{module_name}"

        if any(
            channel.get("type") == reference
            for channel in config.get("notifications", {}).get("channels", [])
        ):
            flash(
                "Der Custom Beacon wird noch von mindestens einer "
                "Beacon-Instanz verwendet.",
                "error",
            )
            return redirect(url_for("beacon_management"))

        try:
            delete_custom_beacon(module_name)
            flash("Custom Beacon wurde gelöscht.", "success")
        except Exception as error:
            flash(str(error), "error")

        return redirect(url_for("beacon_management"))


    @app.get("/portals")
    def portals_page():
        config = service.load()
        items = config.setdefault("control", {}).setdefault("portals", [])
        return render_template(
            "portals.html",
            portals=items,
            portal_types=list(localized_portal_catalog().values()),
            runtime=portal_manager.status(),
        )

    @app.route("/portals/add/<path:portal_type>", methods=["GET", "POST"])
    def portal_add(portal_type):
        catalog = localized_portal_catalog()
        if portal_type not in catalog:
            abort(404)
        config = service.load()
        items = config.setdefault("control", {}).setdefault("portals", [])
        if request.method == "POST":
            try:
                item = build_portal(
                    request.form,
                    portal_type,
                    all_items=items,
                )
                items.append(item)
                service.save(config)
                portal_manager.start(config)
                credentials = {}
                for credential_key in ("webhook_secret", "access_token"):
                    if item.get(credential_key):
                        credentials[credential_key] = item[credential_key]
                if credentials:
                    session["new_portal_credentials"] = {"portal_id": item["id"], **credentials}
                flash("Portal wurde angelegt.", "success")
                return redirect(url_for("portal_edit", portal_id=item["id"]))
            except Exception as error:
                flash(str(error), "error")
        return render_template(
            "portal_form.html",
            mode="add",
            portal={},
            portal_type=portal_type,
            schema=catalog[portal_type],
            secret_placeholder=PORTAL_SECRET,
            control_commands=CONTROL_COMMANDS,
            checks=service.load().get("checks", []),
            base_url=request.url_root.rstrip("/"),
        )

    @app.route("/portals/<portal_id>/edit", methods=["GET", "POST"])
    def portal_edit(portal_id):
        config = service.load()
        items = config.setdefault("control", {}).setdefault("portals", [])
        item = next((x for x in items if x.get("id") == portal_id), None)
        if item is None:
            abort(404)
        if request.method == "POST":
            try:
                updated = build_portal(
                    request.form,
                    item["type"],
                    existing=item,
                    all_items=items,
                )
                items[items.index(item)] = updated
                service.save(config)
                portal_manager.start(config)
                flash("Portal wurde gespeichert.", "success")
                return redirect(url_for("portals_page"))
            except Exception as error:
                flash(str(error), "error")
        return render_template(
            "portal_form.html",
            mode="edit",
            portal=item,
            portal_type=item["type"],
            schema=localized_portal_catalog()[item["type"]],
            secret_placeholder=PORTAL_SECRET,
            control_commands=CONTROL_COMMANDS,
            checks=config.get("checks", []),
            base_url=request.url_root.rstrip("/"),
            one_time_credentials=(lambda value: value if value and value.get("portal_id") == item.get("id") else {})(session.pop("new_portal_credentials", None)),
        )

    @app.post("/portals/<portal_id>/toggle")
    def portal_toggle(portal_id):
        config = service.load()
        item = next(
            (
                x
                for x in config.get("control", {}).get("portals", [])
                if x.get("id") == portal_id
            ),
            None,
        )
        if item is None:
            abort(404)
        item["enabled"] = not item.get("enabled", True)
        service.save(config)
        portal_manager.start(config)
        return redirect(url_for("portals_page"))

    @app.post("/portals/<portal_id>/duplicate")
    def portal_duplicate(portal_id):
        import copy
        from portal_config import next_id
        config = service.load()
        items = config.setdefault("control", {}).setdefault("portals", [])
        item = next((x for x in items if x.get("id") == portal_id), None)
        if item is None:
            abort(404)
        duplicate = copy.deepcopy(item)
        duplicate["name"] = f"{item.get('name', portal_id)} Kopie"
        duplicate["id"] = next_id(items, duplicate["name"])
        duplicate["enabled"] = False
        items.append(duplicate)
        service.save(config)
        portal_manager.start(config)
        flash("Portal wurde dupliziert und zunächst deaktiviert.", "success")
        return redirect(url_for("portals_page"))

    @app.post("/portals/<portal_id>/test")
    def portal_test(portal_id):
        portal = portal_manager.instances.get(portal_id)
        if portal is None:
            flash("Portal ist nicht aktiv.", "error")
        else:
            result = portal.test()
            if result.get("running"):
                flash("Portal ist aktiv und bereit.", "success")
            else:
                flash(
                    "Portal-Test fehlgeschlagen: "
                    + str(result.get("last_error", "unbekannt")),
                    "error",
                )
        return redirect(url_for("portals_page"))

    @app.post("/portals/<portal_id>/delete")
    def portal_delete(portal_id):
        config = service.load()
        items = config.setdefault("control", {}).setdefault("portals", [])
        config["control"]["portals"] = [
            x for x in items if x.get("id") != portal_id
        ]
        service.save(config)
        portal_manager.start(config)
        flash("Portal wurde gelöscht.", "success")
        return redirect(url_for("portals_page"))

    @app.get("/portals/types")
    def portal_management():
        portals = list(localized_portal_catalog().values())
        return render_template(
            "portal_management.html",
            builtin=[x for x in portals if x.get("source") == "builtin"],
            custom=[x for x in portals if x.get("source") == "custom"],
        )

    @app.route("/portals/custom/import", methods=["GET", "POST"])
    def custom_portal_import():
        if request.method == "POST":
            try:
                module_name = validate_portal_module_name(
                    request.form.get("module_name", "")
                )
                source = request.form.get("source", "")
                metadata = install_portal_source(
                    source,
                    module_name,
                    request.form.get("overwrite") == "1",
                )
                translations = {}
                for language in ("de", "en"):
                    raw = request.form.get(
                        f"translation_{language}", ""
                    ).strip()
                    if raw:
                        translations[language] = json.loads(raw)
                manifest_raw = request.form.get("manifest_json", "").strip()
                manifest = (
                    json.loads(manifest_raw)
                    if manifest_raw
                    else default_manifest("portal", module_name)
                )
                manifest.update({
                    "module": module_name,
                    "entrypoint": "portal.py",
                    "type": "portal",
                })
                save_package_metadata(
                    custom_portal_path(module_name),
                    manifest,
                    translations,
                    request.form.get("readme_md", ""),
                )
                flash(
                    f"Custom Portal '{metadata.get('name', module_name)}' installiert.",
                    "success",
                )
                return redirect(url_for("portal_management"))
            except Exception as error:
                flash(str(error), "error")
        return render_template(
            "custom_portal_import.html",
            template_source=portal_template(),
        )

    @app.get("/portals/custom/template.zip")
    def custom_portal_template():
        package = template_package(
            "portal",
            "mein_portal",
            portal_template(),
        )
        return send_file(
            package,
            as_attachment=True,
            download_name="mein_portal.zip",
            mimetype="application/zip",
        )

    @app.get("/portals/custom/<module_name>/export")
    def custom_portal_export(module_name):
        plugin_file = custom_portal_path(module_name)
        if not plugin_file.is_file():
            abort(404)
        manifest, translations, readme = package_metadata_for_storage(plugin_file)
        package = build_package_bytes(
            "portal",
            module_name,
            plugin_file.read_text(encoding="utf-8"),
            translations=translations,
            manifest=manifest or default_manifest("portal", module_name),
            readme=readme or default_readme("portal", module_name),
        )
        return send_file(
            package,
            as_attachment=True,
            download_name=f"{module_name}.zip",
            mimetype="application/zip",
        )

    @app.post("/portals/custom/<module_name>/delete")
    def custom_portal_delete(module_name):
        config = service.load()
        reference = f"custom:{module_name}"
        if any(
            x.get("type") == reference
            for x in config.get("control", {}).get("portals", [])
        ):
            flash("Das Custom Portal wird noch verwendet.", "error")
        else:
            delete_custom_portal(module_name)
            flash("Custom Portal wurde gelöscht.", "success")
        return redirect(url_for("portal_management"))

    def _portal_request_allowed(portal):
        allowlist = {
            value.strip()
            for value in str(portal.get("ip_allowlist", "")).split(",")
            if value.strip()
        }
        return not allowlist or request.remote_addr in allowlist

    def _portal_command_allowed(portal, payload):
        allowed = str(portal.get("allowed_commands", "*"))
        return allowed == "*" or payload.get("command") in {
            value.strip() for value in allowed.split(",") if value.strip()
        }

    def _execute_portal_request(portal, payload, source):
        if not isinstance(payload, dict):
            return {"ok": False, "error": "JSON-Objekt erwartet."}, 400
        if not _portal_request_allowed(portal):
            return {"ok": False, "error": "IP ist für dieses Portal nicht erlaubt."}, 403
        if not _portal_command_allowed(portal, payload):
            return {"ok": False, "error": "Befehl ist für dieses Portal nicht erlaubt."}, 403
        result = control_engine.execute(payload, source)
        return result, (200 if result.get("ok") else 400)

    @app.post("/api/control/webhook/<portal_id>/<secret>")
    def control_webhook_command(portal_id, secret):
        config = service.load()
        portal = next((item for item in config.get("control", {}).get("portals", []) if item.get("id") == portal_id and item.get("type") == "webhook" and item.get("enabled", True)), None)
        if portal is None:
            return {"ok": False, "error": "Webhook-Portal nicht gefunden oder deaktiviert."}, 404
        if not secrets.compare_digest(str(portal.get("webhook_secret", "")), str(secret)):
            return {"ok": False, "error": "Ungültiger Webhook-Schlüssel."}, 401
        return _execute_portal_request(portal, request.get_json(silent=True), f"webhook:{portal_id}")

    @app.post("/api/control/cli/<portal_id>")
    def control_cli_command(portal_id):
        config = service.load()
        portal = next((item for item in config.get("control", {}).get("portals", []) if item.get("id") == portal_id and item.get("type") == "cli" and item.get("enabled", True)), None)
        if portal is None:
            return {"ok": False, "error": "CLI-Portal nicht gefunden oder deaktiviert."}, 404
        header = request.headers.get("Authorization", "")
        token = header[7:].strip() if header.startswith("Bearer ") else ""
        if not secrets.compare_digest(str(portal.get("access_token", "")), token):
            return {"ok": False, "error": "Ungültiger CLI-Zugriffstoken."}, 401
        return _execute_portal_request(portal, request.get_json(silent=True), f"cli:{portal_id}")

    @app.post("/api/control/command")
    def control_http_command():
        config = service.load()
        http_portals = [
            item
            for item in config.get("control", {}).get("portals", [])
            if item.get("type") == "http" and item.get("enabled", True)
        ]
        if not http_portals:
            return {"ok": False, "error": "HTTP Portal ist nicht aktiviert."}, 404
        header = request.headers.get("Authorization", "")
        token = header[7:].strip() if header.startswith("Bearer ") else ""
        if not verify_control_token(config, token):
            return {"ok": False, "error": "Ungültiger Control-Token."}, 401
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return {"ok": False, "error": "JSON-Objekt erwartet."}, 400
        portal = http_portals[0]
        allowlist = {
            value.strip()
            for value in str(portal.get("ip_allowlist", "")).split(",")
            if value.strip()
        }
        if allowlist and request.remote_addr not in allowlist:
            return {"ok": False, "error": "IP ist nicht erlaubt."}, 403
        allowed = str(portal.get("allowed_commands", "*"))
        if allowed != "*" and payload.get("command") not in {
            x.strip() for x in allowed.split(",") if x.strip()
        }:
            return {"ok": False, "error": "Befehl ist nicht erlaubt."}, 403
        result = control_engine.execute(
            payload,
            f"http:{portal.get('id', 'portal')}",
        )
        return result, (200 if result.get("ok") else 400)

    @app.post("/system/control/token")
    def control_token_generate():
        config = service.load()
        token, token_hash = generate_control_token()
        control = config.setdefault("control", {})
        control["enabled"] = True
        control["token_hash"] = token_hash
        service.save(config)
        session["new_control_token"] = token
        flash(
            "Ein neuer Control-Token wurde erzeugt.",
            "success",
        )
        return redirect(url_for("system_page") + "#control")

    @app.post("/system/control/toggle")
    def control_toggle():
        config = service.load()
        control = config.setdefault("control", {})
        control["enabled"] = request.form.get("enabled") == "1"
        service.save(config)
        portal_manager.start(config)
        flash("Control API wurde aktualisiert.", "success")
        return redirect(url_for("system_page") + "#control")

    @app.post("/system/settings/<section>")
    def system_settings_section(section):
        config = service.load()
        web_config = config.setdefault("web", {})
        auth = web_config.setdefault("authentication", {})
        try:
            if section == "language":
                language_value = request.form.get("language", "auto")
                if language_value not in {"auto", *SUPPORTED_LANGUAGES}:
                    raise ValueError("Unbekannte Sprache.")
                web_config["language"] = language_value
                message = "Sprache gespeichert."
                reload_page = True

            elif section == "access":
                enabled = request.form.get("auth_enabled") == "1"
                username = request.form.get("username", "").strip()
                password = request.form.get("password", "")
                confirmation = request.form.get("password_confirm", "")
                if enabled and not username:
                    raise ValueError("Benutzername fehlt.")
                if password or confirmation:
                    if password != confirmation:
                        raise ValueError("Passwörter stimmen nicht überein.")
                    if len(password) < 10:
                        raise ValueError("Passwort muss mindestens 10 Zeichen lang sein.")
                    auth["password_hash"] = generate_password_hash(password, method="pbkdf2:sha256:600000")
                if enabled and not auth.get("password_hash"):
                    raise ValueError("Passwort fehlt.")
                try:
                    lifetime = max(15, int(request.form.get("session_lifetime_minutes", 480)))
                except (TypeError, ValueError):
                    raise ValueError("Die Session-Dauer muss eine Zahl sein.")
                auth.update({
                    "enabled": enabled,
                    "username": username,
                    "session_lifetime_minutes": lifetime,
                    "session_version": int(auth.get("session_version", 0)) + 1,
                })
                message = "Zugriffsschutz gespeichert."
                reload_page = False

            elif section == "developer":
                web_config["developer_mode"] = request.form.get("developer_mode") == "1"
                message = "Entwicklermodus gespeichert."
                reload_page = True

            elif section == "datetime":
                datetime_config = web_config.setdefault("datetime", {})
                requested_timezone = request.form.get("timezone", "").strip()
                if requested_timezone and requested_timezone != _host_timezone():
                    _system_helper("set-timezone", requested_timezone)
                date_format = request.form.get("date_format", "dd.mm.yyyy").strip() or "dd.mm.yyyy"
                time_format = request.form.get("time_format", "HH:MM:ss").strip() or "HH:MM:ss"
                datetime_format = request.form.get("datetime_format", "").strip() or f"{date_format}, {time_format}"
                allowed_tokens = re.compile(r"^(?:yyyy|yy|dd|d|mm|m|HH|H|MM|M|ss|s|[^A-Za-z])+$")
                for label, value in (("Datumsformat", date_format), ("Zeitformat", time_format), ("Datums-/Zeitformat", datetime_format)):
                    if len(value) > 80 or not allowed_tokens.fullmatch(value):
                        raise ValueError(f"{label} enthält ungültige Tokens.")
                datetime_config.update({
                    "date_format": date_format,
                    "time_format": time_format,
                    "datetime_format": datetime_format,
                })
                message = "Datum, Uhrzeit und Zeitzone gespeichert."
                reload_page = True

            elif section == "mdns":
                mdns_enabled = request.form.get("mdns_enabled") == "1"
                mdns_hostname = request.form.get("mdns_hostname", "").strip().lower()
                if not mdns_hostname:
                    raise ValueError("mDNS-Name fehlt.")
                if len(mdns_hostname) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", mdns_hostname):
                    raise ValueError("Der mDNS-Name darf nur Kleinbuchstaben, Ziffern und Bindestriche enthalten und nicht mit einem Bindestrich beginnen oder enden.")
                previous_hostname = str(web_config.get("mdns_hostname", socket.gethostname())).strip().lower()
                if mdns_hostname != previous_hostname:
                    _system_helper("mdns-set-hostname", mdns_hostname)
                _system_helper("mdns-enable" if mdns_enabled else "mdns-disable")
                web_config["mdns_enabled"] = mdns_enabled
                web_config["mdns_hostname"] = mdns_hostname
                message = f"mDNS gespeichert: {mdns_hostname}.local"
                reload_page = True

            else:
                return jsonify({"ok": False, "error": "Unbekannter Einstellungsbereich."}), 404

            service.save(config)
            redirect_url = None
            if section == "access" and auth.get("enabled"):
                session.clear()
                redirect_url = url_for("login")
            return jsonify({
                "ok": True,
                "message": message,
                "reload": reload_page,
                "redirect": redirect_url,
            })
        except Exception as error:
            return jsonify({"ok": False, "error": str(error)}), 400

    @app.route("/system",methods=["GET","POST"])
    def system_page():
        config=service.load(); auth=config.setdefault("web",{}).setdefault("authentication",{})
        if request.method=="POST":
            try:
                language_value = request.form.get("language", "auto")
                if language_value not in {"auto", *SUPPORTED_LANGUAGES}:
                    language_value = "auto"
                web_config = config.setdefault("web", {})
                web_config["language"] = language_value
                web_config["developer_mode"] = request.form.get("developer_mode") == "1"
                datetime_config = web_config.setdefault("datetime", {})
                date_format = request.form.get("date_format", "dd.mm.yyyy").strip() or "dd.mm.yyyy"
                time_format = request.form.get("time_format", "HH:MM:ss").strip() or "HH:MM:ss"
                datetime_format = request.form.get("datetime_format", "").strip() or f"{date_format}, {time_format}"
                allowed_tokens = re.compile(r"^(?:yyyy|yy|dd|d|mm|m|HH|H|MM|M|ss|s|[^A-Za-z])+$")
                for label, value in (("Datumsformat", date_format), ("Zeitformat", time_format), ("Datums-/Zeitformat", datetime_format)):
                    if len(value) > 80 or not allowed_tokens.fullmatch(value):
                        raise ValueError(f"{label} enthält ungültige Tokens.")
                datetime_config.update({
                    "date_format": date_format,
                    "time_format": time_format,
                    "datetime_format": datetime_format,
                })
                on=request.form.get("auth_enabled")=="1"; user=request.form.get("username","").strip(); pw=request.form.get("password",""); confirm=request.form.get("password_confirm","")
                if on and not user: raise ValueError("Benutzername fehlt.")
                if pw or confirm:
                    if pw!=confirm: raise ValueError("Passwörter stimmen nicht überein.")
                    if len(pw)<10: raise ValueError("Passwort muss mindestens 10 Zeichen lang sein.")
                    auth["password_hash"]=generate_password_hash(pw, method="pbkdf2:sha256:600000")
                if on and not auth.get("password_hash"): raise ValueError("Passwort fehlt.")
                auth.update({"enabled":on,"username":user,"session_lifetime_minutes":max(15,int(request.form.get("session_lifetime_minutes",480))),"session_version":int(auth.get("session_version",0))+1})
                service.save(config)
                flash("Einstellungen gespeichert.", "success")
                if on:
                    session.clear()
                    return redirect(url_for("login"))
                return redirect(url_for("system_page") + "#general")
            except Exception as error:
                flash(str(error), "error")
        def status(name):
            return subprocess.run(["/usr/bin/systemctl","is-active",name],capture_output=True,text=True).stdout.strip()
        notifications = config.get("notifications", {})
        channels = notifications.get("channels", [])
        rules = notifications.get("rules", [])
        portals = config.get("control", {}).get("portals", [])
        runtime_status = load_runtime_status()
        state_checks = load_state().get("checks", {})
        active_checks = [
            check
            for check in config.get("checks", [])
            if check.get("enabled", True)
        ]
        problem_count = sum(
            1
            for check in active_checks
            if int(
                state_checks.get(
                    check.get("id"),
                    {},
                ).get("level", 0)
                or 0
            ) > 0
        )
        backup_items = list_backups()

        service_status = {
            "lanaxy": status("lanaxy.service"),
            "web": status("lanaxy-web.service"),
        }
        system_readiness = build_health(
            app_version=APP_VERSION,
            config=config,
            runtime=runtime_status,
            state=state_checks,
            agents=list_miniguards(),
            monitoring_running=service_status["lanaxy"] == "active",
            web_running=service_status["web"] == "active",
        )

        return render_template(
            "system.html",
            auth=auth,
            system_readiness=system_readiness,
            hostname=socket.gethostname(),
            python_version=platform.python_version(),
            guardian_count=len(config.get("checks", [])),
            active_guardian_count=len(active_checks),
            problem_guardian_count=problem_count,
            beacon_count=len([
                channel
                for channel in channels
                if channel.get("enabled", True)
            ]),
            rule_count=len([
                rule
                for rule in rules
                if rule.get("enabled", True)
            ]),
            portal_count=len([
                portal
                for portal in portals
                if portal.get("enabled", True)
            ]),
            mqtt_connected=bool(
                runtime_status.get("mqtt_connected")
            ),
            runtime_status=runtime_status,
            service_status={
                "lanaxy": status("lanaxy.service"),
                "web": status("lanaxy-web.service"),
            },
            database_path=config.get("lanaxy", {}).get(
                "database_file",
                str(LANAXY_DATA_DIR / "lanaxy.db"),
            ),
            system_mqtt=config.get("mqtt", {}),
            configured_language=config.get("web", {}).get(
                "language",
                "auto",
            ),
            configured_datetime=config.get("web", {}).get("datetime", {
                "date_format": "dd.mm.yyyy",
                "time_format": "HH:MM:ss",
                "datetime_format": "dd.mm.yyyy, HH:MM:ss",
            }),
            host_timezone=_host_timezone(),
            host_local_time=datetime.now().astimezone().isoformat(timespec="seconds"),
            available_timezones=_available_timezones(),
            mdns_enabled=_service_active("avahi-daemon.service"),
            mdns_hostname=str(config.get("web", {}).get("mdns_hostname", socket.gethostname())).removesuffix(".local"),
            retention_days=int(
                config.get("lanaxy", {}).get("retention_days", 90)
            ),
            backup_keep_count=int(
                config.get("lanaxy", {}).get("backup_keep_count", 20)
            ),
            config_history_keep=int(
                config.get("lanaxy", {}).get("config_history_keep", 100)
            ),
            database_stats=database_stats(
                config.get("lanaxy", {}).get(
                    "database_file",
                    str(LANAXY_DATA_DIR / "lanaxy.db"),
                )
            ),
            backups=backup_items,
            backup_count=len(backup_items),
            control_config=config.get("control", {}),
            control_runtime=control_engine.state.snapshot(),
            new_control_token=session.pop(
                "new_control_token",
                None,
            ),
        )




    @app.get("/system/topology")
    def topology_page():
        config = service.load()
        checks = config.get("checks", [])
        state_checks = load_state().get("checks", {})
        by_id = {str(c.get("id")): c for c in checks}

        nodes = {}
        for index, check in enumerate(checks):
            check_id = str(check.get("id", ""))
            deps = check.get("depends_on", [])
            if isinstance(deps, str):
                deps = [deps]
            deps = [str(dep) for dep in deps if dep]
            parent_id = str(check.get("topology_parent") or "")
            if not parent_id and deps:
                parent_id = deps[0]
            if parent_id not in by_id or parent_id == check_id:
                parent_id = ""
            nodes[check_id] = {
                "check": check,
                "state": state_checks.get(check_id, {}),
                "parent_id": parent_id,
                "extra_dependencies": [dep for dep in deps if dep != parent_id],
                "order": int(check.get("topology_order", index) or 0),
                "children": [],
                "scheduled_maintenance": scheduled_maintenance_for(
                    check, config.get("maintenance_windows", [])
                ),
            }

        roots = []
        for node in nodes.values():
            parent = nodes.get(node["parent_id"])
            if parent is None:
                roots.append(node)
            else:
                parent["children"].append(node)

        def sort_tree(items):
            items.sort(key=lambda item: (item["order"], str(item["check"].get("name", "")).lower()))
            for item in items:
                sort_tree(item["children"])

        sort_tree(roots)
        return render_template(
            "topology.html",
            roots=roots,
            diagnostics=topology_diagnostics(checks),
            windows=config.get("maintenance_windows", []),
        )

    @app.post("/system/topology/save")
    def topology_save():
        payload = request.get_json(silent=True) or {}
        items = payload.get("items", [])
        if not isinstance(items, list):
            return jsonify({"ok": False, "error": "Ungültige Baumdaten."}), 400

        config = service.load()
        checks = config.get("checks", [])
        by_id = {str(check.get("id")): check for check in checks}
        submitted_ids = {str(item.get("id", "")) for item in items if isinstance(item, dict)}
        if submitted_ids != set(by_id):
            return jsonify({"ok": False, "error": "Die Guardian-Liste ist unvollständig oder veraltet. Bitte die Seite neu laden."}), 409

        parent_map = {}
        for item in items:
            check_id = str(item.get("id", ""))
            parent_id = str(item.get("parent") or "")
            if parent_id and parent_id not in by_id:
                return jsonify({"ok": False, "error": f"Unbekannter übergeordneter Guardian: {parent_id}"}), 400
            if parent_id == check_id:
                return jsonify({"ok": False, "error": "Ein Guardian kann nicht von sich selbst abhängen."}), 400
            parent_map[check_id] = parent_id

        for check_id in parent_map:
            seen = set()
            current = check_id
            while parent_map.get(current):
                current = parent_map[current]
                if current in seen or current == check_id:
                    return jsonify({"ok": False, "error": "Die Anordnung würde eine zirkuläre Abhängigkeit erzeugen."}), 400
                seen.add(current)

        for item in items:
            check_id = str(item.get("id"))
            new_parent = parent_map[check_id]
            check = by_id[check_id]
            dependencies = check.get("depends_on", [])
            if isinstance(dependencies, str):
                dependencies = [dependencies]
            dependencies = [str(dep) for dep in dependencies if dep and dep != check_id]
            old_parent = str(check.get("topology_parent") or (dependencies[0] if dependencies else ""))
            extras = [dep for dep in dependencies if dep != old_parent and dep != new_parent]
            if new_parent:
                check["depends_on"] = [new_parent, *extras]
                check["topology_parent"] = new_parent
            else:
                if extras:
                    check["depends_on"] = extras
                else:
                    check.pop("depends_on", None)
                check.pop("topology_parent", None)
            try:
                check["topology_order"] = max(0, int(item.get("order", 0)))
            except (TypeError, ValueError):
                check["topology_order"] = 0

        try:
            service.save(config)
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        schedule_restart_all()
        return jsonify({"ok": True, "message": "Abhängigkeiten gespeichert. LANaxy wird neu gestartet."})

    @app.get("/system/maintenance")
    def maintenance_planner_page():
        config = service.load()
        now = datetime.now()
        windows = []
        for item in config.get("maintenance_windows", []):
            item = copy.deepcopy(item)
            try:
                start = datetime.fromisoformat(str(item.get("starts_at", "")))
                end = datetime.fromisoformat(str(item.get("ends_at", "")))
                item["state"] = "active" if start <= now < end else ("future" if now < start else "past")
            except ValueError:
                item["state"] = "invalid"
            windows.append(item)
        groups = sorted({c.get("group") for c in config.get("checks", []) if c.get("group")})
        return render_template(
            "maintenance_planner.html",
            windows=windows,
            checks=config.get("checks", []),
            groups=groups,
            default_start=now.strftime("%Y-%m-%dT%H:%M"),
            default_end=(now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
        )

    @app.post("/system/maintenance/add")
    def maintenance_planner_add():
        config = service.load()
        try:
            name = request.form.get("name", "").strip()
            starts_at = request.form.get("starts_at", "").strip()
            ends_at = request.form.get("ends_at", "").strip()
            if not name:
                raise ValueError("Bitte einen Namen für das Wartungsfenster eingeben.")
            start = datetime.fromisoformat(starts_at)
            end = datetime.fromisoformat(ends_at)
            if end <= start:
                raise ValueError("Das Ende muss nach dem Beginn liegen.")
            guardian_ids = [v for v in request.form.getlist("guardian_ids") if v]
            groups = [v for v in request.form.getlist("groups") if v]
            if not guardian_ids and not groups:
                raise ValueError("Bitte mindestens einen Guardian oder eine Gruppe auswählen.")
            import secrets
            config.setdefault("maintenance_windows", []).append({
                "id": secrets.token_hex(6),
                "name": name,
                "reason": request.form.get("reason", "").strip(),
                "starts_at": starts_at,
                "ends_at": ends_at,
                "guardian_ids": guardian_ids,
                "groups": groups,
                "enabled": True,
            })
            service.save(config)
            database.add_event(
                "MAINTENANCE_PLANNED",
                f"Wartungsfenster {name} geplant",
                status="maintenance",
                details={"starts_at": starts_at, "ends_at": ends_at, "guardian_ids": guardian_ids, "groups": groups},
            )
            restart_lanaxy()
            flash("Wartungsfenster wurde angelegt.", "success")
        except Exception as error:
            flash(str(error), "error")
        return redirect(url_for("maintenance_planner_page"))

    @app.post("/system/maintenance/<window_id>/toggle")
    def maintenance_planner_toggle(window_id):
        config = service.load()
        window = next((w for w in config.get("maintenance_windows", []) if w.get("id") == window_id), None)
        if window is None:
            abort(404)
        window["enabled"] = not window.get("enabled", True)
        service.save(config)
        restart_lanaxy()
        flash("Wartungsfenster wurde aktualisiert.", "success")
        return redirect(url_for("maintenance_planner_page"))

    @app.post("/system/maintenance/<window_id>/delete")
    def maintenance_planner_delete(window_id):
        config = service.load()
        before = len(config.get("maintenance_windows", []))
        config["maintenance_windows"] = [w for w in config.get("maintenance_windows", []) if w.get("id") != window_id]
        if len(config["maintenance_windows"]) == before:
            abort(404)
        service.save(config)
        restart_lanaxy()
        flash("Wartungsfenster wurde gelöscht.", "success")
        return redirect(url_for("maintenance_planner_page"))

    @app.get("/system/config-history")
    def config_history_page():
        entries = []
        config = service.load()
        history_keep = max(
            5,
            int(config.get("lanaxy", {}).get("config_history_keep", 100)),
        )
        prune_configuration_history(Path(service.backup_dir), history_keep)
        for path in sorted(
            Path(service.backup_dir).glob("config-*.yaml"),
            reverse=True,
        )[:history_keep]:
            meta = {}
            try:
                meta = json.loads(
                    path.with_suffix(".json").read_text(encoding="utf-8")
                )
            except Exception:
                pass

            # Older metadata files contained only counts. Read the archived
            # YAML as a fallback so existing revisions gain the detailed list
            # without requiring a migration.
            try:
                archived_config = __import__("yaml").safe_load(
                    path.read_text(encoding="utf-8")
                ) or {}
                inventory = configuration_inventory(archived_config)
                for key, value in inventory.items():
                    meta.setdefault(key, value)
            except Exception:
                pass

            entries.append({
                "name": path.name,
                "size": path.stat().st_size,
                "modified": datetime.fromtimestamp(
                    path.stat().st_mtime
                ).isoformat(timespec="seconds"),
                "meta": meta,
            })
        return render_template("config_history.html", entries=entries)

    @app.get("/system/config-history/<path:name>/diff")
    def config_history_diff(name):
        path=Path(service.backup_dir)/Path(name).name
        if not path.exists() or not path.name.startswith("config-"): abort(404)
        current=Path(service.config_path).read_text(encoding="utf-8") if Path(service.config_path).exists() else ""
        historic=path.read_text(encoding="utf-8")
        diff="".join(difflib.unified_diff(historic.splitlines(True),current.splitlines(True),fromfile=path.name,tofile="aktuelle Konfiguration",n=3))
        return render_template("config_history_diff.html",name=path.name,diff=diff or "Keine Unterschiede.")

    @app.get("/system/config-history/<path:name>/download")
    def config_history_download(name):
        path=(Path(service.backup_dir)/Path(name).name)
        if not path.exists() or not path.name.startswith("config-"): abort(404)
        return send_file(path,as_attachment=True,download_name=path.name)

    @app.post("/system/config-history/<path:name>/restore")
    def config_history_restore(name):
        path=(Path(service.backup_dir)/Path(name).name)
        if not path.exists() or not path.name.startswith("config-"): abort(404)
        try:
            restored=__import__('yaml').safe_load(path.read_text()) or {}
            service.save(restored); restart_lanaxy(); flash("Konfigurationsstand wurde wiederhergestellt.","success")
        except Exception as error: flash(f"Wiederherstellung fehlgeschlagen: {error}","error")
        return redirect(url_for("config_history_page"))

    @app.route("/system/cluster", methods=["GET","POST"])
    def cluster_page():
        join_token=None
        if request.method=="POST":
            action=request.form.get("action")
            if action=="save":
                configure_cluster(request.form.get("cluster_id",""),request.form.get("node_id",""),request.form.get("node_name",""),request.form.get("enabled")=="1")
                flash("Cluster-Basis wurde gespeichert. Automatisches Failover bleibt bis LANaxy 2.x deaktiviert.","success")
            elif action=="token": join_token=create_join_token()
        return render_template("cluster.html", cluster=cluster_status(), join_token=join_token)

    @app.get("/api/cluster/v1/status")
    def cluster_status_api(): return jsonify(cluster_public_snapshot())

    def _remove_legacy_miniguard_guardians():
        """Remove system-generated MiniGuard cards from the normal Guardian model.

        MiniGuard health and inventory are represented directly on the MiniGuards
        page. Older releases created normal Guardian checks for the same data,
        which caused duplicate cards and recreated deleted entries.
        """
        config = service.load()
        checks = config.get("checks", [])
        legacy_types = {"miniguard_health", "miniguard_inventory"}
        removed_ids = {
            str(check.get("id"))
            for check in checks
            if check.get("guardian") in legacy_types
        }
        if not removed_ids:
            return 0

        config["checks"] = [
            check for check in checks
            if check.get("guardian") not in legacy_types
        ]
        for check in config["checks"]:
            if check.get("depends_on"):
                check["depends_on"] = [
                    dependency for dependency in check["depends_on"]
                    if str(dependency) not in removed_ids
                ]

        notifications = config.get("notifications", {})
        for rule in notifications.get("rules", []):
            if rule.get("guardians"):
                rule["guardians"] = [
                    guardian_id for guardian_id in rule["guardians"]
                    if str(guardian_id) not in removed_ids
                ]

        service.save(config)
        restart_lanaxy()
        return len(removed_ids)

    def _miniguard_update_parameters(agent_id):
        agent_path = Path(__file__).resolve().parents[1] / "miniguard_agent.py"
        payload = agent_path.read_bytes()
        return {
            "url": request.url_root.rstrip("/") + "/miniguard/agent.py",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "target_version": "1.7.0",
        }

    def _run_miniguard_action(agent_id, action_type, parameters=None, timeout=90):
        actor = str(session.get("username") or session.get("user") or "LANaxy")
        task_id, _secret = enqueue_miniguard_action(
            agent_id,
            action_type,
            parameters or {},
            timeout=timeout,
            actor=actor,
        )
        return task_id, wait_for_miniguard_task(task_id, timeout=timeout)

    @app.get("/system/miniguards")
    def miniguards_page():
        command = session.pop("miniguard_install_command", None)
        ttl = session.pop("miniguard_registration_ttl", 30)
        agents = list_miniguards()
        _remove_legacy_miniguard_guardians()
        agents = list_miniguards()
        base = request.url_root.rstrip("/")
        policy = miniguard_policy_for(APP_VERSION)
        latest_agent_version = ".".join(str(part) for part in policy["recommended_agent"])
        for agent in agents:
            agent["update_command"] = (
                f"curl -fsSL {base}/miniguard/u/{agent['id']} | sh"
            )
            compatibility = evaluate_miniguard_compatibility(agent, APP_VERSION)
            agent["compatibility"] = compatibility
            agent["latest_agent_version"] = latest_agent_version
            agent["update_available"] = compatibility.get("update_required", False)
            installed_version = tuple(int(part) for part in re.findall(r"\d+", str(agent.get("agent_version") or "0.0.0"))[:3])
            installed_version = installed_version + (0,) * (3 - len(installed_version))
            agent["remote_management_ready"] = installed_version >= (1, 7, 0)
            tools = agent.get("tools") or {}
            agent["missing_tools"] = sorted(name for name, available in tools.items() if not available)
        selftest = session.pop("miniguard_selftest", None)
        inventory = session.pop("miniguard_inventory", None)
        action_result = session.pop("miniguard_action_result", None)
        for agent in agents:
            agent["recent_tasks"] = miniguard_recent_tasks(agent["id"], 10)
            agent["action_permissions"] = {
                **MINIGUARD_DEFAULT_ACTION_PERMISSIONS,
                **(agent.get("action_permissions") or {}),
            }
            agent["pending_inventory_changes"] = [change for change in agent.get("inventory_changes", []) if not change.get("acknowledged_at")]
        return render_template(
            "miniguards.html",
            agents=agents,
            install_command=command,
            registration_ttl=ttl,
            selftest=selftest,
            inventory=inventory,
            action_result=action_result,
            action_names=sorted(MINIGUARD_ACTIONS),
        )

    @app.post("/system/miniguards/add")
    def miniguard_add():
        try:
            ttl = int(request.form.get("ttl_minutes", 30))
            agent, code = create_miniguard(request.form.get("name", ""), request.form.get("description", ""), ttl)
            base = request.url_root.rstrip("/")
            command = (
                f"curl -fsSL {base}/miniguard/i/{agent['id']}/{code} | sh"
            )
            session["miniguard_install_command"] = command
            session["miniguard_registration_ttl"] = ttl
            flash("MiniGuard wurde angelegt. Installationsbefehl jetzt auf dem Zielsystem ausführen.", "success")
        except Exception as error:
            flash(str(error), "error")
        return redirect(url_for("miniguards_page"))

    @app.post("/system/miniguards/<agent_id>/selftest")
    def miniguard_selftest(agent_id):
        try:
            outcome = miniguard_execute_remote_check(agent_id, "system_info", {"name": "MiniGuard Selbsttest"}, 20)
            session["miniguard_selftest"] = {"agent_id": agent_id, **outcome}
            flash("MiniGuard-Selbsttest abgeschlossen.", "success" if outcome.get("status") == "ok" else "warning")
        except Exception as error:
            session["miniguard_selftest"] = {"agent_id": agent_id, "status": "unknown", "message": str(error), "details": {}}
            flash(f"MiniGuard-Selbsttest fehlgeschlagen: {error}", "error")
        return redirect(url_for("miniguards_page"))

    @app.post("/system/miniguards/<agent_id>/inventory")
    def miniguard_inventory(agent_id):
        try:
            outcome = miniguard_execute_remote_check(agent_id, "hardware_inventory", {"name": "Hardwareinventar"}, 60)
            session["miniguard_inventory"] = {"agent_id": agent_id, **outcome}
            flash("Hardwareinventar wurde aktualisiert.", "success" if outcome.get("status") == "ok" else "warning")
        except Exception as error:
            session["miniguard_inventory"] = {"agent_id": agent_id, "status": "unknown", "message": str(error), "details": {}}
            flash(f"Hardwareinventar fehlgeschlagen: {error}", "error")
        return redirect(url_for("miniguards_page"))

    @app.get("/system/miniguards/<agent_id>/diagnostics.json")
    def miniguard_diagnostics_download(agent_id):
        agent = next((item for item in list_miniguards() if item.get("id") == agent_id), None)
        if not agent:
            abort(404)
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "lanaxy_version": APP_VERSION,
            "agent": agent,
        }
        return Response(
            json.dumps(payload, ensure_ascii=False, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename=miniguard-{agent_id}-diagnostics.json"},
        )

    @app.post("/system/miniguards/<agent_id>/action")
    def miniguard_action(agent_id):
        action = request.form.get("action", "").strip()
        try:
            agent = get_miniguard(agent_id)
            if not agent:
                raise ValueError("MiniGuard wurde nicht gefunden.")
            installed = tuple(int(part) for part in re.findall(r"\d+", str(agent.get("agent_version") or "0.0.0"))[:3])
            installed = installed + (0,) * (3 - len(installed))
            if installed < (1, 7, 0):
                raise ValueError("Einmaliges Bootstrap-Update erforderlich: Bitte den angezeigten cURL-Updatebefehl ausführen. Danach sind direkte Updates aus LANaxy möglich.")
            parameters = {}
            timeout = 90
            if action == "update_agent":
                parameters = _miniguard_update_parameters(agent_id)
                timeout = 120
            elif action == "fetch_logs":
                parameters = {"lines": int(request.form.get("lines", 200) or 200)}
            elif action == "check_tool":
                parameters = {"tool": request.form.get("tool", "").strip()}
            elif action == "restart_host" and request.form.get("confirm_host_restart") != "RESTART":
                raise ValueError("Für den Host-Neustart muss RESTART als Bestätigung eingegeben werden.")
            task_id, outcome = _run_miniguard_action(agent_id, action, parameters, timeout)
            session["miniguard_action_result"] = {
                "agent_id": agent_id,
                "task_id": task_id,
                "action": action,
                **outcome,
            }
            result_payload = {
                "ok": outcome.get("status") == "ok",
                "agent_id": agent_id,
                "task_id": task_id,
                "action": action,
                "status": outcome.get("status", "unknown"),
                "message": outcome.get("message", "MiniGuard-Aktion abgeschlossen."),
                "details": outcome.get("details") or {},
            }
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(result_payload), (200 if result_payload["ok"] else 422)
            flash(
                result_payload["message"],
                "success" if result_payload["ok"] else "error",
            )
        except Exception as error:
            session["miniguard_action_result"] = {
                "agent_id": agent_id,
                "action": action,
                "status": "critical",
                "message": str(error),
                "details": {},
            }
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({
                    "ok": False,
                    "agent_id": agent_id,
                    "action": action,
                    "status": "critical",
                    "message": str(error),
                    "details": {},
                }), 422
            flash(f"MiniGuard-Aktion fehlgeschlagen: {error}", "error")
        return redirect(url_for("miniguards_page"))

    @app.post("/system/miniguards/<agent_id>/permissions")
    def miniguard_permissions(agent_id):
        try:
            agent = get_miniguard(agent_id)
            if not agent:
                raise ValueError("MiniGuard wurde nicht gefunden.")
            installed = tuple(int(part) for part in re.findall(r"\d+", str(agent.get("agent_version") or "0.0.0"))[:3])
            installed = installed + (0,) * (3 - len(installed))
            if installed < (1, 7, 0):
                raise ValueError("Zuerst ist das einmalige Bootstrap-Update auf MiniGuard 1.7.0 erforderlich.")
            permissions = {
                name: request.form.get(f"permission_{name}") == "1"
                for name in MINIGUARD_ACTIONS
            }
            normalized = set_miniguard_action_permissions(agent_id, permissions)
            task_id, outcome = _run_miniguard_action(
                agent_id,
                "sync_permissions",
                {"permissions": normalized},
                60,
            )
            session["miniguard_action_result"] = {
                "agent_id": agent_id,
                "task_id": task_id,
                "action": "sync_permissions",
                **outcome,
            }
            flash("MiniGuard-Berechtigungen wurden gespeichert und übertragen.", "success")
        except Exception as error:
            flash(f"Berechtigungen konnten nicht gespeichert werden: {error}", "error")
        return redirect(url_for("miniguards_page"))

    @app.post("/system/miniguards/<agent_id>/toggle")
    def miniguard_toggle(agent_id):
        enabled = request.form.get("enabled") == "1"
        if set_miniguard_enabled(agent_id, enabled):
            flash(f"MiniGuard wurde {'aktiviert' if enabled else 'deaktiviert'}.", "success")
        else:
            flash("MiniGuard wurde nicht gefunden.", "error")
        return redirect(url_for("miniguards_page"))

    @app.post("/system/miniguards/bulk")
    def miniguard_bulk():
        ids = request.form.getlist("agent_ids")
        action = request.form.get("action", "").strip()
        if not ids:
            flash("Keine MiniGuards ausgewählt.", "error")
            return redirect(url_for("miniguards_page"))
        success = 0
        failed = []
        for agent_id in ids:
            try:
                agent = get_miniguard(agent_id)
                if not agent:
                    raise ValueError("nicht gefunden")
                installed = tuple(int(part) for part in re.findall(r"\d+", str(agent.get("agent_version") or "0.0.0"))[:3])
                installed = installed + (0,) * (3 - len(installed))
                if action not in {"enable", "disable"} and installed < (1, 7, 0):
                    raise ValueError("Bootstrap-Update auf 1.7.0 erforderlich")
                if action == "enable":
                    if not set_miniguard_enabled(agent_id, True):
                        raise ValueError("nicht gefunden")
                elif action == "disable":
                    if not set_miniguard_enabled(agent_id, False):
                        raise ValueError("nicht gefunden")
                else:
                    parameters = _miniguard_update_parameters(agent_id) if action == "update_agent" else {}
                    _task_id, outcome = _run_miniguard_action(
                        agent_id,
                        action,
                        parameters,
                        120 if action == "update_agent" else 90,
                    )
                    if outcome.get("status") != "ok":
                        raise ValueError(outcome.get("message", "Aktion fehlgeschlagen"))
                success += 1
            except Exception as error:
                failed.append(f"{agent_id}: {error}")
        flash(
            f"Massenaktion abgeschlossen: {success} erfolgreich, {len(failed)} fehlgeschlagen."
            + (f" {'; '.join(failed[:3])}" if failed else ""),
            "success" if not failed else "warning",
        )
        return redirect(url_for("miniguards_page"))

    @app.post("/system/miniguards/<agent_id>/inventory-alias")
    def miniguard_inventory_alias(agent_id):
        inventory_id=request.form.get("inventory_id","").strip(); alias=request.form.get("alias","").strip()
        if not inventory_id or not set_miniguard_inventory_alias(agent_id,inventory_id,alias): flash("Inventaralias konnte nicht gespeichert werden.","error")
        else: flash("Gerätename wurde gespeichert.","success")
        return redirect(url_for("miniguards_page"))

    @app.post("/system/miniguards/<agent_id>/inventory-acknowledge")
    def miniguard_inventory_acknowledge(agent_id):
        count=acknowledge_miniguard_inventory_changes(agent_id,request.form.getlist("change_ids"))
        flash(f"{count} Inventaränderungen wurden bestätigt.","success")
        return redirect(url_for("miniguards_page"))

    @app.post("/system/miniguards/<agent_id>/delete")
    def miniguard_delete(agent_id):
        if delete_miniguard(agent_id):
            flash("MiniGuard wurde aus LANaxy entfernt. Der Agent muss auf dem Zielsystem als root mit 'miniguard uninstall' oder über 'sudo miniguard uninstall' deinstalliert werden.", "warning")
        else:
            flash("MiniGuard wurde nicht gefunden.", "error")
        return redirect(url_for("miniguards_page"))

    @app.post("/api/miniguards/<agent_id>/register")
    def miniguard_register_api(agent_id):
        payload = request.get_json(silent=True) or {}
        try:
            token = register_miniguard(agent_id, str(payload.get("code", "")), payload)
            registered_agent = get_miniguard(agent_id)
            if registered_agent:
                _remove_legacy_miniguard_guardians()
            return {"ok": True, "token": token, "protocol_version": 1}
        except ValueError as error:
            return {"ok": False, "error": str(error)}, 400

    @app.post("/api/miniguards/<agent_id>/heartbeat")
    def miniguard_heartbeat_api(agent_id):
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        try:
            return miniguard_heartbeat(agent_id, token, request.get_json(silent=True) or {})
        except PermissionError as error:
            return {"ok": False, "error": str(error)}, 403

    @app.post("/api/miniguards/<agent_id>/checks/next")
    def miniguard_next_check_api(agent_id):
        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        try:
            return jsonify(miniguard_poll_check(agent_id, token))
        except (ValueError, PermissionError) as error:
            return jsonify({"ok": False, "error": str(error)}), 403
        except Exception as error:
            app.logger.exception("MiniGuard polling failed for %s", agent_id)
            return jsonify({"ok": False, "error": f"MiniGuard-Queue konnte nicht gelesen werden: {error}"}), 500

    @app.post("/api/miniguards/<agent_id>/checks/<task_id>/result")
    def miniguard_check_result_api(agent_id, task_id):
        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        try:
            return jsonify(miniguard_complete_check(agent_id, token, task_id, request.get_json(silent=True) or {}))
        except PermissionError as error:
            return jsonify({"ok": False, "error": str(error)}), 403
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        except Exception as error:
            app.logger.exception("MiniGuard result upload failed for %s/%s", agent_id, task_id)
            return jsonify({"ok": False, "error": f"MiniGuard-Ergebnis konnte nicht gespeichert werden: {error}"}), 500

    def _miniguard_bootstrap_script(*, base: str, agent_id: str, code: str = "", update: bool = False, self_url: str) -> str:
        """Build a short self-elevating MiniGuard bootstrap script."""
        q = shlex.quote
        args = f"--lanaxy {q(base)} --agent-id {q(agent_id)}"
        if update:
            args += " --update"
        else:
            args += f" --code {q(code)}"
        mode = "Aktualisierung" if update else "Installation"
        lines = [
            "#!/bin/sh",
            "set -eu",
            'echo "MiniGuard Bootstrap"',
            f'echo "LANaxy: {base}"',
            f'echo "Agent-ID: {agent_id}"',
            f'echo "Modus: {mode}"',
            "",
            'if [ "$(id -u)" -ne 0 ]; then',
            '  if ! command -v sudo >/dev/null 2>&1; then',
            '    echo "Fehler: Root-Rechte erforderlich. Bitte als root ausführen oder sudo installieren." >&2',
            '    exit 1',
            '  fi',
            '  tmp=$(mktemp)',
            '  trap \'rm -f "$tmp"\' EXIT HUP INT TERM',
            '  echo "[INFO] Root-Rechte werden über sudo angefordert."',
            f'  curl -fsSL {q(self_url)} -o "$tmp"',
            '  sudo sh "$tmp"',
            '  exit $?',
            'fi',
            "",
            'command -v curl >/dev/null 2>&1 || { echo "Fehler: curl fehlt." >&2; exit 1; }',
            'command -v python3 >/dev/null 2>&1 || { echo "Fehler: python3 fehlt." >&2; exit 1; }',
            'tmp=$(mktemp)',
            'trap \'rm -f "$tmp"\' EXIT HUP INT TERM',
            'echo "[OK] Root-Rechte verfügbar"',
            'echo "[INFO] MiniGuard-Installer wird geladen ..."',
            f'curl -fsSL {q(base + "/miniguard/install.sh")} -o "$tmp"',
            'echo "[INFO] MiniGuard wird installiert beziehungsweise aktualisiert ..."',
            f'sh "$tmp" {args}',
            'echo "[OK] MiniGuard Bootstrap abgeschlossen."',
            "",
        ]
        return "\n".join(lines)

    @app.get("/miniguard/i/<agent_id>/<code>")
    def miniguard_install_bootstrap(agent_id, code):
        base = request.url_root.rstrip("/")
        script = _miniguard_bootstrap_script(
            base=base,
            agent_id=agent_id,
            code=code,
            update=False,
            self_url=request.url,
        )
        return Response(
            script,
            mimetype="text/x-shellscript",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/miniguard/u/<agent_id>")
    def miniguard_update_bootstrap(agent_id):
        base = request.url_root.rstrip("/")
        script = _miniguard_bootstrap_script(
            base=base,
            agent_id=agent_id,
            update=True,
            self_url=request.url,
        )
        return Response(
            script,
            mimetype="text/x-shellscript",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/miniguard/agent.py")
    def miniguard_agent_download():
        return send_file(Path(__file__).resolve().parents[1] / "miniguard_agent.py", mimetype="text/x-python")

    @app.get("/miniguard/install.sh")
    def miniguard_install_script():
        return send_file(
            Path(__file__).resolve().parents[1] / "miniguard_install.sh",
            mimetype="text/x-shellscript",
        )

    @app.post("/system/maintenance/settings")
    def maintenance_settings():
        config = service.load()
        try:
            retention_days = max(
                1,
                min(
                    3650,
                    int(request.form.get("retention_days", 90)),
                ),
            )
            backup_keep_count = max(
                1, min(500, int(request.form.get("backup_keep_count", 20)))
            )
            config_history_keep = max(
                5, min(2000, int(request.form.get("config_history_keep", 100)))
            )
            lanaxy_settings = config.setdefault("lanaxy", {})
            lanaxy_settings["retention_days"] = retention_days
            lanaxy_settings["backup_keep_count"] = backup_keep_count
            lanaxy_settings["config_history_keep"] = config_history_keep
            service.save(config)
            prune_backups(backup_keep_count)
            prune_configuration_history(
                Path(service.backup_dir), config_history_keep
            )
            restart_lanaxy()
            flash(
                "Aufbewahrung gespeichert: "
                f"{retention_days} Tage Datenbank, "
                f"{backup_keep_count} Backups und "
                f"{config_history_keep} Konfigurationsstände.",
                "success",
            )
        except Exception as error:
            flash(str(error), "error")
        return redirect(url_for("system_page") + "#maintenance")

    @app.post("/system/maintenance/cleanup")
    def maintenance_cleanup():
        try:
            days = max(
                1,
                min(
                    3650,
                    int(request.form.get("retention_days", 90)),
                ),
            )
            result = database.cleanup_with_counts(days)
            if request.form.get("vacuum") == "1":
                database.vacuum()
            flash(
                "Datenbereinigung abgeschlossen: "
                f"{result['events']} Protokolleinträge und "
                f"{result['metrics']} Messwerte entfernt.",
                "success",
            )
        except Exception as error:
            flash(f"Datenbereinigung fehlgeschlagen: {error}", "error")
        return redirect(url_for("system_page") + "#maintenance")

    @app.post("/system/maintenance/clear-events")
    def maintenance_clear_events():
        try:
            deleted = database.clear_events()
            database.vacuum()
            flash(
                f"{deleted} Protokolleinträge wurden gelöscht.",
                "success",
            )
        except Exception as error:
            flash(str(error), "error")
        return redirect(url_for("system_page") + "#maintenance")

    @app.post("/system/maintenance/clear-history")
    def maintenance_clear_history():
        try:
            deleted = database.clear_metrics()
            database.vacuum()
            flash(
                f"{deleted} historische Messwerte wurden gelöscht.",
                "success",
            )
        except Exception as error:
            flash(str(error), "error")
        return redirect(url_for("system_page") + "#maintenance")

    @app.post("/system/backups/create")
    def backup_create():
        config = service.load()
        database_path = config.get("lanaxy", {}).get(
            "database_file",
            str(LANAXY_DATA_DIR / "lanaxy.db"),
        )
        try:
            backup = create_backup(
                database_path,
                include_database=(
                    request.form.get("include_database") == "1"
                ),
                reason="manual",
                keep_count=int(
                    config.get("lanaxy", {}).get("backup_keep_count", 20)
                ),
            )
            flash(
                f"Backup {backup.name} wurde erstellt.",
                "success",
            )
        except Exception as error:
            flash(f"Backup fehlgeschlagen: {error}", "error")
        return redirect(url_for("system_page") + "#backups")

    @app.get("/system/backups/<path:filename>/download")
    def backup_download(filename):
        safe_name = Path(filename).name
        path = BACKUP_DIR / safe_name
        if (
            safe_name != filename
            or not path.is_file()
            or not safe_name.startswith("lanaxy-backup-")
            or path.suffix != ".zip"
        ):
            abort(404)
        return send_file(
            path,
            as_attachment=True,
            download_name=safe_name,
            mimetype="application/zip",
        )

    @app.post("/system/backups/<path:filename>/delete")
    def backup_delete(filename):
        safe_name = Path(filename).name
        path = BACKUP_DIR / safe_name
        if (
            safe_name != filename
            or not path.is_file()
            or not safe_name.startswith("lanaxy-backup-")
        ):
            abort(404)
        path.unlink()
        flash("Backup wurde gelöscht.", "success")
        return redirect(url_for("system_page") + "#backups")

    @app.post("/system/backups/<path:filename>/restore")
    def backup_restore_saved(filename):
        safe_name = Path(filename).name
        path = BACKUP_DIR / safe_name
        if (
            safe_name != filename
            or not path.is_file()
            or not safe_name.startswith("lanaxy-backup-")
        ):
            abort(404)

        config = service.load()
        database_path = config.get("lanaxy", {}).get(
            "database_file",
            str(LANAXY_DATA_DIR / "lanaxy.db"),
        )

        try:
            result = restore_backup(
                path,
                database_path,
                restore_database=(
                    request.form.get("restore_database") == "1"
                ),
                keep_count=int(
                    config.get("lanaxy", {}).get("backup_keep_count", 20)
                ),
            )
            schedule_restart_all()
            flash(
                "Backup wurde wiederhergestellt. "
                f"Sicherheitsbackup: "
                f"{result['safety_backup'].name}",
                "success",
            )
        except Exception as error:
            flash(
                f"Wiederherstellung fehlgeschlagen: {error}",
                "error",
            )
        return redirect(url_for("system_page") + "#backups")

    @app.post("/system/backups/upload")
    def backup_upload_restore():
        upload = request.files.get("backup_file")
        if upload is None or not upload.filename:
            flash("Bitte eine Backup-ZIP auswählen.", "error")
            return redirect(url_for("system_page") + "#backups")

        if not upload.filename.lower().endswith(".zip"):
            flash("Es werden nur ZIP-Backups akzeptiert.", "error")
            return redirect(url_for("system_page") + "#backups")

        config = service.load()
        database_path = config.get("lanaxy", {}).get(
            "database_file",
            str(LANAXY_DATA_DIR / "lanaxy.db"),
        )

        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".zip",
                delete=False,
            ) as temporary:
                upload.save(temporary.name)
                temporary_path = Path(temporary.name)

            validate_backup(temporary_path)
            result = restore_backup(
                temporary_path,
                database_path,
                restore_database=(
                    request.form.get("restore_database") == "1"
                ),
                keep_count=int(
                    config.get("lanaxy", {}).get("backup_keep_count", 20)
                ),
            )
            schedule_restart_all()
            flash(
                "Hochgeladenes Backup wurde wiederhergestellt. "
                f"Sicherheitsbackup: "
                f"{result['safety_backup'].name}",
                "success",
            )
        except Exception as error:
            flash(
                f"Wiederherstellung fehlgeschlagen: {error}",
                "error",
            )
        finally:
            try:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
            except Exception:
                pass

        return redirect(url_for("system_page") + "#backups")

    @app.get("/system/diagnostics/download")
    def diagnostic_download():
        config = service.load()
        database_path = config.get("lanaxy", {}).get(
            "database_file",
            str(LANAXY_DATA_DIR / "lanaxy.db"),
        )
        bundle = create_diagnostic_bundle(
            config,
            database_path,
            "1.5.0",
        )
        filename = (
            "lanaxy-diagnostics-"
            + __import__("datetime").datetime.now().strftime(
                "%Y%m%d-%H%M%S"
            )
            + ".zip"
        )
        return send_file(
            bundle,
            as_attachment=True,
            download_name=filename,
            mimetype="application/zip",
        )

    @app.get("/about")
    def about_page():
        return render_template("about.html")

    return app


app = create_app()

