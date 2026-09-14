# -*- coding: utf-8 -*-
"""P0 Crash/ANR Monitor —— 用 adb logcat 增量监控崩溃类事件。

监测: Crash / ANR / Force Close / Freeze。
命中时: 抓去新 logcat 片段 + 截图，并把当前事件序列一并转给 runner。
"""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tools.android.client import ADBClient

# logcat 崩溃关键词 ── android 常见标记与包名相关
_CRASH_PATS = [
    (r"FATAL EXCEPTION", "crash"),
    (r"AndroidRuntime.*Process: ", "crash"),
    (r"ANR in %s", "anr"),
    (r"am_anr", "anr"),
    (r"has died", "force_close"),
    (r"Force finishing activity", "force_close"),
    (r"am_crash", "crash"),
]

_FREEZE_PATS = [r"Watchdog", r"Input dispatching timed out", r"Choreographer.*Skipped"]


@dataclass
class Failure:
    kind: str            # crash / anr / force_close / freeze
    seq: int             # 命中时的事件序号
    pattern: str
    snippet: str
    logcat_file: str = ""
    screenshot: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "seq": self.seq,
            "pattern": self.pattern,
            "snippet": self.snippet[:200],
            "logcat_file": self.logcat_file,
            "screenshot": self.screenshot,
        }


class CrashMonitor:
    def __init__(self, package: str, device_serial: str = "",
                 root: str | Path = "output/evidence_stability") -> None:
        self.pkg = package
        self._client = ADBClient(device_serial)
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        # 预处理用户证书无关，仅 logcat
        self._since_line = None

    def _raw_logcat(self) -> list[str]:
        try:
            out = self._client.shell("logcat -d -t 800")
            return out.splitlines()
        except Exception:
            return []

    def poll(self, seq: int, events_tail: list[str]) -> Optional[Failure]:
        lines = self._raw_logcat()
        joined = "\n".join(lines)

        for pat, kind in _CRASH_PATS:
            rx = pat % self.pkg if "%s" in pat else pat
            m = re.search(re.compile(rx), joined)
            if m:
                return self._capture(seq, kind, rx, lines, events_tail)

        for pat in _FREEZE_PATS:
            if re.search(pat, joined):
                return self._capture(seq, "freeze", pat, lines, events_tail)
        return None

    def _capture(self, seq, kind, pattern, lines, events_tail):
        f = Failure(kind=kind, seq=seq, pattern=pattern,
                    snippet="\n".join(lines[-40:]),)
        # 截图与事件序列
        try:
            shot = str(self.root / f"shot_seq{seq}.png")
            self._client.screenshot(shot)
            f.screenshot = shot
        except Exception:
            pass
        logfile = str(self.root / f"crash_seq{seq}.log")
        Path(logfile).write_text("\n".join(lines), encoding="utf-8", errors="replace")
        f.logcat_file = logfile
        try:
            seqfile = str(self.root / f"events_seq{seq}.txt")
            Path(seqfile).write_text("\n".join(events_tail), encoding="utf-8")
        except Exception:
            pass
        return f