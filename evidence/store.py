"""Evidence storage — persists evidence metadata to disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evidence.models import Evidence


class EvidenceStore:
    """将证据元数据按 TC ID + 步骤号归档到磁盘。"""

    def __init__(self, base_dir: str = "output/evidence"):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    @property
    def base_dir(self) -> Path:
        return self._base

    def save(self, evidence: Evidence) -> str:
        tc_dir = self._base / evidence.tc_id
        tc_dir.mkdir(parents=True, exist_ok=True)
        artifact = evidence.metadata.get("artifact", evidence.type.value)
        meta_path = tc_dir / f"step{evidence.step_id}_{artifact}_meta.json"
        meta_path.write_text(
            json.dumps(evidence.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(meta_path)

    def list_for_tc(self, tc_id: str) -> list[dict[str, Any]]:
        tc_dir = self._base / tc_id
        if not tc_dir.exists():
            return []
        return [
            json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(tc_dir.glob("*.json"))
        ]

    def list_all(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for tc_dir in sorted(self._base.iterdir()):
            if tc_dir.is_dir():
                result.extend(self.list_for_tc(tc_dir.name))
        return result
