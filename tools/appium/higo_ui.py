# -*- coding: utf-8 -*-
"""Appium UI 控制器 — 负责任何 UI **业务操作**；设备控制/证据采集仍走 ADB。

定位策略（依据真机 uiautomator dump 实测）：
  · Higo 66% 节点带非空 resource-id → 优先 `By.ID`（稳定）；content-desc(5)、text(29) 覆盖低，仅作兜底。
  · Appium(UiAutomator2) 与 ADB `uiautomator dump` 读同一份树，因此这里只暴露资源级定位，
    不再像旧 ADB 用例那样做「关键词打分 + 坐标 tap」。

与 ADB 分工：
  · 本类：start session → find → tap/swipe/input（UI 业务操作）
  · tools.android.client.ADBClient：shell / screenshot / logcat / pull（设备控制 + 证据采集）
"""
from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from appium import webdriver as appium_webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy

from execution.exceptions import ToolError

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_APPIUM_MAIN = (_PROJECT_ROOT / "tools" / "appium" / "node_modules" / "appium"
                / "build" / "lib" / "main.js")
_APPIUM_HOME = _PROJECT_ROOT / "tools" / "appium" / ".appium"
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 4723

APP_PACKAGE = "com.example.live"   # 实测 resolve-activity 得到


class AppiumController:
    """封装 Appium server 生命周期 + UiAutomator2 会话 + 资源级 UI 操作。"""

    def __init__(
        self,
        device_serial: str = "emulator-5554",
        host: str = _DEFAULT_HOST,
        port: int = _DEFAULT_PORT,
        app_package: str = APP_PACKAGE,
        no_reset: bool = True,
    ):
        self.device_serial = device_serial
        self.host = host
        self.port = port
        self.app_package = app_package
        self.no_reset = no_reset
        self.driver: Any | None = None
        self._server_proc: subprocess.Popen | None = None

    # ── server 生命周期 ──────────────────────────────

    @classmethod
    def server_up(cls, port: int = _DEFAULT_PORT) -> bool:
        try:
            with socket.create_connection((_DEFAULT_HOST, port), timeout=1):
                return True
        except OSError:
            return False

    def start_server(self, log_path: str | None = None) -> None:
        """项目内启动 Appium server（APPIUM_HOME 指向本项目，驱动已装在其下）。"""
        if self.server_up(self.port):
            return
        if not _APPIUM_MAIN.exists():
            raise ToolError("appium", f"appium main.js 不存在: {_APPIUM_MAIN}")
        env = dict(os.environ)
        env["APPIUM_HOME"] = str(_APPIUM_HOME)
        out = open(log_path, "w", encoding="utf-8") if log_path else subprocess.DEVNULL
        self._server_proc = subprocess.Popen(
            ["node", str(_APPIUM_MAIN), "--port", str(self.port)],
            cwd=str(_PROJECT_ROOT), env=env, stdout=out, stderr=subprocess.STDOUT,
        )
        # 等待服务就绪
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.server_up(self.port):
                return
            time.sleep(0.5)
        raise ToolError("appium", f"Appium server 起不来 (port {self.port})，日志: {log_path}")

    def stop_server(self) -> None:
        if self._server_proc:
            self._server_proc.terminate()
            self._server_proc = None

    # ── 会话 ─────────────────────────────────────────

    def start_session(self, app_activity: str | None = None) -> None:
        """建立 UiAutomator2 会话。no_reset=True 保留已登录/所在直播间状态。

        app_activity=None 时附加到当前前台 App（不强制重开）。
        """
        caps: dict[str, Any] = {
            "platformName": "Android",
            "automationName": "UiAutomator2",
            "udid": self.device_serial,
            "appPackage": self.app_package,
            "noReset": self.no_reset,
            "newCommandTimeout": 300,
            "uiautomator2ServerInstallTimeout": 60000,
            "shouldTerminateBackgroundProcesses": False,
        }
        if app_activity:
            caps["appActivity"] = app_activity
        options = UiAutomator2Options()
        options.load_capabilities(caps)
        self.driver = appium_webdriver.Remote(
            f"http://{self.host}:{self.port}", options=options)

    def close_session(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    # ── 资源级定位（By.ID 优先，稳）──────────────

    def find(self, rid: str, timeout: float = 10):
        """按 resource-id 找元素（含包名前缀自动补全）。"""
        key = rid if ":" in rid else f"{self.app_package}:id/{rid}"
        return self.driver.find_element(AppiumBy.ID, key)

    def find_text(self, text: str, timeout: float = 10):
        return self.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR,
                                        f'new UiSelector().text("{text}")')

    def find_desc(self, desc: str, timeout: float = 10):
        return self.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR,
                                        f'new UiSelector().description("{desc}")')

    def wait(self, rid: str, timeout: float = 10):
        self.driver.implicitly_wait(timeout)
        el = self.find(rid)
        return el

    def tap(self, rid: str, timeout: float = 10):
        self.wait(rid, timeout).click()

    def tap_point(self, x: int, y: int) -> None:
        """坐标兜底（仅当无稳定定位符时）。"""
        self.driver.tap([(x, y)])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, dur_ms: int = 300):
        self.driver.swipe(x1, y1, x2, y2, dur_ms)

    def input_text(self, rid: str, text: str):
        self.wait(rid).send_keys(text)

    def back(self) -> None:
        self.driver.press_keycode(4)  # KEYCODE_BACK

    # ── 证据/诊断（仍走 Appium 的 page_source，贴近同层快照）──

    def page_source(self) -> str:
        if not self.driver:
            return ""
        try:
            return self.driver.page_source or ""
        except Exception:
            return ""

    def visible_ids(self) -> list[str]:
        src = self.page_source()
        import re
        ids = sorted({x for x in re.findall(r'resource-id="([^"]*)"', src)
                      if x.startswith(self.app_package) and ":id/" in x})
        return ids

    # ── 关键词驱动业务下钻（保持 Core 通用，业务关键词由计划配置注入）──

    def tap_by_keyword(self, keyword: str, timeout: float = 10) -> bool:
        """在当前页面扫描 resource-id / text / content-desc，命中关键词即点击。

        返回是否成功点击；未命中返回 False（不抛错，交由断言层判定）。
        """
        import re

        if self.driver is None:
            return False
        src = self.page_source()
        if not src:
            return False

        pat = re.compile(keyword, re.IGNORECASE)
        # 属性顺序无关解析：先取每个 <node> 块，再从中分别抽 rid/text/desc
        # （不同 App 的 uiautomator 属性顺序不固定，如 text→desc→rid，固定顺序正则会漏）
        node_blocks = re.findall(r"<node\b[^>]*?/?>", src)
        nodes = []
        for blk in node_blocks:
            rid = re.search(r'resource-id="([^"]*)"', blk)
            text = re.search(r'\btext="([^"]*)"', blk)
            desc = re.search(r'content-desc="([^"]*)"', blk)
            nodes.append((
                rid.group(1) if rid else "",
                text.group(1) if text else "",
                desc.group(1) if desc else "",
            ))

        def hit(n) -> str | None:
            for c, grp in zip(n, ("1", "2", "3")):
                if c and pat.search(c):
                    return grp
            return None

        # 按“命中的属性”优先级尝试：先 resource-id(1) 稳定，再 text(2) / desc(3)
        for attr_pri in ("1", "2", "3"):
            for n in nodes:
                if hit(n) != attr_pri:
                    continue
                rid = n[0]
                try:
                    if rid and ":" not in rid:
                        rid = f"{self.app_package}:id/{rid}"
                    el = self.driver.find_element(AppiumBy.ID, rid) if rid else None
                    if el is None:
                        continue
                    el.click()
                    return True
                except Exception:
                    continue
        # 兜底：按 text 命中的节点用 UiSelector text 定位（无 resource-id 时）
        for n in nodes:
            if hit(n) != "2":
                continue
            try:
                el = self.driver.find_element(
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    f'new UiSelector().text("{n[1]}")',
                )
                el.click()
                return True
            except Exception:
                continue
        return False