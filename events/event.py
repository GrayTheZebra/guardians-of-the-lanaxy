from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Event:
    type: str
    source: str
    device_id: str
    message: str
    old_status: str = ""
    new_status: str = ""
    level: int = 0
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
