"""Evidence data models."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EvidenceType(str, Enum):
    """证据类型枚举。"""

    SCREENSHOT = "screenshot"
    LOGCAT = "logcat"
    API_RESPONSE = "api_response"
    DB_SNAPSHOT = "db_snapshot"
    TEXT = "text"


@dataclass
class Evidence:
    """单条证据制品。"""

    type: EvidenceType
    path: str
    tc_id: str
    step_id: int
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.hash and self.path:
            self.hash = self._compute_hash()

    def _compute_hash(self) -> str:
        try:
            with open(self.path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()[:16]
        except (OSError, IOError):
            return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value if isinstance(self.type, EvidenceType) else str(self.type),
            "path": self.path,
            "tc_id": self.tc_id,
            "step_id": self.step_id,
            "timestamp": self.timestamp,
            "hash": self.hash,
            "metadata": self.metadata,
        }
