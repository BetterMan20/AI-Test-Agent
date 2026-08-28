"""
agents/requirement_analysis.py

Requirement Analysis
====================

职责：
    将 Facts 转换为结构化的业务规则。

核心原则：

       Facts
            ↓
    Requirement Analysis
            ↓
    Business Rules
            ↓
    Gap Detection / Test Design

Requirement Analysis 负责：
    - 识别业务规则
    - 识别状态规则
    - 识别数据规则
    - 识别约束
    - 引用 Fact IDs

Requirement Analysis 不负责：
    - Fact Extraction
    - Gap Detection
    - Test Design
    - Test Case 生成
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class RequirementAnalysis:

    AGENT_NAME = "requirement_analysis"
    STAGE_NAME = "Requirement Analysis"

    SKILL_PATH = SKILLS["analysis"]

    SCHEMA_PATH = (
        Path(__file__).resolve().parent.parent
        / "schema"
        / "requirement_analysis.schema.json"
    )

    def run(self, facts: Any) -> Dict[str, Any]:

        if not isinstance(facts, dict):
            raise ValueError(
                "RequirementAnalysis requires facts as dict."
            )

        if not facts:
            raise ValueError(
                "RequirementAnalysis requires non-empty facts."
            )

        result = SkillEngine.run(
            skill_path=self.SKILL_PATH,
            input_data=facts,
            schema_path=str(self.SCHEMA_PATH),
            output_mode="json",
        )

        if not isinstance(result, dict):
            raise ValueError(
                "RequirementAnalysis output must be a dict."
            )

        if not result:
            raise ValueError(
                "RequirementAnalysis output is empty."
            )

        return result
