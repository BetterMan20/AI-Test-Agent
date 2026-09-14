# -*- coding: utf-8 -*-
"""core.adapters.base — 项目适配器抽象接口。

「通用引擎 + 项目适配器」的核心契约：
  · Core 只做测试编排，不知道「HIGO 红包」是什么；
  · 具体业务动作由各项目在 projects/<proj>/adapters 里实现 Adapter；
  · Core 通过 execute_action / get_state / collect_evidence 三个入口驱动它。

新增一个适配器不需要改 Core 或 app：只要实现本接口并声明在项目配置里即可。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionResult:
    """一次业务动作的执行结果（通用结构，不含任何业务语义）。"""
    action: str
    ok: bool
    status: str = "UNKNOWN"                 # PASS / FAIL / BLOCKED / UNKNOWN
    summary: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    error: str | None = None

    def __bool__(self) -> bool:
        return self.ok


class TTestAdapter(ABC):
    """项目适配器抽象基类。Core 与 app 只依赖它，不依赖具体项目。"""

    name: str = "base"
    description: str = ""
    actions: list[str] = []                 # 该适配器声明支持的业务动作清单

    def __init__(self, project: str, env_cfg=None, evidence_dir: str = "",
                 params: dict | None = None) -> None:
        self.project = project
        self.env_cfg = env_cfg
        self.evidence_dir = evidence_dir
        self.params = params or {}

    # ── Core 唯一真正依赖的三个入口 ──────────────────────────
    @abstractmethod
    def execute_action(self, action: str, params: dict | None = None) -> ActionResult:
        """执行一个业务动作（如 send_red_packet），返回通用结果。"""

    def get_state(self) -> dict:
        """拉取当前被测对象/设备状态（默认空；子类按需实现）。"""
        return {}

    def collect_evidence(self) -> list[str]:
        """收集本次执行产生的证据文件路径（默认空；子类按需实现）。"""
        return []

    # ── 便捷工具（子类可复用） ──────────────────────────────
    def _action_result(self, action: str, ok: bool, **kw) -> ActionResult:
        kw.setdefault("evidence", self.collect_evidence())
        kw["summary"] = {**getattr(self, "last_summary", {}), **(kw.get("summary") or {})}
        return ActionResult(action=action, ok=ok, **kw)