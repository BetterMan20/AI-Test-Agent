# -*- coding: utf-8 -*-
"""core.attack.consistency — 历史Bug反推测试·第一类：状态一致性定向攻击。

素材：历史 bug 截图（如「领取弹窗 UI=OPEN 而业务 CLAIM_NOT_STARTED」）。
反推核心不是「再生成几个用例」，而是**专门攻击状态一致性**：

    status × open_at × server_time × ui_state × state_refresh  的一致性

本引擎是项目无关的；它消费一个「定向攻击路径」模型（见 projects/*/attack/*.json），
产出：
  · build_attack_tests():   由触发条件展开为定向攻击测试点
  · check_consistency():    对一次观测 (status, server_time, open_at, observed_ui)
                            计算期望 ui_state，判定是否违反对称/时间一致。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 时间关系机读表：model 中 time_relation 枚举 → 判定函数
_RELATIONS = {
    "server_time<open_at": lambda st, oa, ttl: st < oa,
    "server_time>=open_at": lambda st, oa, ttl: st >= oa,
    "server_time_ge_open_at_plus_ttl": lambda st, oa, ttl: st >= oa + (ttl or 0),
    "any": lambda st, oa, ttl: True,
}


@dataclass
class ConsistencyVerdict:
    """一次观测的一致性结论。"""
    consistent: bool
    phase: str                        # 由 status 命中的生命周期阶段
    expected_ui: str | None
    observed_ui: str | None
    time_agree: bool | None           # status 对应阶段的时间关系是否与 server_time/open_at 自洽
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "consistent": self.consistent,
            "phase": self.phase,
            "expected_ui": self.expected_ui,
            "observed_ui": self.observed_ui,
            "time_agree": self.time_agree,
            "violations": self.violations,
        }


@dataclass
class AttackTest:
    """一条定向攻击测试点（不是普通用例，专门攻击一致性）。"""
    id: str
    title: str
    trigger_id: str
    trigger_name: str
    perturb_dimension: str
    focus: str
    steps: list[str] = field(default_factory=list)
    expected_anomaly: str = ""

    def to_dict(self) -> dict:
        return vars(self)


def load_model(path_or_dict: str | Path | dict) -> dict:
    if isinstance(path_or_dict, dict):
        return path_or_dict
    return json.loads(Path(path_or_dict).read_text(encoding="utf-8"))


def _phase_by_status(model: dict, status: int | str) -> tuple[str, dict] | None:
    for name, st in model["state_model"].items():
        if str(st.get("status") if not isinstance(st, dict) else st.get("status")) == str(status):
            return name, st
    return None


def check_consistency(model: dict, status, server_time, open_at,
                      observed_ui: str | None, ttl: int | None = None) -> ConsistencyVerdict:
    """对一次观测判定 status / server_time / open_at / ui_state 的一致性。"""
    hit = _phase_by_status(model, status)
    if hit is None:
        return ConsistencyVerdict(consistent=False, phase="UNKNOWN",
                                  expected_ui=None, observed_ui=observed_ui,
                                  time_agree=None, violations=[f"status={status} 不在状态模型"])
    phase, st = hit
    expected = st.get("ui")
    rel = _RELATIONS.get(st.get("time_relation", "any"))
    time_agree = rel(int(server_time), int(open_at), ttl) if rel else True

    violations: list[str] = []
    if observed_ui is not None and expected and str(observed_ui).upper() != str(expected).upper():
        violations.append(
            f"UI 与业务不一致：期望 UI={expected}({phase})，观测 UI={observed_ui}")
    if not time_agree:
        violations.append(
            f"status={status}({phase}) 与时间关系不一致：{st.get('time_relation')} 在 "
            f"server_time={server_time} open_at={open_at} 下不成立")
    return ConsistencyVerdict(
        consistent=not violations, phase=phase, expected_ui=expected,
        observed_ui=observed_ui, time_agree=time_agree, violations=violations)


def gen_test_id(model: dict, trigger: dict, i: int) -> str:
    tgt = str(model.get("target", "T")).upper().replace("-", "_")
    return f"ATTK-{tgt}-{i:02d}"


def build_attack_tests(model: dict) -> list[AttackTest]:
    """把模型的触发条件 → 定向攻击测试点。每个测试点专门攻击一致性。

    若无显式 trigger_conditions，则从 attack_paths 兜底合成（每个可执行攻击路径一个触发点），
    避免出现「有攻击路径却生成 0 用例」的空转。
    """
    triggers = model.get("trigger_conditions", []) or []
    if not triggers and model.get("attack_paths"):
        triggers = [
            {"id": ap.get("id"), "name": ap.get("name"),
             "perturb": ap.get("focus") or "state_consistency",
             "desc": ap.get("condition") or ap.get("name", "")}
            for ap in model.get("attack_paths", []) if ap.get("executable", True)
        ]
    inv = model.get("consistency_invariant", {})
    tests: list[AttackTest] = []
    for i, t in enumerate(triggers, 1):
        steps, focus = [], None
        for ap in model.get("attack_paths", []):
            steps2 = ap.get("steps", []) or []
            if any(str(step).strip().startswith(t["id"]) for step in steps2):
                steps, focus = steps2, ap["focus"]
                break
        if focus is None:
            focus = ", ".join(inv.get("dimensions", []))
        tests.append(AttackTest(
            id=gen_test_id(model, t, i),
            title=f"[{t['name']}] 攻击 {t['perturb']} 维度下与业务一致性",
            trigger_id=t["id"], trigger_name=t["name"],
            perturb_dimension=t["perturb"], focus=focus,
            steps=steps or [f"{t['id']} {t['desc']}"],
            expected_anomaly=model.get("known_anomaly", {}).get("business", ""),
        ))
    return tests


def tests_to_cases(tests: list[AttackTest], target: str = "red_packet_claim") -> list[dict]:
    """把定向攻击测试点 → 统一文档级测试用例（断言一致性，而非普通业务断言）。"""
    out = []
    for t in tests:
        out.append({
            "id": t.id,
            "title": t.title,
            "module": f"{target}-consistency-attack",
            "test_type": "attack",
            "category": "state_consistency",
            "preconditions": ["可观测到目标红包(status/open_at/server_time)",
                              "UI 呈现可被 dump/识别"],
            "attack_focus": t.focus,
            "steps": [{"step_id": i + 1, "action": s,
                      "expected": "UI 与业务生命周期一致；若出现 violation 则判定攻击命中"}
                      for i, s in enumerate(t.steps)],
        })
    return out