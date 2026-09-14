# -*- coding: utf-8 -*-
"""测试策略决策器（S6 入口）—— 决定本次回归跑哪些层与量。

输入：回归模式 + 待测业务点 + 风险/选项
输出：TestPlan（业务/攻击/稳定性 三层是否为、跑哪些、跑多少）

当前为确定性规则决策（可复现、无依赖），并预留 llm_hook 供后续接 LLM：
把决策输入丢给模型，由模型返回同样的 TestPlan 结构（少 token 往返）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class LayerPlan:
    layer: str
    enabled: bool
    ref: Any = None          # tc_ids / attack_ids / endpoint 等
    events: int = 0          # 稳定性事件量
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "layer": self.layer, "enabled": self.enabled,
            "ref": self.ref, "events": self.events, "params": self.params,
        }


@dataclass
class TestPlan:
    mode: str
    target: str
    layers: list[LayerPlan]
    validation: dict = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode, "target": self.target,
            "layers": [l.to_dict() for l in self.layers],
            "validation": self.validation,
            "rationale": self.rationale,
        }


# 从业务点/端点推断业务回放端点
DEFAULT_ENDPOINT = "send_red_packet"


class StrategyDecision:
    def __init__(self, llm_hook: Optional[Callable[[dict], dict]] = None) -> None:
        self._llm = llm_hook

    def decide(
        self,
        mode: str = "smoke",
        target: str = "",
        risk: str = "low",
        options: Optional[dict] = None,
    ) -> TestPlan:
        options = options or {}
        mode = (mode or "smoke").lower()
        if self._llm:
            plan = self._llm({"mode": mode, "target": target, "risk": risk,
                             "options": options})
            return TestPlan(**plan)

        endpoint = options.get("endpoint") or DEFAULT_ENDPOINT
        base = _BASE_MATRIX[mode]
        stab_events = options.get("stability_events") or base["stability"]["events"]
        layers = [
            LayerPlan("business", base["business"]["enabled"],
                      ref=base["business"].get("ref", endpoint),
                      params={"endpoint": endpoint}),
            LayerPlan("attack", base["attack"]["enabled"],
                      ref=base["attack"].get("ref", []),
                      params={"victim": target or "send_red_packet"}),
            LayerPlan("stability", base["stability"]["enabled"],
                      events=stab_events,
                      params={"anchor_bias": options.get("anchor_bias", 0.9)}),
        ]
        rationale, validation = _rationalize(mode, risk, target, layers)
        return TestPlan(mode=mode, target=target, layers=layers,
                        validation=validation, rationale=rationale)


# 决策矩阵：每种模式 → 各层开关/量
_BASE_MATRIX: dict[str, dict] = {
    "smoke": {
        "business": {"enabled": True, "ref": "probe1"},      # 每端点回放1条代表
        "attack": {"enabled": False},
        "stability": {"enabled": True, "events": 40},
    },
    "regression": {
        "business": {"enabled": True, "ref": "tc_all"},      # 全量 TC
        "attack": {"enabled": True, "ref": "executable"},    # A01/A02/A05/A07/A10
        "stability": {"enabled": True, "events": 1000},
    },
    "nightly": {
        "business": {"enabled": True, "ref": "tc_all"},
        "attack": {"enabled": True, "ref": "executable"},
        "stability": {"enabled": True, "events": 10000},
    },
}


def _rationalize(mode, risk, target, layers) -> tuple[list[str], dict]:
    r = []
    if mode == "smoke":
        r.append("smoke：单回放代表+小量稳定性，先快速验证链路是否可跑")
    elif mode == "regression":
        r.append("regression：全量业务用例 + 本机可执行攻击 + 中量稳定性")
    else:
        r.append("nightly：业务全量 + 攻击 + 大容量稳定性(10万级)")
    if risk in ("high", "critical"):
        r.append("高风险，稳定性事件量与攻击覆盖上调")
        for l in layers:
            if l.layer == "stability" and l.enabled:
                l.events = max(l.events, 3000)
    validation = {
        "business_pass_rate": 0.8 if mode == "smoke" else 0.9,
        "stability_crash_threshold": 0,
        "attack_must_not_crash": True,
    }
    return r, validation