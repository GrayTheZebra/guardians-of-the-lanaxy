from models.result import Result


class BaseGuardian:
    GUARDIAN = {
        "id": "base",
        "name": "Base Guardian",
        "version": "1.0.0",
        "description": "Basisklasse für LANaxy Guardians",
        "icon": "shield",
        "category": "Allgemein",
    }

    CONFIG_SCHEMA = {}
    REQUIRED: tuple[str, ...] = ()

    def __init__(self, check: dict):
        self.check = check
        self.id = check["id"]
        self.device_id = check.get("device_id", self.id)
        self.name = check.get("name", self.id)
        self.timeout = int(check.get("timeout", 3))

    @classmethod
    def validate_config(cls, check: dict) -> None:
        missing = [field for field in cls.REQUIRED if field not in check]
        if missing:
            raise ValueError(
                f"Fehlende Guardian-Konfiguration: {', '.join(missing)}"
            )

    def result(
        self,
        status: str,
        level: int,
        message: str,
        response_time: int = 0,
        details: dict | None = None,
    ) -> Result:
        return Result(
            id=self.id,
            device_id=self.device_id,
            name=self.name,
            status=status,
            level=level,
            message=message,
            response_time=response_time,
            details=details or {},
        )

    def ok(self, message, response_time=0, details=None):
        return self.result("ok", 0, message, response_time, details)

    def warning(self, message, response_time=0, details=None):
        return self.result("warning", 1, message, response_time, details)

    def critical(self, message, response_time=0, details=None):
        return self.result("critical", 2, message, response_time, details)


    def remote(self, check_type: str):
        from miniguard_manager import execute_remote_check
        agent_id = str(self.check.get("miniguard_id", "")).strip()
        if not agent_id:
            return self.critical(f"{self.name}: Kein MiniGuard ausgewählt", details={"error_code": "miniguard_missing"})
        excluded = {"guardian", "execution_source", "miniguard_id", "enabled", "interval", "retries"}
        parameters = {k: v for k, v in self.check.items() if k not in excluded}
        result = execute_remote_check(agent_id, check_type, parameters, self.timeout)
        status = str(result.get("status", "unknown"))
        message = str(result.get("message") or f"{self.name}: MiniGuard lieferte kein Ergebnis")
        details = dict(result.get("details") or {})
        details.update({"execution_source": "miniguard", "miniguard_id": agent_id, "error_code": result.get("error_code")})
        ms = int(result.get("duration_ms", 0) or 0)
        levels = {"ok": 0, "warning": 1, "critical": 2, "unknown": 2}
        return self.result(status if status in levels else "unknown", levels.get(status, 2), message, ms, details)

    def run(self) -> Result:
        raise NotImplementedError
