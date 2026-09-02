"""
agents/test_design.py

Test Design Agent
=================

职责：
    将 Requirement Analysis + Requirement Gap 转换为 Test Design。

核心原则：

    Requirement Analysis
            +
    Requirement Gap
            ↓
       Test Design
            ↓
       Test Points
            ↓
    Test Case Generator

Test Design 负责：
    - 识别测试点
    - 选择测试设计方法
    - 定义测试维度
    - 定义边界
    - 定义状态
    - 定义数据关系
    - 定义约束
    - 建立 Requirement / Gap → Test Point 的追踪关系

Test Design 不负责：
    - 生成具体 Test Case
    - 编写操作步骤
    - 编写期望结果
    - 验证 Test Case
    - 做最终质量判定
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class TestDesign:

    AGENT_NAME = "test_design"
    STAGE_NAME = "Test Design"

    SKILL_PATH = SKILLS["design"]

    SCHEMA_PATH = (
        Path(__file__).resolve().parent.parent
        / "schema"
        / "test_design.schema.json"
    )

    def run(
        self,
        analysis: Dict[str, Any],
        gaps: Dict[str, Any],
    ) -> Dict[str, Any]:

        if not isinstance(analysis, dict):
            raise ValueError(
                "TestDesign requires analysis as dict."
            )

        if not isinstance(gaps, dict):
            raise ValueError(
                "TestDesign requires gaps as dict."
            )

        input_data = {
            "requirement_analysis": analysis,
            "requirement_gap": gaps,
        }

        result = SkillEngine.run(
            skill_path=str(self.SKILL_PATH),
            input_data=input_data,
            schema_path=str(self.SCHEMA_PATH),
            output_mode="json",
        )

        if not isinstance(result, dict):
            raise ValueError(
                "TestDesign output must be a dict."
            )

        return result