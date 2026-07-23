"""MiniGuard/LANaxy compatibility policy.

The table is intentionally explicit so future LANaxy releases can raise the
required Agent version when protocol or check behavior changes.
"""
from __future__ import annotations

import re
from typing import Any

CURRENT_PROTOCOL_VERSION = 1

# Minimum/recommended MiniGuard version per LANaxy release line.
COMPATIBILITY_LINES = (
    {
        "lanaxy_min": (1, 28, 0),
        "lanaxy_max": (1, 29, 999),
        "minimum_agent": (1, 7, 0),
        "recommended_agent": (1, 7, 2),
        "protocol_version": 1,
    },
)


def parse_version(value: Any) -> tuple[int, int, int] | None:
    match = re.match(r"^\s*v?(\d+)\.(\d+)\.(\d+)", str(value or ""))
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def format_version(value: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in value)


def policy_for(lanaxy_version: Any) -> dict[str, Any]:
    parsed = parse_version(lanaxy_version)
    if parsed:
        for policy in COMPATIBILITY_LINES:
            if policy["lanaxy_min"] <= parsed <= policy["lanaxy_max"]:
                return dict(policy)
    # Safe fallback: current release's requirements.
    return dict(COMPATIBILITY_LINES[-1])


def evaluate_agent(agent: dict[str, Any], lanaxy_version: Any) -> dict[str, Any]:
    policy = policy_for(lanaxy_version)
    installed = parse_version(agent.get("agent_version"))
    protocol = agent.get("protocol_version")
    minimum = policy["minimum_agent"]
    recommended = policy["recommended_agent"]
    expected_protocol = policy["protocol_version"]

    result = {
        "compatible": False,
        "update_required": False,
        "status": "unknown",
        "reason": "",
        "minimum_version": format_version(minimum),
        "recommended_version": format_version(recommended),
        "expected_protocol": expected_protocol,
        "installed_version": agent.get("agent_version") or "",
    }

    if not agent.get("registered"):
        result.update(status="unregistered", reason="MiniGuard ist noch nicht registriert.")
        return result
    if installed is None:
        result.update(
            status="unknown",
            update_required=True,
            reason=f"Der Agent meldet keine auswertbare Version. Erwartet wird mindestens {result['minimum_version']}.",
        )
        return result
    try:
        protocol_number = int(protocol)
    except (TypeError, ValueError):
        protocol_number = None
    if protocol_number != expected_protocol:
        result.update(
            status="incompatible",
            update_required=True,
            reason=f"Protokoll {protocol_number or 'unbekannt'} ist nicht mit Protokoll {expected_protocol} kompatibel.",
        )
        return result
    if installed < minimum:
        result.update(
            status="outdated",
            update_required=True,
            reason=(
                f"MiniGuard {format_version(installed)} ist für LANaxy {lanaxy_version} zu alt. "
                f"Mindestens {result['minimum_version']} ist erforderlich."
            ),
        )
        return result
    result.update(compatible=True, status="compatible")
    if installed < recommended:
        result.update(
            status="update_recommended",
            reason=f"Kompatibel, empfohlen ist jedoch MiniGuard {result['recommended_version']}.",
        )
    elif installed > recommended:
        result["reason"] = (
            f"MiniGuard {format_version(installed)} verwendet das passende Protokoll und ist neuer "
            f"als die für diese LANaxy-Version empfohlene Agent-Version."
        )
    else:
        result["reason"] = f"MiniGuard {format_version(installed)} passt zu LANaxy {lanaxy_version}."
    return result
