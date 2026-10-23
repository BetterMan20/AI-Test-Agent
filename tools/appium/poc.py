# -*- coding: utf-8 -*-
"""Appium POC 入口：「红包入口 → 打开发送面板」用 Appium 按 resource-id 下钻。

前提：设备处于「直播间」且屏幕上有发红包/红包入口（有效会话，由用户手动拉回房间）。

用法:
    python -m tools.appium.poc --device emulator-5554 [--dry]
    --dry   只建会话 + dump 当前可见 resource-id，不点击（用于进场前后自检）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.android.client import ADBClient          # 设备控制 + 证据采集
from tools.appium.higo_ui import AppiumController

# 发控制流程关键 resource-id（依据实测 id 前缀 com.example.live:id/）
RED_SEND_IDS = [
    # 红包/礼物入口（发控制触发按钮）候选
    "iv_gift", "fl_gift", "rv_live_toolbar", "ll_more_tools",
    "rl_red_packet", "tv_red_packet", "iv_red_packet", "fl_anchor_tools",
    # 发送面板元素
    "btn_send", "tv_send", "et_count", "et_coin", "btn_confirm",
]
RED_KW = ("red", "packet", "红包", "gift", "礼物", "send", "发送", "coin", "金币")


def _match_ids(ids: list[str]) -> dict[str, list[str]]:
    hits = {"入口": [], "面板": []}
    for i in ids:
        low = i.lower()
        # 红包/礼物入口：带 red/packet/红包/gift/礼物 且是工具栏/图标类
        if any(k in low for k in ("red", "packet", "红包", "gift", "礼物")):
            hits["入口"].append(i)
        elif any(k in low for k in ("send", "发送", "coin", "金币", "btn_confirm")):
            hits["面板"].append(i)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--device", default="emulator-5554")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--log", default="output/logs/appium/server.log")
    a = ap.parse_args()

    Path("output/logs/appium").mkdir(parents=True, exist_ok=True)
    Path("output/evidence_appium").mkdir(parents=True, exist_ok=True)
    adb = ADBClient(a.device)
    ctl = AppiumController(device_serial=a.device)
    try:
        ctl.start_server(log_path=a.log)
        print(f"[server] Appium up on 4723")
        ctl.start_session()
        print(f"[session] UiAutomator2 已连接 {a.device}，App={ctl.app_package}")
        time.sleep(1)

        ids = ctl.visible_ids()
        print(f"[dump] 当前可见 resource-id: {len(ids)} 个")
        matched = _match_ids(ids)
        for k, v in matched.items():
            print(f"  · {k}: {v}")

        # 采证：ADB 截图 + 页面源（Appium 只管 UI，证据走 ADB / page_source 存档）
        src = ctl.page_source()
        (Path("output/evidence_appium") / "source.xml").write_text(src, encoding="utf-8")
        adb.screenshot("output/evidence_appium/entry_screen.png")
        print("[evidence] source.xml + entry_screen.png 已落盘 output/evidence_appium/")

        if a.dry:
            print("[dry] 仅自检，未点击")
            return 0

        # 真正的 POC 下钻：找入口 -> 点击 -> 验证面板出现
        entry = None
        for grp in (matched["入口"], ids):
            for i in grp:
                if any(k in i.lower() for k in ("red", "packet", "红包", "gift", "礼物")):
                    entry = i
                    break
            if entry:
                break
        if not entry:
            print("[poc] 未发现红包/礼物入口 id，无法下钻（请在直播间且面板弹出后重试）")
            return 2

        print(f"[poc] 点击入口 {entry}")
        ctl.tap(entry)
        time.sleep(2)
        after_ids = ctl.visible_ids()
        panel_keys = [i for i in after_ids if any(k in i.lower()
                       for k in ("send", "发送", "coin", "金币", "confirm"))]
        ok = bool(panel_keys) or bool(matched["面板"])
        (Path("output/evidence_appium") / "after_source.xml").write_text(
            ctl.page_source(), encoding="utf-8")
        adb.screenshot("output/evidence_appium/after_panel.png")
        print(f"[poc] 面板元素: {panel_keys}")
        print("[poc] 面板校验:", "通过 — 发送面板已打开" if ok else "未命中发送面板特征")
        return 0 if ok else 1
    finally:
        ctl.close_session()
        ctl.stop_server()
        adb  # noqa


if __name__ == "__main__":
    raise SystemExit(main())