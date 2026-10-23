# -*- coding: utf-8 -*-
"""语音房 P0 真机 UI 自动化（Appium 优先，ADB 兜底）。

按 xmind《语音房（p0）》用例做真机下钻，不是 API 回放：
  登录(密码) → 进语音房 → 加入(无限制/密码分支) → 送礼(普通/幸运/盲盒) → 断言公屏/扣费。

每一步都落证据（page_source + screenshot + action 记录），可复核可追溯。
资源级定位优先 resource-id，无 rid 用 text/desc，坐标仅兜底。

用法（库）：
    from projects.higo.adapters.voice_room import VoiceRoomFlow
    with VoiceRoomFlow.from_config() as flow:
        flow.ensure_login()
        flow.enter_voice_room()
        flow.send_gift(category="普通礼物")

用法（CLI）：
    python -m projects.higo.adapters.voice_room --probe          # 只探查当前页控件
    python -m projects.higo.adapters.voice_room --login          # 跑登录
    python -m projects.higo.adapters.voice_room --full           # 登录→进房→送礼 全链路
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools.appium.higo_ui import AppiumController

_CFG = _PROJECT_ROOT / "testdata" / "higo" / "voice_room.yaml"
_AUTH = _PROJECT_ROOT / "testdata" / "higo" / "voice_room.auth.yaml"
_EVIDENCE_ROOT = _PROJECT_ROOT / "output" / "evidence_voice_room"


def _load_yaml(p: Path) -> dict:
    import yaml  # type: ignore
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


class VoiceRoomFlow:
    """语音房真机业务流程封装：每个方法=一个真机操作步骤，落证据。"""

    def __init__(self, serial: str, package: str, cfg: dict, auth: dict,
                 evidence_dir: Path | None = None):
        self.serial = serial
        self.package = package
        self.cfg = cfg
        self.auth = auth
        self.evidence_dir = evidence_dir or _EVIDENCE_ROOT
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.ctl = AppiumController(device_serial=serial, app_package=package)
        self.step_log: list[dict[str, Any]] = []
        self._step_no = 0

    @classmethod
    def from_config(cls, evidence_dir: Path | None = None) -> "VoiceRoomFlow":
        cfg = _load_yaml(_CFG)
        auth = _load_yaml(_AUTH) if _AUTH.exists() else {}
        return cls(cfg.get("device_serial", "emulator-5554"),
                   cfg.get("package", "com.example.live"), cfg, auth, evidence_dir)

    # ── 生命周期 ──────────────────────────────────────
    def __enter__(self):
        if not AppiumController.server_up():
            self.ctl.start_server()
        self.ctl.start_session()
        return self

    def __exit__(self, *exc):
        self.ctl.close_session()
        self.ctl.stop_server()
        self._flush_log()

    # ── 证据采集 ──────────────────────────────────────
    def _snap(self, name: str, action: str, extra: dict | None = None):
        """每步落证据：page_source.xml + screenshot.png + action 记录。"""
        self._step_no += 1
        safe = re.sub(r"[^\w一-龥-]", "_", name)
        tag = f"{self._step_no:02d}_{safe}"
        d = self.evidence_dir / tag
        d.mkdir(parents=True, exist_ok=True)
        ps = self.ctl.page_source()
        (d / "page_source.xml").write_text(ps or "", encoding="utf-8")
        try:
            self.ctl.driver.save_screenshot(str(d / "screenshot.png"))
        except Exception:
            pass
        rec = {"step": self._step_no, "name": name, "action": action,
               "ts": time.strftime("%H:%M:%S"), "evidence": str(d), **(extra or {})}
        self.step_log.append(rec)
        return rec

    def _flush_log(self):
        (self.evidence_dir / "flow_log.json").write_text(
            json.dumps(self.step_log, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 定位工具（关键词优先 rid>text>desc，坐标兜底）──
    def _tap_kw(self, keywords: list[str], timeout: float = 8) -> bool:
        """按一组关键词顺序尝试点击；任一命中即返回 True。"""
        for kw in keywords:
            try:
                if self.ctl.tap_by_keyword(kw, timeout=timeout):
                    return True
            except Exception:
                continue
        return False

    def _page_has(self, keywords: list[str]) -> bool:
        src = (self.ctl.page_source() or "").lower()
        return any(k.lower() in src for k in keywords)

    def _input_by_kw(self, keywords: list[str], text: str) -> bool:
        """找输入框并输入：rid 含 et_/edit/input 或 text/desc 命中关键词（属性顺序无关解析）。"""
        src = self.ctl.page_source() or ""
        # 收集所有 EditText 节点的 rid/text/desc
        edits = []
        for blk in re.findall(r"<node\b[^>]*?/?>", src):
            if "EditText" not in blk:
                continue
            rid = re.search(r'resource-id="([^"]*)"', blk)
            txt = re.search(r'\btext="([^"]*)"', blk)
            desc = re.search(r'content-desc="([^"]*)"', blk)
            edits.append((rid.group(1) if rid else "",
                          txt.group(1) if txt else "", desc.group(1) if desc else ""))
        for kw in keywords:
            pat = re.compile(re.escape(kw), re.IGNORECASE)
            for rid, txt, desc in edits:
                if not (pat.search(rid) or pat.search(txt) or pat.search(desc)):
                    continue
                if not rid:
                    continue
                try:
                    el = self.ctl.driver.find_element("id", rid)
                    el.clear()
                    el.send_keys(text)
                    return True
                except Exception:
                    continue
        return False

    # ══ 业务步骤 ═════════════════════════════════════
    def is_logged_in(self) -> bool:
        """已登录判定：当前页无登录入口特征（Google/FB/phone 登录按钮）。"""
        src = self.ctl.page_source() or ""
        # 登录首页特征：出现第三方/手机登录按钮即未登录（不用 LoginActivity 子串，避免误判）
        return not any(k in src for k in ("fl_login_google", "fl_login_fb", "iv_login_phone"))

    def ensure_login(self) -> dict:
        """确保已登录；未登录则走：登录首页→手机登录入口→密码登录。"""
        if self.is_logged_in():
            return self._snap("已登录", "skip", {"logged": True})
        # 拉起 App 到登录页
        self.ctl.driver.activate_app(self.package)
        time.sleep(3)
        if self.is_logged_in():
            return self._snap("已登录", "skip", {"logged": True})
        account, password = self.auth.get("account", ""), self.auth.get("password", "")
        if not account or not password or password.startswith("TODO"):
            self._snap("登录", "abort", {"reason": "账号/密码未配置", "hint": f"请填 {_AUTH.name}"})
            raise RuntimeError("测试账号未配置：请填 testdata/higo/voice_room.auth.yaml")
        # 步骤1：登录首页 → 点"手机登录"入口进二级页
        self._tap_kw(["iv_login_phone"], timeout=6)
        time.sleep(2)
        self._snap("手机登录页", "goto_phone_login")
        # 步骤2：输账号 → 切密码登录 → 输密码 → 提交
        ok = True
        ok &= self._input_by_kw(["et_email", "email", "手机", "phone"], account)
        self._tap_kw(["tv_password", "Password Login", "密码登录"], timeout=3)
        time.sleep(1)
        ok &= self._input_by_kw(["et_password1", "password", "密码"], password)
        self._snap("已填账号密码", "fill_credentials", {"filled": ok})
        ok &= self._tap_kw(["tv_login_next", "Log in", "登录", "Go On"])
        time.sleep(5)
        logged = self.is_logged_in()
        return self._snap("密码登录", "login", {"ok": logged and ok, "input_ok": ok})

    def enter_voice_room(self) -> dict:
        """从首页/大厅进入语音房。返回步骤记录（含是否在房间内）。"""
        self._tap_kw(self.cfg["entry"]["voice_room_tab_keywords"])
        time.sleep(3)
        in_room = self._in_voice_room()
        if not in_room:
            # 点第一个房间卡片
            self._tap_kw(self.cfg["entry"]["room_card_keywords"], timeout=5)
            time.sleep(3)
            in_room = self._in_voice_room()
        return self._snap("进入语音房", "enter", {"in_room": in_room})

    def _in_voice_room(self) -> bool:
        """在语音房内判定：出现麦位/公屏/送礼入口特征。"""
        src = (self.ctl.page_source() or "").lower()
        return any(k in src.lower() for k in
                   self.cfg["gift"]["gift_entry_keywords"] + ["麦", "mic", "seat", "公屏", "chat"])

    def join_with_password(self, password: str | None = None) -> dict:
        """加入密码房：检测到密码框则输入密码。返回分支命中记录。"""
        pwd = password or self.auth.get("room_password", "")
        src = self.ctl.page_source() or ""
        has_pwd_box = bool(re.search(r'(密码|password|pwd)', src, re.I)) and "EditText" in src
        if not has_pwd_box:
            return self._snap("加入语音房", "join", {"branch": "无密码直接进入"})
        ok = self._input_by_kw(["password", "密码", "pwd"], pwd)
        self._tap_kw(["确定", "Confirm", "进入", "Join", "OK"], timeout=4)
        time.sleep(2)
        joined = self._in_voice_room()
        return self._snap("加入语音房(密码)", "join_pwd", {"input_ok": ok, "joined": joined})

    def send_gift(self, category: str = "普通礼物", times: int = 1) -> dict:
        """送礼：打开礼物面板 → 选分类 → 选第一个礼物 → 赠送 times 次 → 断言。"""
        opened = self._tap_kw(self.cfg["gift"]["gift_entry_keywords"])
        time.sleep(2)
        rec = self._snap("打开礼物面板", "open_gift_panel", {"opened": opened})
        if not opened:
            return rec
        # 选分类 tab
        tab_kw = self.cfg["gift"]["tabs"].get(category, [])
        if tab_kw:
            self._tap_kw(tab_kw, timeout=4)
            time.sleep(1)
            self._snap(f"切分类[{category}]", "select_tab")
        # 记录送前金币（用于扣费断言）
        before = self._read_coin()
        # 选礼物 + 赠送
        for i in range(times):
            self._tap_kw(self.cfg["gift"]["send_button_keywords"], timeout=5)
            time.sleep(1.5)
        after = self._read_coin()
        # 断言：公屏出现送礼特征 或 金币减少
        public_ok = self._page_has(self.cfg["assert"]["public_screen_keywords"])
        deduct_ok = (before is not None and after is not None and after < before)
        return self._snap(f"送礼[{category}]x{times}", "send_gift",
                          {"before_coin": before, "after_coin": after,
                           "public_screen": public_ok, "deduct": deduct_ok,
                           "passed": bool(public_ok or deduct_ok)})

    def _read_coin(self) -> int | None:
        """尽力从页面读金币余额（用于扣费断言）；读不到返回 None。"""
        src = self.ctl.page_source() or ""
        for kw in self.cfg["assert"]["deduct_keywords"]:
            m = re.search(re.escape(kw) + r'[^\d]{0,6}(\d{2,9})', src, re.I)
            if m:
                return int(m.group(1))
        return None

    def probe(self) -> dict:
        """只探查当前页控件（不操作），列出可交互元素与命中关键词。"""
        src = self.ctl.page_source() or ""
        ids = sorted(set(re.findall(r'resource-id="([^"]+)"', src)))
        texts = sorted(set(t for t in re.findall(r'text="([^"]{1,20})"', src) if t.strip()))
        return self._snap("探查", "probe", {
            "activity": self.ctl.driver.current_activity if self.ctl.driver else None,
            "ids": ids[:60], "texts": texts[:60]})


def main() -> int:
    ap = argparse.ArgumentParser(description="语音房 P0 真机 UI 自动化")
    ap.add_argument("--probe", action="store_true", help="只探查当前页")
    ap.add_argument("--login", action="store_true", help="跑登录")
    ap.add_argument("--room", action="store_true", help="进语音房")
    ap.add_argument("--gift", default="", help="送礼分类（普通礼物/幸运礼物/盲盒）")
    ap.add_argument("--full", action="store_true", help="登录→进房→送礼 全链路")
    args = ap.parse_args()

    with VoiceRoomFlow.from_config() as flow:
        try:
            if args.probe:
                out = flow.probe()
                print(json.dumps(out, ensure_ascii=False, indent=2))
                return 0
            if args.full or args.login:
                print(json.dumps(flow.ensure_login(), ensure_ascii=False))
            if args.full or args.room:
                print(json.dumps(flow.enter_voice_room(), ensure_ascii=False))
                print(json.dumps(flow.join_with_password(), ensure_ascii=False))
            if args.gift:
                print(json.dumps(flow.send_gift(args.gift), ensure_ascii=False))
            elif args.full:
                print(json.dumps(flow.send_gift("普通礼物"), ensure_ascii=False))
        except RuntimeError as e:
            print("ABORT:", e)
            return 2
    print("\n证据:", _EVIDENCE_ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
