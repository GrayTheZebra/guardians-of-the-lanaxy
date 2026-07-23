import json
import os
from datetime import datetime
from pathlib import Path


class StateStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.data = self.load()

    def load(self):
        if not self.path.exists():
            return {"checks": {}}

        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return {"checks": {}}

        return data if isinstance(data, dict) else {"checks": {}}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)

        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")

        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(self.data, file, indent=2, ensure_ascii=False)

        os.replace(temporary_path, self.path)

    def apply_retry_logic(self, result, retries: int):
        retries = max(1, retries)
        checks = self.data.setdefault("checks", {})
        old = checks.get(result.id, {})
        failed_count = int(old.get("failed_count", 0))

        if result.status == "blocked":
            result.details["retry"] = {
                "failed_count": failed_count,
                "required_failures": retries,
                "suppressed_by_dependency": True,
            }
            return result, failed_count

        if result.level == 0:
            result.details["retry"] = {
                "failed_count": 0,
                "required_failures": retries,
            }
            return result, 0

        failed_count += 1

        result.details["retry"] = {
            "failed_count": failed_count,
            "required_failures": retries,
        }

        if failed_count < retries:
            original_message = result.message
            result.status = "warning"
            result.level = 1
            if not result.details.get("suppress_retry_suffix"):
                result.message = f"{original_message} ({failed_count}/{retries})"

        return result, failed_count

    def update_result(self, result, retries: int = 1):
        now = datetime.now().isoformat(timespec="seconds")
        result, failed_count = self.apply_retry_logic(result, retries)

        checks = self.data.setdefault("checks", {})
        old = checks.get(result.id, {})

        previous_status = old.get("status")
        current_status = result.status

        total = int(old.get("total_checks", 0)) + 1
        ok_count = int(old.get("ok_checks", 0)) + (
            1 if result.level == 0 else 0
        )

        result.uptime = round((ok_count / total) * 100, 2)

        last_error = old.get("last_error", "")
        last_recovery = old.get("last_recovery", "")

        status_changed = (
            previous_status is not None and previous_status != current_status
        )

        if result.level > 0 and previous_status != current_status:
            last_error = f"{now} - {result.message}"

        if result.level == 0 and previous_status and previous_status != "ok":
            last_recovery = f"{now} - {result.message}"

        result.last_error = last_error
        result.last_recovery = last_recovery

        checks[result.id] = {
            "device_id": result.device_id,
            "status": current_status,
            "level": result.level,
            "message": result.message,
            "last_check": result.last_check,
            "last_error": last_error,
            "last_recovery": last_recovery,
            "total_checks": total,
            "ok_checks": ok_count,
            "failed_count": 0 if result.level == 0 else failed_count,
            "uptime": result.uptime,
            "details": result.details,
        }

        self.save()

        return status_changed, result, previous_status or "", current_status
