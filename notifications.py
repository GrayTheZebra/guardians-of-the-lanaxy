import json
import smtplib
import ssl
import threading
import time as time_module
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time, timedelta
from email.message import EmailMessage
from pathlib import Path

import paho.mqtt.client as mqtt


STATUS_FILE = Path("/var/lib/lanaxy/notification-status.json")


def event_kind(event) -> str:
    new_status = str(getattr(event, "new_status", "") or "")
    old_status = str(getattr(event, "old_status", "") or "")

    if new_status == "critical":
        return "critical"
    if new_status in {"warning", "blocked"}:
        return "warning"
    if new_status == "ok" and old_status not in {"", "ok"}:
        return "recovery"
    return new_status or "event"


def load_status() -> dict:
    if not STATUS_FILE.exists():
        return {}
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_status(status: dict) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(STATUS_FILE)


def record_channel_result(channel_id: str, ok: bool, error: str = "") -> None:
    status = load_status()
    entry = status.setdefault(channel_id, {})
    now = datetime.now().isoformat(timespec="seconds")

    if ok:
        entry["last_success"] = now
        entry["last_error"] = ""
    else:
        entry["last_error"] = error
        entry["last_error_at"] = now

    save_status(status)


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days} T")
    if hours:
        parts.append(f"{hours} Std.")
    if minutes:
        parts.append(f"{minutes} Min.")
    if seconds or not parts:
        parts.append(f"{seconds} Sek.")
    return " ".join(parts)


def notification_payload(event) -> dict:
    data = event.to_dict()
    data["kind"] = event_kind(event)

    event_details = data.get("details") or {}
    guardian_name = str(event_details.get("name") or data.get("source") or "unbekannt")
    guardian_id = str(data.get("source") or data.get("device_id") or "unbekannt")
    result_message = str(event_details.get("message") or data.get("message") or "").strip()
    name_prefix = guardian_name + ":"
    if result_message.startswith(name_prefix):
        result_message = result_message[len(name_prefix):].lstrip()

    old_status = str(data.get("old_status") or "").strip()
    new_status = str(data.get("new_status") or "").strip()
    if old_status and new_status:
        data["message"] = f"{old_status} -> {new_status}: {result_message}".strip()
    else:
        data["message"] = result_message

    data["guardian_name"] = guardian_name
    data["guardian_id"] = guardian_id

    incident = event_details.get("incident") or {}
    if incident:
        data["incident_id"] = incident.get("id")
        data["incident_started_at"] = incident.get("started_at", "")
        data["incident_acknowledged"] = incident.get(
            "acknowledged",
            False,
        )
        if incident.get("duration_seconds") is not None:
            data["duration_seconds"] = incident["duration_seconds"]
            data["duration_human"] = format_duration(
                incident["duration_seconds"]
            )

    data["title"] = {
        "critical": "Kritischer LANaxy-Fehler",
        "warning": "LANaxy-Warnung",
        "recovery": "LANaxy-Wiederherstellung",
    }.get(data["kind"], "LANaxy-Ereignis")

    return data


def plain_message(payload: dict) -> str:
    status = payload.get("new_status") or payload.get("kind", "event")
    lines = [
        str(payload.get("title", "LANaxy")),
        "",
        f"Guardian: {payload.get('guardian_name') or payload.get('source', 'unbekannt')}",
        f"ID: {payload.get('guardian_id') or payload.get('source', 'unbekannt')}",
        f"Status: {status}",
        f"Meldung: {payload.get('message', '')}",
    ]
    if payload.get("duration_human"):
        lines.append(f"Ausfalldauer: {payload['duration_human']}")
    lines.append(f"Zeit: {payload.get('timestamp', '')}")
    return "\n".join(lines)


def send_mqtt(channel: dict, payload: dict) -> None:
    connected = threading.Event()
    error = {"message": ""}

    client = mqtt.Client(
        client_id=channel.get("client_id", ""),
        clean_session=True,
    )

    user = channel.get("username")
    if user:
        client.username_pw_set(user, channel.get("password"))

    if channel.get("tls"):
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

    def on_connect(_client, _userdata, _flags, rc):
        if rc == 0:
            connected.set()
        else:
            error["message"] = f"MQTT Return Code {rc}"
            connected.set()

    client.on_connect = on_connect
    client.connect(
        channel["host"],
        int(channel.get("port", 1883)),
        int(channel.get("keepalive", 60)),
    )
    client.loop_start()

    try:
        if not connected.wait(8):
            raise ConnectionError("MQTT-Verbindung hat das Zeitlimit überschritten.")
        if error["message"]:
            raise ConnectionError(error["message"])

        info = client.publish(
            channel.get("topic", "lanaxy/notifications"),
            json.dumps(payload, ensure_ascii=False),
            qos=int(channel.get("qos", 0)),
            retain=bool(channel.get("retain", False)),
        )
        info.wait_for_publish(timeout=8)

        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"MQTT Publish fehlgeschlagen: RC {info.rc}")
    finally:
        client.disconnect()
        client.loop_stop()


def send_webhook(channel: dict, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "LANaxy/1.1",
    }

    for line in str(channel.get("headers", "")).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()

    token = channel.get("bearer_token")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(
        channel["url"],
        data=body,
        headers=headers,
        method=channel.get("method", "POST").upper(),
    )

    context = None
    if channel.get("verify_tls", True) is False:
        context = ssl._create_unverified_context()

    with urllib.request.urlopen(
        request,
        timeout=int(channel.get("timeout", 10)),
        context=context,
    ) as response:
        if response.status >= 400:
            raise ConnectionError(f"Webhook antwortet mit HTTP {response.status}")



GET_WEBHOOK_DEFAULT_QUERY = (
    "status={status}&guardian={guardien}&message={text}&timestamp={date}"
)


def render_get_webhook_query(template: str, payload: dict) -> str:
    """Render a user-defined GET query while URL-encoding dynamic values."""
    values = {
        "status": str(payload.get("new_status") or payload.get("kind", "event")),
        "guardian": str(payload.get("source", "")),
        "guardien": str(payload.get("source", "")),
        "message": str(payload.get("message", "")),
        "text": str(payload.get("message", "")),
        "timestamp": str(payload.get("timestamp", "")),
        "date": str(payload.get("timestamp", "")),
        "title": str(payload.get("title", "")),
        "kind": str(payload.get("kind", "event")),
    }

    rendered = str(template or GET_WEBHOOK_DEFAULT_QUERY).strip()
    for key, value in values.items():
        rendered = rendered.replace(
            "{" + key + "}",
            urllib.parse.quote_plus(value),
        )
    return rendered.lstrip("?")


def send_get_webhook(channel: dict, payload: dict) -> None:
    """Send a compact, user-defined query string via HTTP GET."""
    rendered_query = render_get_webhook_query(
        channel.get("query_template", GET_WEBHOOK_DEFAULT_QUERY),
        payload,
    )
    parts = urllib.parse.urlsplit(channel["url"])
    query_parts = [part for part in (parts.query, rendered_query) if part]
    query = "&".join(query_parts)
    target_url = urllib.parse.urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        query,
        parts.fragment,
    ))

    headers = {"User-Agent": "LANaxy/1.1"}
    for line in str(channel.get("headers", "")).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()

    token = channel.get("bearer_token")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(target_url, headers=headers, method="GET")
    context = None
    if channel.get("verify_tls", True) is False:
        context = ssl._create_unverified_context()

    with urllib.request.urlopen(
        request,
        timeout=int(channel.get("timeout", 10)),
        context=context,
    ) as response:
        if response.status >= 400:
            raise ConnectionError(
                f"GET-Webhook antwortet mit HTTP {response.status}"
            )

def send_discord(channel: dict, payload: dict) -> None:
    color = {
        "critical": 16729412,
        "warning": 15844367,
        "recovery": 3066993,
        "test": 7506394,
    }.get(payload.get("kind"), 7506394)

    body = {
        "username": channel.get("username", "LANaxy"),
        "content": channel.get("mention", ""),
        "embeds": [
            {
                "title": payload.get("title", "LANaxy"),
                "description": payload.get("message", ""),
                "color": color,
                "fields": [
                    {
                        "name": "Guardian",
                        "value": str(payload.get("source", "unbekannt")),
                        "inline": True,
                    },
                    {
                        "name": "Status",
                        "value": str(
                            payload.get("new_status")
                            or payload.get("kind", "event")
                        ),
                        "inline": True,
                    },
                ],
                "timestamp": payload.get("timestamp"),
            }
        ],
    }

    avatar_url = channel.get("avatar_url")
    if avatar_url:
        body["avatar_url"] = avatar_url

    request = urllib.request.Request(
        channel["webhook_url"],
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "LANaxy/1.1",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=int(channel.get("timeout", 10)),
    ) as response:
        if response.status >= 400:
            raise ConnectionError(f"Discord antwortet mit HTTP {response.status}")



def telegram_api(token: str, method: str, parameters: dict | None = None) -> dict:
    token = token.strip()
    if not token:
        raise ValueError("Bot-Token fehlt.")

    url = (
        "https://api.telegram.org/bot"
        + urllib.parse.quote(token, safe=":")
        + "/"
        + method
    )

    data = None
    if parameters:
        data = urllib.parse.urlencode(parameters).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        method="POST" if data is not None else "GET",
        headers={"User-Agent": "LANaxy/1.1.1"},
    )

    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8"))
            description = payload.get("description")
        except Exception:
            description = str(error)
        raise ConnectionError(
            description or f"Telegram antwortet mit HTTP {error.code}"
        ) from error
    except urllib.error.URLError as error:
        raise ConnectionError(f"Telegram ist nicht erreichbar: {error.reason}") from error

    if not payload.get("ok"):
        raise ConnectionError(
            payload.get("description") or "Telegram-Anfrage fehlgeschlagen."
        )

    return payload


def discover_telegram_chats(token: str) -> dict:
    bot = telegram_api(token, "getMe").get("result", {})
    webhook = telegram_api(token, "getWebhookInfo").get("result", {})

    if webhook.get("url"):
        return {
            "bot": bot,
            "webhook_active": True,
            "webhook_url": webhook.get("url"),
            "pending_update_count": webhook.get("pending_update_count", 0),
            "chats": [],
            "message": (
                "Für diesen Bot ist ein Webhook aktiv. Telegram erlaubt "
                "getUpdates und Webhooks nicht gleichzeitig."
            ),
        }

    updates = telegram_api(
        token,
        "getUpdates",
        {
            "timeout": 0,
            "limit": 100,
            "allowed_updates": json.dumps(
                [
                    "message",
                    "edited_message",
                    "channel_post",
                    "edited_channel_post",
                    "my_chat_member",
                    "callback_query",
                ]
            ),
        },
    ).get("result", [])

    chats: dict[str, dict] = {}

    for update in updates:
        candidates = []

        for key in (
            "message",
            "edited_message",
            "channel_post",
            "edited_channel_post",
            "my_chat_member",
        ):
            value = update.get(key)
            if isinstance(value, dict):
                candidates.append(value)

        callback_message = (
            update.get("callback_query", {})
            .get("message")
        )
        if isinstance(callback_message, dict):
            candidates.append(callback_message)

        for candidate in candidates:
            chat = candidate.get("chat")
            if not isinstance(chat, dict) or "id" not in chat:
                continue

            chat_id = str(chat["id"])
            title = (
                chat.get("title")
                or " ".join(
                    value
                    for value in (
                        chat.get("first_name"),
                        chat.get("last_name"),
                    )
                    if value
                )
                or chat.get("username")
                or chat_id
            )

            chats[chat_id] = {
                "id": chat_id,
                "title": title,
                "username": chat.get("username", ""),
                "type": chat.get("type", "unknown"),
            }

    message = ""
    if not chats:
        message = (
            "Keine Chats gefunden. Sende dem Bot in Telegram zuerst /start "
            "oder eine Nachricht und suche anschließend erneut. Nutzt bereits "
            "ein anderer Dienst wie ioBroker denselben Bot per getUpdates, "
            "kann dieser die Updates vorher abholen."
        )

    return {
        "bot": bot,
        "webhook_active": False,
        "webhook_url": "",
        "pending_update_count": 0,
        "chats": sorted(
            chats.values(),
            key=lambda item: (item["type"], item["title"].lower()),
        ),
        "message": message,
    }

def send_telegram(channel: dict, payload: dict) -> None:
    text = plain_message(payload)
    data = urllib.parse.urlencode(
        {
            "chat_id": channel["chat_id"],
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{channel['bot_token']}/sendMessage",
        data=data,
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=int(channel.get("timeout", 10)),
    ) as response:
        body = json.loads(response.read().decode("utf-8"))
        if response.status >= 400 or not body.get("ok"):
            raise ConnectionError(
                body.get("description")
                or f"Telegram antwortet mit HTTP {response.status}"
            )


def send_email(channel: dict, payload: dict) -> None:
    recipients = [
        item.strip()
        for item in str(channel.get("recipients", "")).replace(";", ",").split(",")
        if item.strip()
    ]
    if not recipients:
        raise ValueError("Keine E-Mail-Empfänger konfiguriert.")

    message = EmailMessage()
    prefix = channel.get("subject_prefix", "[LANaxy]")
    message["Subject"] = f"{prefix} {payload.get('title', 'Ereignis')}".strip()
    message["From"] = channel["sender"]
    message["To"] = ", ".join(recipients)
    message.set_content(plain_message(payload))

    host = channel["smtp_host"]
    port = int(channel.get("smtp_port", 587))
    encryption = channel.get("encryption", "starttls")
    timeout = int(channel.get("timeout", 15))

    if encryption == "ssl":
        smtp = smtplib.SMTP_SSL(
            host,
            port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
    else:
        smtp = smtplib.SMTP(host, port, timeout=timeout)

    try:
        smtp.ehlo()
        if encryption == "starttls":
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()

        username = channel.get("username")
        if username:
            smtp.login(username, channel.get("password", ""))

        smtp.send_message(message)
    finally:
        try:
            smtp.quit()
        except Exception:
            smtp.close()


def send_channel(channel: dict, payload: dict) -> None:
    from custom_beacons import resolve_beacon_class
    from control import global_mute_active, rule_paused

    beacon_class = resolve_beacon_class(channel.get("type", ""))
    beacon_class.validate_config(channel)
    beacon_class(channel).send(payload)


def parse_clock(value: str) -> time | None:
    if not value:
        return None
    try:
        hour, minute = value.split(":", 1)
        return time(int(hour), int(minute))
    except (TypeError, ValueError):
        return None


def quiet_hours_active(rule: dict, now: datetime | None = None) -> bool:
    if not rule.get("quiet_hours_enabled"):
        return False

    start = parse_clock(rule.get("quiet_start", ""))
    end = parse_clock(rule.get("quiet_end", ""))
    if start is None or end is None:
        return False

    current = (now or datetime.now()).time()

    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


class NotificationDispatcher:
    def __init__(self, config: dict, database=None):
        notifications = config.get("notifications", {})
        self.channels = {
            channel["id"]: channel
            for channel in notifications.get("channels", [])
            if channel.get("id")
        }
        self.rules = notifications.get("rules", [])
        self.database = database
        self.timers: dict[int, threading.Timer] = {}
        self.lock = threading.Lock()
        self._resume_pending_jobs()

    def _cancel_repeats(
        self,
        source: str,
        incident_id=None,
        reason="Status hat sich geändert.",
    ) -> None:
        if self.database is not None:
            self.database.cancel_notification_jobs(
                source=source,
                incident_id=incident_id,
                reason=reason,
            )
        with self.lock:
            job_ids = list(self.timers)
            for job_id in job_ids:
                timer = self.timers.get(job_id)
                if timer is None:
                    continue
                if (
                    self.database is None
                    or not self.database.notification_job_is_pending(job_id)
                ):
                    timer.cancel()
                    self.timers.pop(job_id, None)

    def _incident_allows_delivery(self, payload: dict) -> bool:
        if self.database is None:
            return True
        incident_id = payload.get("incident_id")
        if not incident_id:
            return True
        incident = self.database.get_incident(incident_id)
        if not incident:
            return False
        if incident.get("acknowledged_at"):
            return False
        if payload.get("kind") in {"critical", "warning"}:
            return incident.get("status") == "open"
        return True

    def _send_to_rule(
        self,
        rule: dict,
        payload: dict,
        job_id=None,
    ) -> None:
        from control import beacon_muted, global_mute_active, rule_paused

        if job_id and self.database is not None:
            if not self.database.notification_job_is_pending(job_id):
                with self.lock:
                    self.timers.pop(job_id, None)
                return

        error = ""
        try:
            if rule_paused(rule.get("id", "")):
                error = "Rule ist pausiert."
                return
            if global_mute_active(level=payload.get("kind")):
                error = "Benachrichtigungen sind stummgeschaltet."
                return
            if not self._incident_allows_delivery(payload):
                error = "Incident ist quittiert oder nicht mehr offen."
                return

            channel_ids = payload.get("_channel_ids")
            if channel_ids is None:
                channel_ids = (
                    list(self.channels)
                    if rule.get("all_channels", False)
                    else rule.get("channels", [])
                )

            outbound_payload = {
                key: value
                for key, value in payload.items()
                if not key.startswith("_")
            }

            for channel_id in channel_ids:
                channel = self.channels.get(channel_id)
                if not channel or not channel.get("enabled", True):
                    continue
                if beacon_muted(channel_id):
                    continue

                attempts = max(1, min(int(channel.get("retry_attempts", 3) or 3), 5))
                retry_delay = max(1, min(int(channel.get("retry_delay_seconds", 5) or 5), 60))
                last_error = ""
                sent = False
                for attempt in range(1, attempts + 1):
                    try:
                        send_channel(channel, outbound_payload)
                        sent = True
                        break
                    except Exception as channel_error:
                        last_error = str(channel_error)
                        if attempt < attempts:
                            time_module.sleep(retry_delay)

                if sent:
                    record_channel_result(channel_id, True)
                    if self.database is not None:
                        self.database.record_delivery(
                            outbound_payload,
                            rule,
                            channel,
                            True,
                        )
                else:
                    combined_error = f"Nach {attempts} Versuchen fehlgeschlagen: {last_error}"
                    record_channel_result(channel_id, False, combined_error)
                    if self.database is not None:
                        self.database.record_delivery(
                            outbound_payload,
                            rule,
                            channel,
                            False,
                            combined_error,
                        )
        finally:
            if job_id and self.database is not None:
                self.database.complete_notification_job(
                    job_id,
                    error=error,
                )
            if job_id:
                with self.lock:
                    self.timers.pop(job_id, None)

    def _schedule_job(
        self,
        rule: dict,
        payload: dict,
        delay_seconds: int,
    ) -> None:
        delay_seconds = max(0, int(delay_seconds))
        due = datetime.now() + timedelta(seconds=delay_seconds)
        incident_id = payload.get("incident_id")

        if self.database is None:
            timer = threading.Timer(
                delay_seconds,
                self._send_to_rule,
                args=(rule, payload),
            )
            timer.daemon = True
            timer.start()
            return

        job_id = self.database.create_notification_job(
            due.isoformat(timespec="seconds"),
            payload.get("source", "unknown"),
            incident_id,
            rule,
            payload,
        )
        if delay_seconds == 0:
            self._send_to_rule(rule, payload, job_id)
            return

        timer = threading.Timer(
            delay_seconds,
            self._send_to_rule,
            args=(rule, payload, job_id),
        )
        timer.daemon = True
        with self.lock:
            self.timers[job_id] = timer
        timer.start()

    def _schedule(self, rule: dict, payload: dict) -> None:
        delay = max(0, int(rule.get("delay_seconds", 0) or 0))
        repeat_minutes = max(
            0,
            int(rule.get("repeat_minutes", 0) or 0),
        )
        repeat_count = max(
            0,
            int(rule.get("repeat_count", 0) or 0),
        )

        self._schedule_job(rule, payload, delay)

        if payload.get("kind") in {"critical", "warning"}:
            for step in rule.get("escalation_steps", []):
                minutes = max(
                    0,
                    int(step.get("after_minutes", 0) or 0),
                )
                channels = [
                    channel_id
                    for channel_id in step.get("channels", [])
                    if channel_id
                ]
                if minutes <= 0 or not channels:
                    continue
                escalated_payload = dict(payload)
                escalated_payload["_channel_ids"] = channels
                escalated_payload["escalation_after_minutes"] = minutes
                self._schedule_job(
                    rule,
                    escalated_payload,
                    delay + minutes * 60,
                )

        if (
            payload.get("kind") in {"critical", "warning"}
            and repeat_minutes > 0
        ):
            for index in range(1, repeat_count + 1):
                self._schedule_job(
                    rule,
                    payload,
                    delay + repeat_minutes * 60 * index,
                )

    def _resume_pending_jobs(self) -> None:
        if self.database is None:
            return

        for job in self.database.pending_notification_jobs():
            try:
                payload = json.loads(job["payload_json"])
                rule = json.loads(job["rule_json"])
                due = datetime.fromisoformat(job["due_at"])
                delay = max(
                    0,
                    int((due - datetime.now()).total_seconds()),
                )
                timer = threading.Timer(
                    delay,
                    self._send_to_rule,
                    args=(rule, payload, job["id"]),
                )
                timer.daemon = True
                with self.lock:
                    self.timers[job["id"]] = timer
                timer.start()
            except Exception as error:
                self.database.complete_notification_job(
                    job["id"],
                    error=str(error),
                )

    def shutdown(self) -> None:
        """Stop local timers without deleting persistent notification jobs."""
        with self.lock:
            timers = list(self.timers.values())
            self.timers.clear()
        for timer in timers:
            timer.cancel()

    def handle_event(self, event) -> None:
        payload = notification_payload(event)
        kind = payload["kind"]
        old_status = str(getattr(event, "old_status", "") or "")
        new_status = str(getattr(event, "new_status", "") or "")
        incident_id = payload.get("incident_id")

        if kind == "recovery" or new_status == "maintenance":
            self._cancel_repeats(
                event.source,
                incident_id=incident_id,
                reason=(
                    "Guardian hat sich erholt."
                    if kind == "recovery"
                    else "Guardian befindet sich in Wartung."
                ),
            )

        if old_status == "maintenance" and new_status == "ok":
            return

        # A blocked Guardian is a consequential failure of its dependency,
        # not a separate alert source. Cancel queued jobs and suppress both
        # the blocked warning and the duplicate blocked -> ok recovery.
        if new_status == "blocked" or (
            old_status == "blocked" and new_status == "ok"
        ):
            self._cancel_repeats(
                event.source,
                incident_id=incident_id,
                reason="Folgefehler wird über die primäre Ursache gemeldet.",
            )
            return

        for rule in self.rules:
            if not rule.get("enabled", True):
                continue
            if kind not in rule.get(
                "statuses",
                ["critical", "recovery"],
            ):
                continue
            if quiet_hours_active(rule):
                continue
            event_details = event.details if isinstance(event.details, dict) else {}
            result_details = event_details.get("details", {})
            if not isinstance(result_details, dict):
                result_details = {}
            is_root_cause = bool(
                event_details.get("root_cause")
                or result_details.get("root_cause")
                or event_details.get("root_cause_id") == event.source
                or result_details.get("root_cause_id") == event.source
            )
            if rule.get("root_cause_only") and not (
                is_root_cause or kind == "recovery"
            ):
                continue

            if not rule.get("all_groups", True):
                groups = rule.get("groups", [])
                if (
                    groups
                    and event.details.get("group") not in groups
                ):
                    continue

            if not rule.get("all_guardians", True):
                guardians = rule.get("guardians", [])
                if guardians and event.source not in guardians:
                    continue

            payload_for_rule = dict(payload)
            payload_for_rule["rule_id"] = rule.get("id", "")
            payload_for_rule["rule_name"] = rule.get("name", "")
            self._schedule(rule, payload_for_rule)


def test_channel(
    channel: dict,
    language: str = "de",
) -> None:
    name = channel.get("name", channel.get("type", "Beacon"))
    beacon_type = channel.get("type", "unknown")

    if language == "en":
        title = "LANaxy Beacon Test"
        message = (
            f"The Beacon '{name}' ({beacon_type}) successfully sent "
            "this test notification."
        )
    else:
        title = "LANaxy Beacon-Test"
        message = (
            f"Der Beacon „{name}“ ({beacon_type}) hat diese "
            "Testnachricht erfolgreich versendet."
        )

    payload = {
        "kind": "test",
        "title": title,
        "message": message,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "source": name,
        "beacon_type": beacon_type,
        "new_status": "ok",
        "level": 0,
    }
    send_channel(channel, payload)
    record_channel_result(channel.get("id", "temporary_test"), True)
