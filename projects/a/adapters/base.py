# -*- coding: utf-8 -*-
"""AAdapter — A 项目（TopGame）登录注册业务适配器。

Core 只通过 execute_action / get_state / collect_evidence 驱动它；
「什么叫 A 项目注册」只存在于本层与 projects/a/adapters 内。
"""
from __future__ import annotations

from pathlib import Path

from core.adapters.base import TTestAdapter, ActionResult
from core.config import loader

from projects.a.adapters import register_attack

ACTIONS = ["register_by_captcha", "login_by_captcha", "get_captcha", "register_attack",
           "gift_effect_stress"]


class AAdapter(TTestAdapter):
    name = "a"
    description = "A 项目登录注册适配器"
    actions = ACTIONS

    def execute_action(self, action: str, params: dict | None = None) -> ActionResult:
        params = {**(self.params or {}), **(params or {})}
        evd = params.get("evidence_dir") or self.evidence_dir or None
        assets = loader.load_project(self.project).assets
        capture_dir = assets.get("whistle_dir", "D:/higo-api")

        if action == "register_attack":
            rc, summary = register_attack.run(
                capture_dir, self.env_cfg, evd,
                concurrency=int(params.get("concurrency", 10)),
                phone=str(params.get("phone", "66002")))
            return ActionResult(action=action, ok=(rc == 0),
                                status=summary.get("status", "PASS" if rc == 0 else "FAIL"),
                                summary=summary)

        if action == "gift_effect_stress":
            from projects.a.adapters import gift_effect_stress
            rc, summary = gift_effect_stress.run(
                self.env_cfg, evd or "output/evidence_a_crash",
                cycles=int(params.get("cycles", 10)),
                settle_wait=int(params.get("settle_wait", 300)))
            return ActionResult(action=action, ok=(rc == 1),
                                status=summary.get("status", "ERROR"),
                                summary=summary)

        if action in ("register_by_captcha", "login_by_captcha", "get_captcha"):
            # 正常流程回放：复用框架 CaptureReplay（原样字节回放 + 证据四件套）
            from replay.capture_replay import CaptureReplay
            path_key = {"register_by_captcha": "register_path",
                        "login_by_captcha": "login_path",
                        "get_captcha": "captcha_path"}[action]
            path = assets.get(path_key, f"/account/{action}")
            cap = CaptureReplay(capture_dir, evd or "output/evidence_a_replay")
            entries = cap.scan(path, keyword=assets.get("capture_keyword"))
            entry = cap.pick_successful(entries)
            if entry is None:
                return ActionResult(action=action, ok=False, status="ERROR",
                                    error=f"抓包无成功样本: {path}")
            out = cap.run(entry, tc_id=f"A-{action.upper()}-001", title=f"A项目回放 {path}")
            return ActionResult(action=action, ok=out.passed,
                                status="PASS" if out.passed else "FAIL",
                                summary=out.to_dict(), evidence=out.evidence)

        return ActionResult(action=action, ok=False, status="UNKNOWN",
                            error=f"未知业务动作: {action}（支持: {ACTIONS}）")

    def get_state(self) -> dict:
        serial = getattr(self.env_cfg, "device_serial", "") if self.env_cfg else ""
        return {"device": serial or None}

    def collect_evidence(self) -> list[str]:
        root = Path(self.evidence_dir or "output/evidence_a_register")
        if not root.exists():
            return []
        return [str(p) for p in sorted(root.rglob("*")) if p.is_file()]


Adapter = AAdapter
