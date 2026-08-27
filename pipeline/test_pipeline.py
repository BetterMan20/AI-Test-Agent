"""
Test AI Agent - Test Pipeline

Pipeline:

Raw Requirement
    ↓
Requirement Parser
    ↓
Requirement Analysis
    ↓
Test Design
    ↓
Test Case Generator
    ↓
Test Case Validator
    ↓
Final Result

职责：
1. 编排各 Agent
2. 管理阶段输入输出
3. 校验阶段状态
4. 保存中间产物
5. 控制 Pipeline 是否继续
6. 汇总最终结果

注意：
Pipeline 不负责具体测试设计逻辑。
Pipeline 不负责生成测试用例。
Pipeline 不负责 Validator 规则判断。

这些职责分别属于对应 Agent。
"""

from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


# ============================================================
# Logging
# ============================================================

logger = logging.getLogger("test_pipeline")


# ============================================================
# Pipeline Exceptions
# ============================================================

class PipelineError(Exception):
    """Pipeline 基础异常。"""


class PipelineStageError(PipelineError):
    """Pipeline 某阶段执行失败。"""

    def __init__(self, stage: str, message: str):
        self.stage = stage
        self.message = message
        super().__init__(f"[{stage}] {message}")


class PipelineValidationError(PipelineError):
    """Validator 返回 FAIL。"""

    def __init__(self, message: str, validation_result: Dict[str, Any]):
        self.validation_result = validation_result
        super().__init__(message)


# ============================================================
# Pipeline Context
# ============================================================

@dataclass
class PipelineContext:
    """
    Pipeline 全流程上下文。

    每一个阶段的结果都放在 Context 中，
    后续 Agent 从 Context 获取输入。

    好处：
    - 阶段之间解耦
    - 方便 Debug
    - 方便保存中间结果
    - 方便未来加入 Review / Repair
    """

    run_id: str

    raw_requirement: str = ""

    parsed_requirement: Optional[Dict[str, Any]] = None

    requirement_analysis: Optional[Dict[str, Any]] = None

    test_design: Optional[Dict[str, Any]] = None

    test_cases: Optional[Dict[str, Any]] = None

    validation_result: Optional[Dict[str, Any]] = None

    current_stage: str = "INIT"

    completed_stages: list[str] = field(default_factory=list)

    errors: list[Dict[str, Any]] = field(default_factory=list)

    started_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )

    finished_at: Optional[str] = None

    def mark_stage_completed(self, stage: str) -> None:
        self.completed_stages.append(stage)
        self.current_stage = stage

    def mark_finished(self) -> None:
        self.finished_at = datetime.now().isoformat()

    def add_error(
        self,
        stage: str,
        error: Exception,
    ) -> None:
        self.errors.append(
            {
                "stage": stage,
                "error_type": type(error).__name__,
                "message": str(error),
            }
        )


# ============================================================
# Pipeline
# ============================================================

class TestPipeline:
    """
    QA Test AI Agent 主 Pipeline。

    Pipeline 只负责 orchestration。

    Agent 职责：

    RequirementParser
        → 原始需求预处理

    RequirementAnalysisAgent
        → 需求业务事实分析

    TestDesignAgent
        → 测试设计

    TestCaseGeneratorAgent
        → 测试用例生成

    TestCaseValidatorAgent
        → 三方验证
    """

    STAGE_PARSE = "REQUIREMENT_PARSE"
    STAGE_ANALYSIS = "REQUIREMENT_ANALYSIS"
    STAGE_DESIGN = "TEST_DESIGN"
    STAGE_GENERATION = "TEST_CASE_GENERATION"
    STAGE_VALIDATION = "TEST_CASE_VALIDATION"

    def __init__(
        self,
        requirement_parser,
        requirement_analyzer,
        test_designer,
        testcase_generator,
        testcase_validator,
        output_dir: Optional[str | Path] = None,
    ):
        self.requirement_parser = requirement_parser
        self.requirement_analyzer = requirement_analyzer
        self.test_designer = test_designer
        self.testcase_generator = testcase_generator
        self.testcase_validator = testcase_validator

        self.output_dir = (
            Path(output_dir)
            if output_dir
            else Path("output")
        )

        self.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    # ========================================================
    # Public API
    # ========================================================

    def run(
        self,
        requirement: str,
        run_id: Optional[str] = None,
    ) -> PipelineContext:
        """
        执行完整 QA Pipeline。
        """

        if not requirement or not requirement.strip():
            raise ValueError(
                "requirement cannot be empty"
            )

        run_id = run_id or self._generate_run_id()

        context = PipelineContext(
            run_id=run_id,
            raw_requirement=requirement,
        )

        logger.info(
            "Starting Test Pipeline: %s",
            run_id,
        )

        try:
            # ------------------------------------------------
            # Stage 1
            # ------------------------------------------------

            self._run_stage(
                context,
                self.STAGE_PARSE,
                self._parse_requirement,
            )

            # ------------------------------------------------
            # Stage 2
            # ------------------------------------------------

            self._run_stage(
                context,
                self.STAGE_ANALYSIS,
                self._analyze_requirement,
            )

            # ------------------------------------------------
            # Stage 3
            # ------------------------------------------------

            self._run_stage(
                context,
                self.STAGE_DESIGN,
                self._design_test,
            )

            # ------------------------------------------------
            # Stage 4
            # ------------------------------------------------

            self._run_stage(
                context,
                self.STAGE_GENERATION,
                self._generate_test_cases,
            )

            # ------------------------------------------------
            # Stage 5
            # ------------------------------------------------

            self._run_stage(
                context,
                self.STAGE_VALIDATION,
                self._validate_test_cases,
            )

            context.mark_finished()

            self._save_final_result(context)

            logger.info(
                "Test Pipeline completed: %s",
                run_id,
            )

            return context

        except Exception as exc:

            context.add_error(
                context.current_stage,
                exc,
            )

            context.mark_finished()

            self._save_failure_result(
                context,
                exc,
            )

            logger.exception(
                "Test Pipeline failed: %s",
                run_id,
            )

            raise

    # ========================================================
    # Stage Runner
    # ========================================================

    def _run_stage(
        self,
        context: PipelineContext,
        stage: str,
        handler,
    ) -> None:
        """
        统一执行 Pipeline Stage。
        """

        logger.info(
            "Starting stage: %s",
            stage,
        )

        try:

            handler(context)

            context.mark_stage_completed(stage)

            logger.info(
                "Stage completed: %s",
                stage,
            )

        except Exception as exc:

            context.add_error(
                stage,
                exc,
            )

            raise PipelineStageError(
                stage,
                str(exc),
            ) from exc

    # ========================================================
    # Stage 1
    # ========================================================

    def _parse_requirement(
        self,
        context: PipelineContext,
    ) -> None:
        """
        Requirement Parser。

        Raw Requirement
            ↓
        Parsed Requirement
        """

        result = self.requirement_parser.parse(
            context.raw_requirement
        )

        self._ensure_dict(
            result,
            self.STAGE_PARSE,
        )

        context.parsed_requirement = result

        self._save_stage_result(
            context,
            "parsed_requirement.json",
            result,
        )

    # ========================================================
    # Stage 2
    # ========================================================

    def _analyze_requirement(
        self,
        context: PipelineContext,
    ) -> None:
        """
        Requirement Analysis。

        Parsed Requirement
            ↓
        Requirement Analysis
        """

        if context.parsed_requirement is None:
            raise PipelineError(
                "parsed_requirement is missing"
            )

        result = self.requirement_analyzer.analyze(
            context.parsed_requirement
        )

        self._ensure_dict(
            result,
            self.STAGE_ANALYSIS,
        )

        context.requirement_analysis = result

        self._save_stage_result(
            context,
            "requirement_analysis.json",
            result,
        )

    # ========================================================
    # Stage 3
    # ========================================================

    def _design_test(
        self,
        context: PipelineContext,
    ) -> None:
        """
        Test Design。

        Requirement Analysis
            ↓
        Test Design
        """

        if context.requirement_analysis is None:
            raise PipelineError(
                "requirement_analysis is missing"
            )

        result = self.test_designer.design(
            context.requirement_analysis
        )

        self._ensure_dict(
            result,
            self.STAGE_DESIGN,
        )

        context.test_design = result

        self._save_stage_result(
            context,
            "test_design.json",
            result,
        )

    # ========================================================
    # Stage 4
    # ========================================================

    def _generate_test_cases(
        self,
        context: PipelineContext,
    ) -> None:
        """
        Test Case Generator。

        Requirement Analysis
              +
        Test Design
              ↓
        Generated Test Cases
        """

        if context.requirement_analysis is None:
            raise PipelineError(
                "requirement_analysis is missing"
            )

        if context.test_design is None:
            raise PipelineError(
                "test_design is missing"
            )

        result = self.testcase_generator.generate(
            requirement_analysis=context.requirement_analysis,
            test_design=context.test_design,
        )

        self._ensure_dict(
            result,
            self.STAGE_GENERATION,
        )

        context.test_cases = result

        self._save_stage_result(
            context,
            "test_cases.json",
            result,
        )

    # ========================================================
    # Stage 5
    # ========================================================

    def _validate_test_cases(
        self,
        context: PipelineContext,
    ) -> None:
        """
        Test Case Validator。

        Requirement Analysis
              +
        Test Design
              +
        Generated Test Cases
              ↓
        Validation Result
        """

        if context.requirement_analysis is None:
            raise PipelineError(
                "requirement_analysis is missing"
            )

        if context.test_design is None:
            raise PipelineError(
                "test_design is missing"
            )

        if context.test_cases is None:
            raise PipelineError(
                "test_cases is missing"
            )

        result = self.testcase_validator.validate(
            requirement_analysis=context.requirement_analysis,
            test_design=context.test_design,
            test_cases=context.test_cases,
        )

        self._ensure_dict(
            result,
            self.STAGE_VALIDATION,
        )

        context.validation_result = result

        self._save_stage_result(
            context,
            "validation_result.json",
            result,
        )

        # ----------------------------------------------------
        # Quality Gate
        # ----------------------------------------------------

        status = str(
            result.get("status", "")
        ).upper()

        if status == "FAIL":

            raise PipelineValidationError(
                "Generated test cases failed validation",
                result,
            )

    # ========================================================
    # Result Persistence
    # ========================================================

    def _save_stage_result(
        self,
        context: PipelineContext,
        filename: str,
        result: Dict[str, Any],
    ) -> None:

        run_dir = (
            self.output_dir
            / context.run_id
        )

        run_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        file_path = run_dir / filename

        self._write_json(
            file_path,
            result,
        )

    def _save_final_result(
        self,
        context: PipelineContext,
    ) -> None:

        result = {
            "run_id": context.run_id,
            "status": "PASS",
            "completed_stages": context.completed_stages,
            "validation_result": context.validation_result,
            "test_cases": context.test_cases,
            "started_at": context.started_at,
            "finished_at": context.finished_at,
        }

        self._save_stage_result(
            context,
            "final_result.json",
            result,
        )

    def _save_failure_result(
        self,
        context: PipelineContext,
        error: Exception,
    ) -> None:

        result = {
            "run_id": context.run_id,
            "status": "FAIL",
            "failed_stage": context.current_stage,
            "completed_stages": context.completed_stages,
            "errors": context.errors,
            "error": str(error),
            "started_at": context.started_at,
            "finished_at": context.finished_at,
        }

        self._save_stage_result(
            context,
            "pipeline_failure.json",
            result,
        )

    # ========================================================
    # Helpers
    # ========================================================

    @staticmethod
    def _ensure_dict(
        result: Any,
        stage: str,
    ) -> None:

        if not isinstance(result, dict):

            raise PipelineError(
                f"{stage} returned "
                f"{type(result).__name__}, "
                f"expected dict"
            )

    @staticmethod
    def _write_json(
        path: Path,
        data: Dict[str, Any],
    ) -> None:

        path.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_run_id() -> str:

        return datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )[:-3]


# ============================================================
# Factory
# ============================================================

def create_test_pipeline(
    requirement_parser,
    requirement_analyzer,
    test_designer,
    testcase_generator,
    testcase_validator,
    output_dir: Optional[str | Path] = None,
) -> TestPipeline:
    """
    Pipeline Factory。

    推荐 main.py 使用这个方法创建 Pipeline。
    """

    return TestPipeline(
        requirement_parser=requirement_parser,
        requirement_analyzer=requirement_analyzer,
        test_designer=test_designer,
        testcase_generator=testcase_generator,
        testcase_validator=testcase_validator,
        output_dir=output_dir,
    )


# ============================================================
# Example
# ============================================================

if __name__ == "__main__":
    """
    这里不直接实例化真实 Agent。

    因为 Agent 的具体实现属于 agents/。

    推荐在 main.py 中：

        parser = RequirementParser(...)
        analyzer = RequirementAnalysisAgent(...)
        designer = TestDesignAgent(...)
        generator = TestCaseGenerator(...)
        validator = TestCaseValidator(...)

        pipeline = create_test_pipeline(
            parser,
            analyzer,
            designer,
            generator,
            validator,
        )

        result = pipeline.run(requirement)
    """

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s "
            "[%(levelname)s] "
            "%(name)s - "
            "%(message)s"
        ),
    )

    logger.info(
        "Test Pipeline module loaded."
    )