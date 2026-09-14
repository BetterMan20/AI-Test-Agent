# -*- coding: utf-8 -*-
"""ADB + UI 自动化流程（可复用）。

执行动作：wakeup/unlock -> uiautomator dump 页面 -> 解析红包/礼物入口坐标 ->
input tap 触碰 -> 回 dump 验证面板。每一步采集 adb_command/output/execution
证据，并按需补 screenshot + logcat。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.android.client import ADBClient
from evidence.collector import EvidenceCollector
from evidence.store import EvidenceStore

RED_KW = ("红包", "redpacket", "red_packet", "red packet", "lucky", "幸运", "开红包", "抢红包")
GIFT_KW = ("gift", "礼物", "iv_gift", "fl_gift", "金币", "coin")
PANEL_KW = ("coins", "金币", "red", "红包", "quantity", "人数", "send", "发送", "countdown", "抢")


@dataclass
class UIStep:
    """一次 UI 自动化步骤。"""

    tc_id: str
    kind: str          # dump / tap / verify
    title: str
    detail: str        # 动作描述或当前视图摘要
    output_len: int
    status: str        # pass / error / skip
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tc_id": self.tc_id,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "output_len": self.output_len,
            "status": self.status,
            "evidence": self.evidence,
        }


def parse_panel_target(xml: str) -> tuple[int, int, int] | None:
    """从 uiautomator XML 找红包/礼物入口，返回 (x, y, priority)。"""
    nodes = re.findall(r"<node[^>]*?>", xml)
    best = None
    best_pri = 0
    best_area = 0
    for n in nodes:
        m = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', n)
        if not m:
            continue
        text = (re.search(r'text="([^"]*)"', n) or [None, ""])[1]
        desc = (re.search(r'content-desc="([^"]*)"', n) or [None, ""])[1]
        rid = (re.search(r'resource-id="([^"]*)"', n) or [None, ""])[1]
        hay = f"{text} {desc} {rid}".lower()
        if any(k.lower() in hay for k in RED_KW):
            pri = 3
        elif any(k.lower() in hay for k in GIFT_KW):
            pri = 2
        else:
            continue
        x1, y1, x2, y2 = map(int, m.group(1, 2, 3, 4))
        area = (x2 - x1) * (y2 - y1)
        if pri > best_pri or (pri == best_pri and area > best_area):
            best_pri = pri
            best_area = area
            best = ((x1 + x2) // 2, (y1 + y2) // 2, pri)
    return best


class UIFlowExecutor:
    """在指定设备上跑一条‘dump->点红包入口->验证面板’的 UI 自动化回归。"""

    def __init__(
        self,
        evidence_root: str | Path,
        device_serial: str = "",
        timeout: int = 30,
    ):
        self._store = EvidenceStore(base_dir=str(evidence_root))
        self._collector = EvidenceCollector(self._store)
        self._client = ADBClient(device_serial=device_serial, timeout=timeout)
        self._serial = device_serial

    def _dump_cmd(self, tag: str) -> str:
        return (
            "input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; "
            f"uiautomator dump /sdcard/_ui_{tag}.xml >/dev/null 2>&1; "
            f"cat /sdcard/_ui_{tag}.xml"
        )

    def run(
        self,
        tc_prefix: str = "TC-UI",
        max_steps: int = 4,
    ) -> list[UIStep]:
        steps: list[UIStep] = []
        tag_ctr = 0

        # --- 1. 初始 dump ---
        tag_ctr += 1
        tc = f"{tc_prefix}-{1:03d}"
        cmd = self._dump_cmd(f"b{tag_ctr}")
        out = self._client.shell(cmd)
        ev = self._collect_adb(tc, "dump", "加载当前直播页面并 dump UI", cmd, out)
        steps.append(UIStep(
            tc, "dump", "dump 当前页面", self._summary(xml) if (xml := out) else "",
            len(out), "pass" if ("<hierarchy" in out) else "error", ev,
        ))
        cur = out

        # --- 2..N. 迭代点击下钻 ---
        seq = 2
        hit_red = False
        for _ in range(max(0, max_steps - 1)):
            tgt = parse_panel_target(cur)
            if tgt is None:
                steps.append(self._mk(None, "skip", "当前视图未发现红包/礼物入口", ""))
                break
            x, y, pri = tgt
            kind = "红包入口" if pri >= 3 else "礼物面板"
            tag_ctr += 1
            tc = f"{tc_prefix}-{seq:03d}"
            seq += 1
            c = f"input tap {x} {y}; sleep 2; {self._dump_cmd(f'a{tag_ctr}')}"
            out2 = self._client.shell(c)
            ev = self._collect_adb(tc, "tap", f"点击{kind} ({x},{y})", c, out2)
            steps.append(UIStep(
                tc, "tap", f"input tap {x} {y} 触碰{kind}", "",
                len(out2), "pass", ev,
            ))
            cur = out2
            if pri >= 3:
                hit_red = True
                break

        # --- 3. 面板校验 ---
        low = cur.lower()
        hit = any(k in low for k in PANEL_KW)
        vtc = f"{tc_prefix}-{seq:03d}" if seq < 100 else f"{tc_prefix}-F"
        steps.append(UIStep(
            vtc, "verify", "红包/面板特征校验",
            "命中红包/金币特征" if hit else "未命中红包/金币特征",
            len(cur), "pass" if hit else "error", [],
        ))
        return steps

    def _collect_adb(self, tc_id: str, tag: str, title: str, cmd: str, output: str) -> list[str]:
        meta = {
            "duration_ms": 0,
            "status": "pass",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        }
        evs = self._collector.collect_adb_evidence(
            {"command": cmd, "args": []}, output, tc_id, 1, meta,
        )
        self._collector.collect_screenshot(self._client, tc_id, 1)
        self._collector.collect_logcat(self._client, tc_id, 1)
        return [e.path for e in evs]

    @staticmethod
    def _summary(xml: str, limit: int = 80) -> str:
        text = " ".join(re.findall(r'text="([^"]+)"', xml))
        return text[:limit] or ""

    @staticmethod
    def _mk(tc, kind, title, detail):
        return UIStep(tc, kind, title, detail, 0, "skip", [])


def run_adb_ui_regression(
    evidence_root: str | Path,
    device_serial: str = "",
    tc_prefix: str = "TC-UI",
    max_steps: int = 4,
) -> list[UIStep]:
    """一键跑 ADB/UI 回归，返回步骤清单。"""
    return UIFlowExecutor(evidence_root, device_serial).run(tc_prefix, max_steps)