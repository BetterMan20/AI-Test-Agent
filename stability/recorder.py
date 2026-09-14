# -*- coding: utf-8 -*-
"""P0 Event Recorder —— 随机/攻击事件流记录。

每条事件落一行 JSON(events.jsonl)：编号/时间/类型/参数/当前状态/执行结果。
同时在内存保留，供 crash 后导出「前 N 事件序列」（Failure Shrinking 的输入）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional


class EventRecorder:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = self.path.open("a", encoding="utf-8")
        self._counter = 0
        self._all: list[dict[str, Any]] = []

    def record(
        self,
        etype: str,
        params: dict[str, Any],
        state: str,
        result: str = "ok",
        note: str = "",
    ) -> int:
        self._counter += 1
        ev = {
            "seq": self._counter,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ts": round(time.time(), 3),
            "type": etype,
            "params": params,
            "state": state,
            "result": result,
        }
        if note:
            ev["note"] = note
        self._f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        self._f.flush()
        self._all.append(ev)
        return self._counter

    def last_n(self, n: int) -> list[dict[str, Any]]:
        return self._all[-n:]

    def all(self) -> list[dict[str, Any]]:
        return list(self._all)

    def export_sequence(self, tail: Optional[int] = None) -> list[str]:
        """导出事件序列（用户给的 #38718 CLICK gift 风格），供报告/shrinking。"""
        src = self._all[-tail:] if tail else self._all
        return [
            "#%d %s %s" % (e["seq"], e["type"], _brief_params(e))
            for e in src
        ]

    def close(self) -> None:
        try:
            self._f.close()
        except Exception:
            pass


def _brief_params(e: dict[str, Any]) -> str:
    p = e.get("params", {})
    for k in ("text", "desc", "kind", "coords", "widget"):
        if p.get(k):
            return str(p[k])
    return str(p)[:40]