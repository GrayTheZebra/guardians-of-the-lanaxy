import importlib
from custom_guardians import load_custom_module
from models.result import Result

CUSTOM_PREFIX = "custom:"

def resolve_guardian_class(name):
    if name.startswith(CUSTOM_PREFIX):
        module = load_custom_module(name[len(CUSTOM_PREFIX):])
    else:
        module = importlib.import_module(f"guardians.{name}")
    return module.Guardian

def load_guardian(check):
    guardian_class = resolve_guardian_class(check["guardian"])
    guardian_class.validate_config(check)
    return guardian_class(check)

def run_checks(checks):
    results = []
    for check in checks:
        if not check.get("enabled", True):
            continue
        try:
            results.append(load_guardian(check).run())
        except Exception as error:
            results.append(Result(
                id=check.get("id", "unknown"),
                device_id=check.get("device_id", check.get("id", "unknown")),
                name=check.get("name", check.get("id", "unknown")),
                status="critical", level=2,
                message=f"Guardian-Fehler: {error}",
                details={"guardian": check.get("guardian"), "error": str(error)}
            ))
    return results

def get_guardian_metadata(checks):
    result = []
    for check in checks:
        try:
            cls = resolve_guardian_class(check["guardian"])
            meta = cls.GUARDIAN.copy()
            meta.update({
                "check_id": check["id"],
                "device_id": check.get("device_id", check["id"]),
                "check_name": check.get("name", check["id"]),
                "status": "loaded",
                "source": "custom" if check["guardian"].startswith(CUSTOM_PREFIX) else "builtin",
            })
            result.append(meta)
        except Exception as error:
            result.append({"id": check.get("guardian"), "status": "failed", "error": str(error)})
    return result
