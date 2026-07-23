from datetime import datetime
from typing import Any

from control import runtime_maintenance


def maintenance_active(check: dict[str, Any], now: datetime | None = None) -> bool:
    maintenance = check.get("maintenance", {})
    if not isinstance(maintenance, dict) or not maintenance.get("active"):
        return False

    until = maintenance.get("until")
    if not until:
        return True

    try:
        end = datetime.fromisoformat(until)
    except (TypeError, ValueError):
        return True

    return (now or datetime.now()) < end


def maintenance_label(
    check: dict[str, Any],
    maintenance: dict[str, Any] | None = None,
) -> str:
    maintenance = maintenance or check.get("maintenance", {})
    until = maintenance.get("until")
    if until:
        return f"Wartung aktiv bis {until.replace('T', ' ')}"
    return "Wartungsmodus aktiv"



def scheduled_maintenance_for(check: dict[str, Any], windows: list[dict[str, Any]] | None = None, now: datetime | None = None) -> dict[str, Any] | None:
    """Return the first active planned maintenance window for a Guardian."""
    now = now or datetime.now()
    check_id = str(check.get("id", ""))
    group = str(check.get("group", ""))
    for window in windows or []:
        if not isinstance(window, dict) or not window.get("enabled", True):
            continue
        try:
            starts_at = datetime.fromisoformat(str(window.get("starts_at", "")))
            ends_at = datetime.fromisoformat(str(window.get("ends_at", "")))
        except (TypeError, ValueError):
            continue
        if not (starts_at <= now < ends_at):
            continue
        guardian_ids = [str(v) for v in window.get("guardian_ids", [])]
        groups = [str(v) for v in window.get("groups", [])]
        if check_id not in guardian_ids and (not group or group not in groups):
            continue
        return {
            "active": True,
            "scheduled": True,
            "window_id": window.get("id", ""),
            "name": window.get("name", "Geplante Wartung"),
            "reason": window.get("reason", ""),
            "until": window.get("ends_at", ""),
        }
    return None


def topology_diagnostics(checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Return orphan dependencies and cycles for the topology UI."""
    ids = {str(c.get("id")) for c in checks}
    orphans = []
    graph = {}
    for check in checks:
        cid = str(check.get("id", ""))
        deps = check.get("depends_on", [])
        if isinstance(deps, str):
            deps = [deps]
        graph[cid] = [str(d) for d in deps if d]
        for dep in graph[cid]:
            if dep not in ids:
                orphans.append({"guardian_id": cid, "dependency_id": dep})

    cycles = []
    visited, active, path = set(), set(), []
    def visit(node):
        if node in active:
            try:
                start = path.index(node)
                cycle = path[start:] + [node]
            except ValueError:
                cycle = [node, node]
            if cycle not in cycles:
                cycles.append(cycle)
            return
        if node in visited:
            return
        visited.add(node); active.add(node); path.append(node)
        for nxt in graph.get(node, []):
            if nxt in graph:
                visit(nxt)
        path.pop(); active.remove(node)
    for node in graph:
        visit(node)
    return {"orphans": orphans, "cycles": cycles}

def apply_runtime_policies(
    checks: list[dict[str, Any]],
    results: list,
    state_checks: dict[str, Any] | None = None,
    maintenance_windows: list[dict[str, Any]] | None = None,
):
    state_checks = state_checks or {}
    check_by_id = {check["id"]: check for check in checks}
    result_by_id = {result.id: result for result in results}

    # Maintenance wins over normal status handling.
    for check in checks:
        result = result_by_id.get(check["id"])
        runtime = runtime_maintenance(check["id"])
        scheduled = scheduled_maintenance_for(check, maintenance_windows)
        if result is None or not (maintenance_active(check) or runtime or scheduled):
            continue

        result.details["underlying_status"] = result.status
        result.details["underlying_level"] = result.level
        active_maintenance = runtime or scheduled or check.get("maintenance", {})
        result.details["maintenance"] = active_maintenance
        result.status = "maintenance"
        result.level = 0
        result.message = maintenance_label(
            check,
            active_maintenance,
        )

    blocked_by: dict[str, str] = {}

    # Resolve dependencies using current run results first and stored state second.
    for check in checks:
        result = result_by_id.get(check["id"])
        if result is None or result.status == "maintenance":
            continue

        dependencies = check.get("depends_on", [])
        if isinstance(dependencies, str):
            dependencies = [dependencies]

        for dependency_id in dependencies:
            dependency_result = result_by_id.get(dependency_id)
            if dependency_result is not None:
                dependency_status = dependency_result.status
                dependency_level = dependency_result.level
            else:
                dependency_state = state_checks.get(dependency_id, {})
                dependency_status = dependency_state.get("status", "unknown")
                dependency_level = int(dependency_state.get("level", 0) or 0)

            if dependency_status in {"warning", "critical", "blocked"} or dependency_level >= 1:
                blocked_by[check["id"]] = dependency_id
                break

    for check_id, dependency_id in blocked_by.items():
        result = result_by_id[check_id]
        original = {
            "status": result.status,
            "level": result.level,
            "message": result.message,
        }
        result.details["underlying_result"] = original
        result.details["blocked_by"] = dependency_id
        result.status = "blocked"
        result.level = 1
        dependency_name = check_by_id.get(dependency_id, {}).get(
            "name",
            dependency_id,
        )
        result.message = f"Abhängiger Fehler – Ursache: {dependency_name}"

        dependency_result = result_by_id.get(dependency_id)
        if dependency_result is not None:
            dependency_result.details["root_cause"] = True
            dependency_result.details.setdefault("blocked_dependents", []).append(
                check_id
            )

    return results
