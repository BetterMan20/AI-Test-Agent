# -*- coding: utf-8 -*-
"""projects.higo.adapters.qa_driver — 把红包装把业务接到全景 QA 循环。

业务差异（怎么探测真机、怎么读状态、怎么回填 KB）都留在这层；
core.qa.cycle 只调用 QADriver 接口，保持 core 不含业务逻辑。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.qa.cycle import QADriver, CycleContext, OBSERVATION
from core.config.loader import load_env

from projects.higo.adapters import discover as D
from projects.higo.adapters import claim_attack as CA


class HigoRedPacketDriver(QADriver):
    """红包装把业务的 QA 驱动。"""

    def __init__(self, serial: str | None = None, *, live: bool = True):
        self.serial = serial
        self.live = live

    # 认识：真机探索 + 历史证据回填，产出系统事实
    def recognize_facts(self, ctx: CycleContext) -> list[dict]:
        D.run_discovery(ctx.project, ctx.env, kb_base=ctx.kb_base,
                        live=self.live, backfill_evidence=None,
                        room=ctx.room, max_depth=5)
        # 历史复现证据也并入同一知识库（长期积累）
        hist_ev = Path("output") / "evidence" / "higo-repro-bug"
        if hist_ev.exists():
            D.run_discovery(ctx.project, ctx.env, kb_base=ctx.kb_base,
                            live=False,
                            backfill_evidence=str(hist_ev),
                            room=ctx.room, max_depth=5)
        tree = ctx.kb.to_tree()
        facts = [{"type": "SYSTEM_FACT", "content": "App 知识库已发现: "
                  + (tree.splitlines()[0] if tree else "empty")}]
        facts += [{"type": "SYSTEM_FACT", "content": "KB 根节点落库，路径="
                   + ctx.kb_base}]
        return facts

    # 观测：真机 overlay 状态 +（若有证据）历史复现结论
    def observe(self, ctx: CycleContext) -> list[OBSERVATION]:
        obs: list[OBSERVATION] = []
        # ① 证据观测（确定性可复现）
        rp = Path("output") / "evidence" / "higo-repro-bug" / "reproduce_report.json"
        if rp.exists():
            try:
                r = json.loads(rp.read_text(encoding="utf-8"))
                cv = r.get("consistency_verdict", {})
                # server_time/open_at 为触发条件代入值（status=3 WAITING 需 server_time<open_at），
                # 用于驱动 check_consistency 判定；非真机实测毫秒数。
                obs.append({
                    "label": "history:reproduce-14775(WAITING@未开领)",
                    "status": 3,
                    "server_time": 0, "open_at": 86400000, "ttl": None,
                    "observed_ui": cv.get("observed_ui") or "OPEN",
                    "expected_ui": cv.get("expected_ui"),
                    "phase": cv.get("phase") or "WAITING",
                    "note": "代入值: server_time<open_at 触发 WAITING 判定口径",
                })
            except Exception:
                pass
        # ② 真机实时 overlay（若可观测）
        if self.live:
            ui = self._live_ui_state()
            if ui:
                obs.append({"label": f"live:{self.serial or 'device'}",
                            "status": None, "server_time": None, "open_at": None,
                            "observed_ui": ui, "expected_ui": None, "phase": None})
        return obs

    # B: 本业务真实可执行的原语清单（执行能力上限；不给 LLM 超出清单的幻想）
    def reachable_primitives(self, ctx: CycleContext) -> list[dict]:
        return [
            {"id": "open_red_packet", "desc": "点击红包入口打开弹窗",
             "precondition": "屏幕存在未处理红包入口"},
            {"id": "dump_ui_state", "desc": "dump UI 并识别红包入口/弹窗 ui_state",
             "precondition": "红包入口或弹窗可见"},
            {"id": "close_red_packet", "desc": "关闭红包弹窗返回",
             "precondition": "红包弹窗已打开"},
            {"id": "refresh_red_packet_state", "desc": "重开红包/再读一次状态以观测刷新",
             "precondition": "红包入口可见"},
        ]

    # B: 真机执行决策给的原语序列，尽力而为；不可达则诚实返回 executed=False
    def execute(self, ctx: CycleContext, primitives: list[str]) -> dict:
        if not self.live:
            return {"executed": False,
                    "reason": "证据模式(--live 未开)不执行真机原语，仅由 driver.observe 读证据",
                    "observations": []}
        serial = self._ensure_serial()
        if not serial:
            return {"executed": False, "reason": "无可用设备", "observations": []}
        try:
            disc = D.HigoRedPacketDiscoverer(serial)
            # 前置：屏幕须能识别到红包入口（overlay 信号），否则不假点击、诚实返回不可达
            probe = disc.probe_screen("qa-cycle:exec")
            entry_ui = probe.get("extra", {}).get("ui_state")
            if not entry_ui:
                return {"executed": False,
                        "reason": f"前置条件不满足: 屏幕无红包入口 (prims={primitives})",
                        "observations": []}
            observations: list[OBSERVATION] = []
            for prim in primitives:
                if prim == "open_red_packet":
                    CA._open_red_packet(serial, idx=1)
                elif prim in ("dump_ui_state", "refresh_red_packet_state"):
                    xml = CA._dump_ui(serial)
                    ui = CA._ui_state_from_xml(xml)
                    observations.append({"label": f"exec:{prim}",
                                         "status": None, "server_time": None,
                                         "open_at": None, "observed_ui": ui,
                                         "expected_ui": None, "phase": None})
                elif prim == "close_red_packet":
                    CA._adb(serial, "input keyevent 4")
                else:
                    return {"executed": False,
                            "reason": f"未知/未实现原语: {prim}", "observations": []}
            return {"executed": True, "reason": "ok", "observations": observations}
        except Exception as e:
            return {"executed": False, "reason": f"执行异常: {e}", "observations": []}

    def _ensure_serial(self) -> str | None:
        if self.serial:
            return self.serial
        try:
            cfg = load_env("higo", "test")
            self.serial = cfg.device_serial
            return self.serial
        except Exception:
            return None

    def _live_ui_state(self) -> str | None:
        serial = self._ensure_serial()
        if not serial:
            return None
        try:
            disc = D.HigoRedPacketDiscoverer(serial)
            probe = disc.probe_screen("qa-cycle:attack")
            return probe.get("extra", {}).get("ui_state")
        except Exception:
            return None

    # 学习：观测回填 KB（claim_attack 同一条累积管道）
    def backfill(self, ctx: CycleContext, observations: list[OBSERVATION]) -> list[str]:
        return D.backfill_observations(ctx.kb, observations, room=ctx.room,
                                       source="qa-cycle:learn")


def build_driver(serial: str | None = None, *, live: bool = True) -> HigoRedPacketDriver:
    return HigoRedPacketDriver(serial=serial, live=live)