"""
agents/testcase_validator.py

Test Case Validator
===================

职责：
    验证 Test Cases 是否正确实现 Test Design。

输入：

    Requirement Analysis
            ↓
       Test Design
            ↓
       Test Cases

Validator 重点检查：

    1. Test Case 是否存在
    2. Test Case 是否对应 Test Point
    3. 每个 Test Point 是否至少存在一个 Test Case
    4. Test Case 是否覆盖 Test Design
    5. Test Case 是否存在无依据的业务假设
    6. Test Case 是否与 Requirement Analysis 冲突
    7. 操作步骤是否可执行
    8. 期望结果是否可验证
    9. Test Case 是否遗漏关键设计条件

核心原则：

    Validator 不负责发现新的 Test Point。

    Test Point 是 Test Design 的责任。

    Validator 只判断：

        Test Design
             ↓
        Test Cases

    是否被正确实现。

不负责：
    - Requirement Analysis
    - Gap Detection
    - Test Design
    - Test Case Generation
    - Quality Validation
    - Release Gate
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from utils.skill_engine import SkillEngine


class TestCaseValidator:

    AGENT_NAME = "testcase_validator"
    STAGE_NAME = "Test Case Validator"

    SKILL_PATH = (
        Path(__file__).resolve().parent.parent
        / "skills"
        / "test-case-validator.skill.md"
    )

    SCHEMA_PATH = (
        Path(__file__).resolve().parent.parent
        / "schema"
        / "test_case_validation.schema.json"
    )

    def run(
        self,
        analysis: Dict[str, Any],
        test_design: Dict[str, Any],
        test_cases: Dict[str, Any],
    ) -> Dict[str, Any]:

        if not isinstance(analysis, dict):
            raise ValueError(
                "TestCaseValidator requires analysis as dict."
            )

        if not isinstance(test_design, dict):
            raise ValueError(
                "TestCaseValidator requires test_design as dict."
            )

        if not isinstance(test_cases, dict):
            raise ValueError(
                "TestCaseValidator requires test_cases as dict."
            )

        input_data = {
            "requirement_analysis": analysis,
            "test_design": test_design,
            "test_cases": test_cases,
        }

        result = SkillEngine.run(
            skill_path=str(self.SKILL_PATH),
            input_data=input_data,
            schema_path=str(self.SCHEMA_PATH),
            output_mode="json",
        )

        if not isinstance(result, dict):
            raise ValueError(
                "TestCaseValidator output must be a dict."
            )

        return result