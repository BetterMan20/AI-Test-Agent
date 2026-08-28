"""
agents/fact_extraction.py

Fact Extraction
===============

职责：
    从解析后的需求文本中提取事实。

核心原则：

    Parsed Text
            ↓
    Fact Extraction
            ↓
       Facts
            ↓
    Requirement Analysis

Fact Extraction 负责：
    - 提取需求中明确陈述的事实
    - 为每个事实分配唯一 ID

Fact Extraction 不负责：
    - 需求分析
    - Gap Detection
    - Test Design
    - Test Case 生成
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class FactExtraction:

    AGENT_NAME = "fact_extraction"
    STAGE_NAME = "Fact Extraction"

    SKILL_PATH = SKILLS["fact_extraction"]

    SCHEMA_PATH = (
        Path(__file__).resolve().parent.parent
        / "schema"
        / "requirement_fact.schema.json"
    )

    def run(self, parsed: Any) -> Dict[str, Any]:

        if not isinstance(parsed, str):
            raise ValueError(
                "FactExtraction requires parsed as str."
            )

        if not parsed.strip():
            raise ValueError(
                "FactExtraction requires non-empty parsed text."
            )

        result = SkillEngine.run(
            skill_path=self.SKILL_PATH,
            input_data=parsed,
            schema_path=str(self.SCHEMA_PATH),
            output_mode="json",
        )

        if not isinstance(result, dict):
            raise ValueError(
                "FactExtraction output must be a dict."
            )

        if not result:
            raise ValueError(
                "FactExtraction output is empty."
            )

        return result
