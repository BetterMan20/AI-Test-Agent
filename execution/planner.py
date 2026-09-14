"""Execution planner — converts document-level TC into executable plan."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from configs.skills import SKILLS
from utils.skill_loader import load_skill
from utils.llm import ask_llm


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

    @staticmethod
    def plan_from_test_case(
        test_case: dict[str, Any],
        capability: Any | None = None,
    ) -> ExecutionPlan:
        """LLM 驱动：将文档级 TC（自然语言 steps）转为可执行 ExecutionPlan.

        Args:
            test_case: 文档级 TC dict
            capability: APICapability 实例，提供 API 知识上下文
        """
        skill_path = SKILLS["tc_to_plan"]
        system_prompt = load_skill(skill_path)

        if capability is not None:
            keywords: list[str] = []
            title = test_case.get("title", "")
            steps_text = " ".join(s.get("action", "") for s in test_case.get("steps", []))
            for word in (title + " " + steps_text).replace("/", " ").split():
                if len(word) > 2 and word.isalpha():
                    keywords.append(word.lower())
            api_knowledge = capability.to_prompt(keywords=keywords[:5])
            system_prompt = system_prompt + "\n\n" + api_knowledge

        user_prompt = json.dumps(
            {"test_case": test_case}, ensure_ascii=False, indent=2
        )

        raw = ask_llm(system_prompt, user_prompt)
        plan_data = ExecutionPlanner._extract_plan_json(raw)
        ExecutionPlanner._normalize_plan(plan_data)

        return ExecutionPlanner.plan_from_dict(plan_data)

    @staticmethod
    def _extract_plan_json(raw: str) -> dict[str, Any]:
        """从 LLM 输出中提取 JSON（兼容 markdown 包裹、//注释、尾随逗号等）。"""
        import re

        text = raw.strip()

        def _clean(candidate: str) -> str:
            candidate = re.sub(r"//[^\n\r]*", "", candidate)
            candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
            candidate = candidate.replace("'", '"')
            return candidate

        def _try_parse(candidate: str) -> dict[str, Any] | None:
            candidate = _clean(candidate)
            try:
                return json.loads(candidate, strict=False)
            except json.JSONDecodeError:
                obj = ExecutionPlanner._extract_first_json_object(candidate)
                if obj:
                    try:
                        return json.loads(obj, strict=False)
                    except json.JSONDecodeError:
                        pass
                return None

        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if match:
            result = _try_parse(match.group(1))
            if result is not None:
                return result

        match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            result = _try_parse(match.group(1))
            if result is not None:
                return result

        obj = ExecutionPlanner._extract_first_json_object(text)
        if obj:
            result = _try_parse(obj)
            if result is not None:
                return result

        return json.loads(_clean(text))

    @staticmethod
    def _extract_first_json_object(text: str) -> str | None:
        """从文本中提取第一个完整的 JSON 对象（通过花括号配对）。"""
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False

        for i in range(start, len(text)):
            ch = text[i]

            if escape:
                escape = False
                continue

            if ch == "\\":
                escape = True
                continue

            if ch == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]

        return None

    @staticmethod
    def _normalize_plan(plan_data: dict[str, Any]) -> None:
        """修复 LLM 输出中的常见问题，确保 config 字段与 step type 匹配。"""
        for step in plan_data.get("steps", []):
            step_type = step.get("type", "manual")
            config = step.get("config")

            if not isinstance(config, dict):
                config = {}
                step["config"] = config

            if step_type == "api":
                config.setdefault("method", "GET")
                config.setdefault("path", "/")
            elif step_type == "db":
                config.setdefault("phase", "verify")
                config.setdefault("query", "SELECT 1")
            elif step_type == "adb":
                if "command" not in config:
                    config["command"] = step.get("description", "")
            elif step_type == "manual":
                if "instruction" not in config:
                    config["instruction"] = step.get("description", "")

    @staticmethod
    def plan_from_capture(captured_api) -> ExecutionPlan:
        """从 Whistle 抓包记录生成 ExecutionPlan（直接回放真实 API）。"""
        from tools.whistle_parser import CapturedAPI

        if not isinstance(captured_api, CapturedAPI):
            raise TypeError("plan_from_capture requires a CapturedAPI instance")

        endpoint = captured_api.endpoint
        tc_id = f"TC-CAP-{abs(hash(captured_api.capture_id)) % 100000:05d}"

        plan_data = {
            "tc_id": tc_id,
            "title": f"回放 {captured_api.method} {endpoint}",
            "preconditions": ["从 Whistle 抓包回放", f"原始状态码: {captured_api.status_code}"],
            "test_data": [f"capture_id={captured_api.capture_id}"],
            "steps": [{
                "step_id": 1,
                "type": "api",
                "description": f"{captured_api.method} {endpoint}",
                "config": {
                    "method": captured_api.method,
                    "path": captured_api.path_with_query,
                    "headers": captured_api.req_headers,
                    "body": captured_api.req_body or {},
                },
                "assertions": [
                    {"type": "status_code", "expected": captured_api.status_code},
                ],
                "evidence_types": ["api_response"],
            }],
        }

        if captured_api.res_body and isinstance(captured_api.res_body, dict):
            ret = captured_api.res_body.get("ret")
            if ret is not None:
                plan_data["steps"][0]["assertions"].append(
                    {"type": "json_path", "path": "$.ret", "expected": ret}
                )

        return ExecutionPlanner.plan_from_dict(plan_data)
