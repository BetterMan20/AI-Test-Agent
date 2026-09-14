# -*- coding: utf-8 -*-
"""P0 StatefulRandomExecutor —— 状态感知随机。

每个动作前 dump 当前 UI，提取可交互元素(clickable + 有文本/desc)；
若检测到「业务锚点」(红包/礼物/发送等) 则高概率点它，否则在如下动作池随机：
  - 点随机可交互元素 / 点屏幕随机坐标
  - 上下/左右滑动
  - 物理键：BACK / MENU / APP_SWITCH
  - 干扰(攻击预备)：BACKGROUND(HOME) + FOREGROUND(重进) / 快速连点
「随机」不再是瞎点，而是基于当前状态选取的动作（状态感知）。
"""
from __future__ import annotations

import random
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

from tools.android.client import ADBClient

# 业务锚点：命中则权重拉满（红色文字如"gift/礼物/发送/send/red packet/红包/coins"）
ANCHOR_PATS = re.compile(
    r"红包|red ?packet|gift|礼物|send|发送|coins|金币|送礼|送礼物|充值|charge",
    re.IGNORECASE,
)
# 登录敏感元素：冒烟时默认不高频点，避免跑进外部登录授权流卡死
LOGIN_PATS = re.compile(r"login|google|facebook|facebook|手机号|验证码|sign ?.?in", re.IGNORECASE)


class UiNode:
    __slots__ = ("text", "desc", "clickable", "bounds")
    def __init__(self, text: str, desc: str, clickable: bool, bounds: tuple):  # type: ignore[assignment]
        self.text = text; self.desc = desc
        self.clickable = clickable
        self.bounds = bounds  # (x1,y1,x2,y2)

    @property
    def center(self) -> tuple:
        x1, y1, x2, y2 = self.bounds
        return (int((x1 + x2) / 2), int((y1 + y2) / 2))

    @property
    def label(self) -> str:
        return (self.text or self.desc or "").strip()


class StateAwareActor:
    def __init__(self, device_serial: str = "", width: int = 1080, height: int = 1920,
                 avoid_login: bool = True, anchor_bias: float = 0.9) -> None:
        self._client = ADBClient(device_serial)
        self.w, self.h = width, height
        self.avoid_login = avoid_login
        self.anchor_bias = anchor_bias
        self._curnodes: list[UiNode] = []

    # ── 状态感知：dump 当前可交互元素 ────────────────────
    def dump_nodes(self) -> list[UiNode]:
        self._curnodes = []
        xml = self._dump_ui()
        if not xml:
            return []
        try:
            root = ET.fromstring(xml)
        except Exception:
            return []
        for el in root.iter("node"):
            a = el.attrib
            if a.get("clickable") != "true":
                continue
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", a.get("bounds", ""))
            if not m:
                continue
            node = UiNode(
                text=a.get("text", ""),
                desc=a.get("content-desc", ""),
                clickable=True,
                bounds=(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))),
            )
            if node.label:
                self._curnodes.append(node)
        return self._curnodes

    def _dump_ui(self) -> str:
        dump_file = "/sdcard/_st_uidump.xml"
        for _ in range(3):
            try:
                self._client.shell(f"uiautomator dump {dump_file} >/dev/null 2>&1")
                out = self._client.shell(f"cat {dump_file} 2>/dev/null")
                if out and "<hierarchy" in out:
                    return out
            except Exception:
                pass
            time.sleep(0.6)
        return ""

    # ── 动作选择（状态感知）─────────────────────────────
    def choose(self) -> tuple[str, dict[str, Any]]:
        nodes = self.dump_nodes()
        if not nodes:
            return self._raw_move()

        anchor = [n for n in nodes if n.clickable and ANCHOR_PATS.search(n.label)]
        eligible = [n for n in nodes if not (self.avoid_login and LOGIN_PATS.search(n.label))]
        if not eligible:
            eligible = nodes

        # 命中业务锚点 → 高概率专门点击
        if anchor and random.random() < self.anchor_bias:
            n = random.choice(anchor)
            return "TAP", {"coords": list(n.center), "text": n.label[:20], "anchor": True}

        roll = random.random()
        if eligible and roll < 0.62:
            n = random.choice(eligible)
            kb = n.label
            return "TAP", {"coords": list(n.center), "text": kb[:20], "widget": n.desc[:16]}
        if roll < 0.80:
            return self._swipe()
        if roll < 0.90:
            return "KEY", {"key": random.choice(["BACK", "MENU", "APP_SWITCH"])}
        if roll < 0.96:
            return "BACKGROUND", {"key": "HOME", "note": "切后台(攻击预备)"}
        # 干扰：快速连点同一点（连击）
        n = random.choice(eligible or nodes)
        c = n.center
        return "BURST_TAP", {"coords": [c[0], c[1]], "note": "快速连点攻击"}

    def _swipe(self) -> tuple[str, dict[str, Any]]:
        start = (random.randint(120, self.w - 120), random.randint(200, self.h - 200))
        dx = random.choice([-1, 1]) * random.randint(150, 500)
        dy = random.choice([-1, 1]) * random.randint(150, 500)
        return "SWIPE", {"start": start, "end": (start[0] + dx, start[1] + dy)}

    def _raw_move(self) -> tuple[str, dict[str, Any]]:
        return self._swipe()

    # ── 执行 ─────────────────────────────────────────
    def act(self, action: tuple[str, dict]) -> str:
        kind, params = action
        if kind == "TAP":
            x, y = params["coords"]
            self._client.shell(f"input tap {x} {y}; sleep 0.6")
        elif kind == "BURST_TAP":
            x, y = params["coords"]
            self._client.shell(f"input tap {x} {y}; input tap {x} {y}; input tap {x} {y}; sleep 0.6")
        elif kind == "SWIPE":
            s, e = params["start"], params["end"]
            self._client.shell(f"input swipe {s[0]} {s[1]} {e[0]} {e[1]} 200; sleep 0.5")
        elif kind == "KEY":
            keymap = {"BACK": "4", "MENU": "82", "APP_SWITCH": "187"}
            self._client.shell(f"input keyevent {keymap.get(params['key'], '4')}; sleep 0.5")
        elif kind == "BACKGROUND":
            # 切到桌面再回前台（模拟切后台/恢复）
            self._client.shell("input keyevent 3; sleep 1.2")
            self._client.shell("am start -n com.example.live/com.global.hiyapro.ui.SplashActivity; sleep 1.5")
        return "ok"