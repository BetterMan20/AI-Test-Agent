"""
agents/testcase_generator.py

Test Case Generator
===================

职责：
    将 Test Design 实现为可执行 Test Case。

核心原则：

    Test Design
         ↓
    Test Case Generator
         ↓
    Test Cases

Generator 不负责发现新的测试点。

例如：

Test Point:
    48h边界

Generator 应该生成：

    48h - 1s
    48h
    48h + 1s

而不是自行判断：

    “是不是还应该测试48h？”

测试点发现属于 Test Design。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class TestCaseGenerator:

    AGENT_NAME = "testcase_generator"
    STAGE_NAME = "Test Case Generator"

    SKILL_PATH = SKILLS["generation"]

    SCHEMA_PATH = (
        Path(__file__).resolve().parent.parent
        / "schema"
        / "test_case.schema.json"
    )

    def run(
        self,
        test_design: Dict[str, Any],
    ) -> Dict[str, Any]:

        if not isinstance(test_design, dict):
            raise ValueError(
                "TestCaseGenerator requires test_design as dict."
            )

        result = SkillEngine.run(
            skill_path=str(self.SKILL_PATH),
            input_data={
                "test_design": test_design,
            },
            schema_path=str(self.SCHEMA_PATH),
            output_mode="json",
        )

        if not isinstance(result, dict):
            raise ValueError(
                "TestCaseGenerator output must be a dict."
            )

        return result