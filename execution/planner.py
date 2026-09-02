"""Execution planner — converts document-level TC into executable plan."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from execution.context import EnvironmentConfig


@dataclass
class ExecutionStep:
    """单条可执行步骤。"""

    step_id: int
    step_type: str  # api | db | adb | manual
    description: str
    action: dict[str, Any] = field(default_factory=dict)
    assertions: list[dict[str, Any]] = field(default_factory=list)
    evidence_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "type": self.step_type,
            "description": self.description,
            "config": self.action,
            "assertions": self.assertions,
            "evidence_types": self.evidence_types,
        }


@dataclass
class ExecutionPlan:
    """单条 TC 的执行计划。"""

    tc_id: str
    title: str
    steps: list[ExecutionStep] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    test_data: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tc_id": self.tc_id,
            "title": self.title,
            "steps": [s.to_dict() for s in self.steps],
            "preconditions": self.preconditions,
            "test_data": self.test_data,
        }


class ExecutionPlanner:
    """将文档级 TC 转换为可执行步骤。"""

    EVIDENCE_MAP: dict[str, list[str]] = {
        "api": ["api_response"],
        "db": ["db_snapshot"],
        "adb": ["screenshot", "logcat"],
        "manual": [],
    }

    def plan(
        self,
        test_case: dict[str, Any],
        environment: EnvironmentConfig,
    ) -> ExecutionPlan:
        tc_id = test_case.get("id", "")
        title = test_case.get("title", "")
        raw_steps = test_case.get("steps", [])
        expected_results = test_case.get("expected_results", [])

        steps: list[ExecutionStep] = []
        for i, raw in enumerate(raw_steps, 1):
            action_text = raw.get("action", "")
            step_type = self._detect_type(action_text)
            steps.append(
                ExecutionStep(
                    step_id=i,
                    step_type=step_type,
                    description=action_text,
                    action=self._parse_action(step_type, action_text),
                    assertions=self._build_assertions(expected_results),
                    evidence_types=self.EVIDENCE_MAP.get(step_type, []),
                )
            )

        return ExecutionPlan(
            tc_id=tc_id,
            title=title,
            steps=steps,
            preconditions=test_case.get("preconditions", []),
            test_data=test_case.get("test_data", []),
        )

    def _detect_type(self, action_text: str) -> str:
        """从自然语言动作文本推断步骤类型。当前全部回退为 manual。"""
        return "manual"

    def _parse_action(self, step_type: str, action_text: str) -> dict[str, Any]:
        if step_type == "manual":
            return {"instruction": action_text}
        return {}

    def _build_assertions(self, expected_results: list[str]) -> list[dict[str, Any]]:
        return [
            {"type": "text_contains", "expected": text}
            for text in expected_results
        ]

    @staticmethod
    def plan_from_dict(plan_data: dict[str, Any]) -> ExecutionPlan:
        """Build an ExecutionPlan from a dict matching execution_plan.schema.json."""
        steps_data = plan_data.get("steps", [])
        steps: list[ExecutionStep] = []
        for s in steps_data:
            steps.append(
                ExecutionStep(
                    step_id=s["step_id"],
                    step_type=s["type"],
                    description=s.get("description", ""),
                    action=s.get("config", {}),
                    assertions=s.get("assertions", []),
                    evidence_types=s.get("evidence_types", []),
                )
            )
        return ExecutionPlan(
            tc_id=plan_data["tc_id"],
            title=plan_data["title"],
            steps=steps,
            preconditions=plan_data.get("preconditions", []),
            test_data=plan_data.get("test_data", []),
        )
