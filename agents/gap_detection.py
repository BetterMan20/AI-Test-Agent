"""
agents/gap_detection.py

Gap Detection
=============

职责：
    基于已确认的事实和业务模型，发现缺失、冲突、歧义。

核心原则：

    Facts + Analysis
              ↓
      Gap Detection
              ↓
          Gaps
              ↓
       Test Design

Gap Detection 负责：
    - 识别未明确的需求
    - 识别遗漏的边界
    - 识别缺失的约束
    - 引用 Fact IDs 和 Analysis 项

Gap Detection 不负责：
    - Fact Extraction
    - Requirement Analysis
    - Test Design
    - Test Case 生成
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class GapDetection:

    AGENT_NAME = "gap_detection"
    STAGE_NAME = "Gap Detection"

    SKILL_PATH = SKILLS["gap_detection"]

    SCHEMA_PATH = (
        Path(__file__).resolve().parent.parent
        / "schema"
        / "requirement_gap.schema.json"
    )

    def run(
        self,
        facts: Any,
        analysis: Any,
    ) -> Dict[str, Any]:

        if not isinstance(facts, dict):
            raise ValueError(
                "GapDetection requires facts as dict."
            )

        if not facts:
            raise ValueError(
                "GapDetection requires non-empty facts."
            )

        if not isinstance(analysis, dict):
            raise ValueError(
                "GapDetection requires analysis as dict."
            )

        if not analysis:
            raise ValueError(
                "GapDetection requires non-empty analysis."
            )

        input_data = {
            "facts": facts,
            "analysis": analysis,
        }

        result = SkillEngine.run(
            skill_path=self.SKILL_PATH,
            input_data=input_data,
            schema_path=str(self.SCHEMA_PATH),
            output_mode="json",
        )

        if not isinstance(result, dict):
            raise ValueError(
                "GapDetection output must be a dict."
            )

        if not result:
            raise ValueError(
                "GapDetection output is empty."
            )

        return result
