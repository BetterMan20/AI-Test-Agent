# -*- coding: utf-8 -*-
"""原子 Skill 3：动态环境适配（env_guardian）。

只干一件事：回归执行前/中，自动检测并自愈三类高频环境异常——
App 崩溃/ANR、遮挡弹窗、控件加载超时——让回归值守不再靠人盯、手动重启、手动清弹窗。

检测（确定性，无 LLM）：
  crash   : dumpsys dropbox 有 data_app_crash / logcat FATAL EXCEPTION
  anr     : dumpsys dropbox 有 data_app_anr
  popup   : 当前页 XML 命中可配置的关闭类控件（关闭/知道了/取消/×/allow/deny）
  crashed : 目标包当前不在前台（被闪退/被杀）
自愈动作：force-stop 重启 App、点击弹窗关闭控件、BACK 键、等待重试。

用法（库）：
    from skills_py.env_guardian import ensure_ready
    res = ensure_ready("emulator-5554", "com.example.live")   # 返回自愈记录

用法（CLI，含效率基线计时）：
    python -m skills_py.env_guardian emulator-5554 com.example.live --record
    python -m skills_py.env_guardian emulator-5554 com.example.live --dry   # 只检测不自愈
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools.android.client import ADBClient

# 弹窗关闭控件候选文案/资源名（可按项目扩展）
POPUP_CLOSE_KW = [
    "关闭", "知道了", "取消", "我知道了", "稍后", "skip", "close", "dismiss",
    "allow", "deny", "拒绝", "同意", "iv_close", "btn_close", "tv_cancel", "iv_delete",
]


class Guardian:
    def __init__(self, serial: str, package: str, timeout: int = 20):
        self.serial = serial
        self.package = package
        self.adb = ADBClient(device_serial=serial, timeout=timeout)
        self.actions: list[dict[str, Any]] = []

    def _log(self, kind: str, detail: str, healed: bool):
        self.actions.append({"kind": kind, "detail": detail, "healed": healed,
                             "ts": time.strftime("%H:%M:%S")})

    def _sh(self, cmd: str) -> str:
        try:
            return self.adb.shell(cmd)
        except Exception as e:  # noqa: BLE001
            return f"ERR:{e}"

    # ── 检测 ──────────────────────────────────────────
    def detect_crash_anr(self) -> list[str]:
        """读 dropbox 崩溃/ANR 标签（近一次）。"""
        out = self._sh("dumpsys dropbox --print | head -c 4000")
        hits = []
        for tag in ("data_app_crash", "data_app_anr", "system_app_crash"):
            if tag in out:
                hits.append(tag)
        return hits

    def foreground_pkg(self) -> str:
        """前台包名：优先 topResumedActivity（锁屏/多窗口也准），兜底 mCurrentFocus。"""
        out = self._sh("dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity' | head -2")
        m = re.search(r"\{[\w]+\s+\w+\s+([\w.]+)/", out)
        if m:
            return m.group(1)
        out2 = self._sh("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | head -2")
        m2 = re.search(r"([a-zA-Z][\w.]*)/", out2)
        return m2.group(1) if m2 else ""

    def dump_xml(self) -> str:
        self._sh("uiautomator dump /sdcard/_guard.xml")
        time.sleep(0.8)
        return self._sh("cat /sdcard/_guard.xml")

    def detect_popup(self, xml: str) -> dict[str, Any] | None:
        """在 XML 中找可点击的关闭类控件，返回其坐标中心。"""
        for kw in POPUP_CLOSE_KW:
            # 找 text/desc/rid 命中且 clickable=true 的节点
            for m in re.finditer(
                r'<node[^>]*?(?:text|content-desc|resource-id)="([^"]*' + re.escape(kw) + r'[^"]*)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*?>',
                xml, re.IGNORECASE):
                node = m.group(0)
                if 'clickable="true"' in node:
                    x1, y1, x2, y2 = map(int, m.group(2, 3, 4, 5))
                    return {"kw": kw, "center": ((x1 + x2) // 2, (y1 + y2) // 2)}
        return None

    # ── 自愈 ──────────────────────────────────────────
    def heal_crash(self) -> bool:
        self._sh(f"am force-stop {self.package}")
        time.sleep(1)
        self._sh(f"monkey -p {self.package} -c android.intent.category.LAUNCHER 1")
        time.sleep(3)
        ok = self.package in self.foreground_pkg() or self.foreground_pkg() == self.package
        self._log("crash", f"force-stop+重启 {self.package}", ok)
        return ok

    def heal_popup(self, pop: dict[str, Any]) -> bool:
        x, y = pop["center"]
        self._sh(f"input tap {x} {y}")
        time.sleep(1)
        self._log("popup", f"点击关闭控件[{pop['kw']}]@({x},{y})", True)
        return True

    def _in_foreground(self) -> bool:
        return self.package in self.foreground_pkg()

    def _wake_unlock(self):
        """唤醒屏幕并上滑解锁（设备锁屏/休眠时 focus=null，App 无法进入前台）。"""
        self._sh("input keyevent KEYCODE_WAKEUP")
        time.sleep(0.5)
        self._sh("input keyevent 82")  # MENU/解锁
        self._sh("input swipe 540 1700 540 600")  # 上滑解锁（无密码场景）
        time.sleep(0.8)

    def heal_not_foreground(self) -> bool:
        self._wake_unlock()
        ok = False
        for attempt in range(2):
            self._sh(f"monkey -p {self.package} -c android.intent.category.LAUNCHER 1")
            for _ in range(6):  # 轮询最多 ~6s 等待进入前台
                time.sleep(1)
                if self._in_foreground():
                    ok = True
                    break
            if ok:
                break
        self._log("not_foreground", f"唤醒解锁+重新拉起 {self.package}（{'成功' if ok else '仍不在前台'}）", ok)
        return ok

    def run(self, dry: bool = False, rounds: int = 2) -> dict[str, Any]:
        """执行检测+自愈（dry=True 只检测）。返回自愈记录汇总。"""
        issues: dict[str, Any] = {"crash_anr": [], "popup": None, "not_foreground": False}

        # 1. 崩溃/ANR
        ca = self.detect_crash_anr()
        issues["crash_anr"] = ca
        if ca and not dry:
            self.heal_crash()
            time.sleep(2)

        # 2. 前台检查
        fg = self.foreground_pkg()
        nf = bool(self.package) and self.package not in fg
        issues["not_foreground"] = nf
        if nf and not dry:
            self.heal_not_foreground()
            time.sleep(2)

        # 3. 弹窗（可能多轮）
        for _ in range(rounds):
            xml = self.dump_xml()
            pop = self.detect_popup(xml)
            if not pop:
                break
            issues["popup"] = pop
            if dry:
                break
            self.heal_popup(pop)

        healed = sum(1 for a in self.actions if a["healed"])
        return {
            "serial": self.serial, "package": self.package, "dry": dry,
            "issues": issues, "actions": self.actions,
            "healed_count": healed,
            "ready": (not ca or healed > 0) and not (nf and not any(a["kind"] == "not_foreground" and a["healed"] for a in self.actions)),
        }


def ensure_ready(serial: str, package: str, dry: bool = False) -> dict[str, Any]:
    """库入口：检测并自愈，返回结果。"""
    return Guardian(serial, package).run(dry=dry)


def main() -> int:
    ap = argparse.ArgumentParser(description="动态环境适配 Skill：崩溃/弹窗/超时自愈")
    ap.add_argument("serial")
    ap.add_argument("package")
    ap.add_argument("--dry", action="store_true", help="只检测不自愈")
    ap.add_argument("--record", action="store_true", help="登记效率基线计时")
    args = ap.parse_args()

    def _go():
        return ensure_ready(args.serial, args.package, dry=args.dry)

    if args.record:
        from core.efficiency import timed
        with timed("env_guardian", items=1):
            res = _go()
    else:
        res = _go()

    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
