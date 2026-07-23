"""Execution-source abstraction for current and future Guardians.

Protocol v1 deliberately exposes only named check types and validated parameter
objects. It never accepts shell commands. The local adapter is the default;
MiniGuard transport is registered in a later release when individual Guardians
are migrated to this interface.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable

VALID_STATUSES = {'ok', 'warning', 'critical', 'unknown'}

@dataclass(frozen=True)
class CheckRequest:
    check_type: str
    parameters: dict[str, Any]
    protocol_version: int = 1

@dataclass(frozen=True)
class CheckResponse:
    status: str
    message: str
    details: dict[str, Any]
    duration_ms: int = 0
    error_code: str | None = None

    def __post_init__(self):
        if self.status not in VALID_STATUSES:
            raise ValueError(f'Ungültiger Check-Status: {self.status}')

class CheckSourceRegistry:
    def __init__(self):
        self._adapters: dict[str, Callable[[CheckRequest], CheckResponse]] = {}

    def register(self, name: str, adapter: Callable[[CheckRequest], CheckResponse]) -> None:
        if not name or name in self._adapters:
            raise ValueError('Prüfquelle fehlt oder ist bereits registriert.')
        self._adapters[name] = adapter

    def execute(self, source: str, request: CheckRequest) -> CheckResponse:
        adapter = self._adapters.get(source)
        if adapter is None:
            return CheckResponse('unknown', f'Prüfquelle {source} ist nicht verfügbar.', {}, error_code='source_unavailable')
        return adapter(request)
