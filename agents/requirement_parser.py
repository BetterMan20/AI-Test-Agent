"""
agents/requirement_parser.py

Requirement Parser
==================

职责：
    将原始需求文本解析为结构化文本，供 Fact Extraction 使用。

核心原则：

    Raw Requirement
            ↓
    Requirement Parser
            ↓
       Parsed Text
            ↓
    Fact Extraction

Requirement Parser 负责：
    - 解析原始需求
    - 栞式化需求文本

Requirement Parser 不负责：
    - 事实提取
    - 需求分析
    - Gap Detection
    - Test Design
    - 生成结构化 JSON
"""

from __future__ import annotations

from typing import Any

from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class RequirementParser:

    AGENT_NAME = "requirement_parser"
    STAGE_NAME = "Requirement Parser"

    SKILL_PATH = SKILLS["parser"]

    def run(self, requirement: Any) -> str:

        if not isinstance(requirement, str):
            raise ValueError(
                "RequirementParser requires requirement as str."
            )

        if not requirement.strip():
            raise ValueError(
                "RequirementParser requires non-empty requirement."
            )

        result = SkillEngine.run(
            skill_path=self.SKILL_PATH,
            input_data=requirement,
            output_mode="text",
        )

        if not isinstance(result, str):
            raise ValueError(
                "RequirementParser output must be str."
            )

        if not result.strip():
            raise ValueError(
                "RequirementParser output is empty."
            )

        return result
