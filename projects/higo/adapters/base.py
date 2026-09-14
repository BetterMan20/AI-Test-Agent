# -*- coding: utf-8 -*-
"""HigoAdapter — HIGO 直播业务适配器。

Core 只通过 execute_action / get_state / collect_evidence 驱动它；
「什么叫 HIGO 红包」只存在于本层与 projects/higo/adapters 内。
"""
from __future__ import annotations

from pathlib import Path

from core.adapters.base import TTestAdapter, ActionResult
from core.config import loader

from projects.higo.adapters import redpacket, replay

# 该适配器声明的业务动作（app/菜单据此生成入口；换动作不改 Core）
ACTIONS = ["send_red_packet", "send_gift", "enter_voice_room"]


def _adb_dump_state(serial: str) -> str | None:
    """返回当前设备页面 uiautomator dump（尽力而为，失败返回 None）。"""
    import subprocess
    try:
        cmd = (f"adb -s {serial} shell \"uiautomator dump /sdcard/_st.xml "
               f">/dev/null 2>&1; cat /sdcard/_st.xml\"" if serial else
               "adb shell \"uiautomator dump /sdcard/_st.xml >/dev/null 2>&1; cat /sdcard/_st.xml\"")
        rp = subprocess.run(cmd, shell=True, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=15)
        out = rp.stdout or ""
        return out if "<hierarchy" in out else None
    except Exception:
        return None


class HigoAdapter(TTestAdapter):
    name = "higo"
    description = "HIGO 直播业务适配器"
    actions = ACTIONS  # 声明的业务动作清单

    # ── Core 唯一的入口 ───────────────────────────────────
    def execute_action(self, action: str, params: dict | None = None) -> ActionResult:
        params = {**(self.params or {}), **(params or {})}
        evd = params.get("evidence_dir") or self.evidence_dir or None
        if action == "send_red_packet":
            rc, summary = redpacket.run(self.project, self.env_cfg.env, evd)
            return ActionResult(action=action, ok=(rc == 0),
                                status=summary.get("status", "PASS" if rc == 0 else "FAIL"),
                                summary=summary)
        if action == "send_gift":
            return self._run_replay(action, evd)
        if action == "enter_voice_room":
            return self._run_replay(action, evd)
        return ActionResult(action=action, ok=False, status="UNKNOWN",
                            error=f"未知业务动作: {action}（支持: {ACTIONS}）")

    def _run_replay(self, action: str, evd: str | None) -> ActionResult:
        assets = loader.load_project(self.project).assets
        path = str(assets.get({"send_gift": "gift_path", "enter_voice_room": "join_room_path"}[action],
                              f"/live/{action}"))
        rc, summary = replay.replay_endpoint(self.project, self.env_cfg.env, path, action, evd)
        return ActionResult(action=action, ok=(rc == 0),
                            status=summary.get("status", "PASS" if rc == 0 else "FAIL"),
                            summary=summary)

    def get_state(self) -> dict:
        serial = getattr(self.env_cfg, "device_serial", "") if self.env_cfg else ""
        xml = _adb_dump_state(serial)
        return {"device": serial or None,
                "page_has_redpacket_entry": bool(xml and any(
                    k in xml.lower() for k in ("红包", "lucky bag", "luckybag", "redpacket"))),
                "screen_dumped": bool(xml)}

    def collect_evidence(self) -> list[str]:
        root = Path(self.evidence_dir or "output/evidence")
        if not root.exists():
            return []
        return [str(p) for p in sorted(root.rglob("*")) if p.is_file()]


# registry 约定暴露的类名
Adapter = HigoAdapter