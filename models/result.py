from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Result:
    id: str
    name: str
    status: str
    level: int
    message: str
    device_id: str = ""
    response_time: int = 0
    uptime: float = 100.0
    last_error: str = ""
    last_recovery: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    last_check: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
