from agents.requirement_parser import RequirementParser
from agents.fact_extraction import FactExtraction
from agents.requirement_analysis import RequirementAnalysis
from agents.gap_detection import GapDetection
from agents.test_design import TestDesign
from agents.testcase_generator import TestCaseGenerator
from agents.testcase_validator import TestCaseValidator
from agents.quality_review import QualityReview
from agents.release_gate import ReleaseGate


from utils.output import Output
from workflow.context import WorkflowContext

import json


class QAWorkflow:
    """
    9 阶段 → 5 阶段，贴合测试团队真实流程：

      S1 需求理解  = 需求解析 + 事实抽取（分块，防截断）
      S2 需求分析  = 业务模型建模 + 缺口检测
      S3 测试设计  = 模块拆分 + 测试点
      S4 用例生成  = 生成测试用例
      S5 用例评审  = 用例校验 + 质量评审 + 发布门禁（评审/门禁为确定性，快速）
      S6 批量回归  = 抓包API回放 + 文档级TC批量执行 + ADB/UI验证（可选，需配置）
    """

    def __init__(self):

        self.parser = RequirementParser()
        self.fact_extraction = FactExtraction()
        self.analysis = RequirementAnalysis()
        self.gap_detection = GapDetection()
        self.test_design = TestDesign()
        self.generator = TestCaseGenerator()
        self.validator = TestCaseValidator()
        self.quality_review = QualityReview()

        self.release_gate = ReleaseGate()

    def run(self, requirement, regression_config=None):

        ctx = WorkflowContext(requirement)

        print("=" * 60)
        print("========== QA Workflow (5 阶段) ==========")
        print("=" * 60)
        if regression_config:
            print("（含 S6 批量回归：抓包API回放 + TC批量 + ADB/UI 验证）")

        # ==================================================
        # Stage 1: 需求理解 —— 解析 + 事实抽取
        # ==================================================

        print("\n========== Stage 1/5 需求理解 ==========")
        print("  (1.1) 需求解析")

        ctx.parsed = self.parser.run(ctx.requirement)
        Output.save("parsed.json", ctx.parsed)

        print("  (1.2) 事实抽取（分块，防截断）")

        ctx.facts = self.fact_extraction.run(ctx.parsed)
        Output.save("facts.json", ctx.facts)

        # ==================================================
        # Stage 2: 需求分析 —— 业务模型 + 缺口检测
        # ==================================================

        print("\n========== Stage 2/5 需求分析 ==========")
        print("  (2.1) 业务模型建模")

        ctx.analysis = self.analysis.run(ctx.facts)
        Output.save("analysis.json", ctx.analysis)

        print("  (2.2) 缺口检测")

        ctx.gaps = self.gap_detection.run(
            ctx.facts,
            ctx.analysis
        )
        Output.save("gaps.json", ctx.gaps)

        # ==================================================
        # Stage 3: 测试设计 —— 模块 + 测试点
        # ==================================================

        print("\n========== Stage 3/5 测试设计 ==========")

        ctx.test_design = self.test_design.run(
            ctx.analysis,
            ctx.gaps
        )
        Output.save("test_design.json", ctx.test_design)

        # ==================================================
        # Stage 4: 用例生成
        # ==================================================

        print("\n========== Stage 4/5 用例生成 ==========")

        ctx.test_cases = self.generator.run(ctx.test_design)
        Output.save("test_cases.json", ctx.test_cases)

        # ==================================================
        # Stage 5: 用例评审 —— 校验 + 质量评审 + 发布门禁
        # ==================================================

        print("\n========== Stage 5/5 用例评审 ==========")
        print("  (5.1) 用例校验")

        ctx.validation = self.validator.run(
            ctx.analysis,
            ctx.test_design,
            ctx.test_cases
        )
        Output.save("validation_result.json", ctx.validation)

        print("  (5.2) 质量评审（确定性）")

        ctx.quality_review = self.quality_review.run(
            ctx.facts,
            ctx.analysis,
            ctx.gaps,
            ctx.test_design,
            ctx.test_cases,
            ctx.validation
        )
        Output.save("quality_review.json", ctx.quality_review)

        print("  (5.3) 发布门禁（确定性）")

        ctx.release_gate = self.release_gate.run(
            ctx.quality_review
        )
        Output.save("release_gate.json", ctx.release_gate)

        # ==================================================
        # Stage 6: 批量回归（可选，需传 regression_config）
        # ==================================================

        if regression_config:
            print("\n========== Stage 6/6 批量回归 ==========")
            try:
                executed = self.run_execution(regression_config)
                ctx.execution = executed
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ S6 批量回归失败（不影响 S1-S5）：{e}")
                ctx.execution = {"error": str(e)}

        # ==================================================
        # Final
        # ==================================================

        print("\n" + "=" * 60)
        print("========== QA Workflow Finished ==========")
        print("=" * 60)

        print("S1 需求理解   : output/parsed.json, output/facts.json")
        print("S2 需求分析   : output/analysis.json, output/gaps.json")
        print("S3 测试设计   : output/test_design.json")
        print("S4 用例生成   : output/test_cases.json")
        print("S5 用例评审   : output/validation_result.json, "
              "output/quality_review.json, output/release_gate.json")
        if regression_config:
            print("S6 批量回归   : output/execution_result.json")

        return ctx.to_dict()

    def run_execution(self, regression_config) -> dict:
        """S6：批量回归（抓包API回放 + 文档级TC批量 + ADB/UI验证）。

        传入 RegressionConfig 或同形状 dict。产出 output/execution_result.json，
        并返回其中的 report dict。
        """
        from execution.batch_regression import BatchRegressor, RegressionConfig

        cfg = (
            regression_config
            if isinstance(regression_config, RegressionConfig)
            else RegressionConfig(**regression_config)
        )
        # 未显式给定 TC 来源时，默认复用 S4 生成的用例
        if not cfg.tc_cases and not cfg.tc_field:
            cfg.tc_field = "output/test_cases.json#test_cases"

        regressor = BatchRegressor(cfg)
        try:
            report = regressor.run()
            regressor.save_report(report)
        finally:
            regressor.close()

        Output.save("execution_result.json", report.to_dict())
        print("  S6 完成:")
        print("    TC批量   : " + json.dumps(report.summary.get("tc_batch", {}),
                                            ensure_ascii=False))
        print("    API回放  : " + json.dumps(report.summary.get("api_replay", {}),
                                            ensure_ascii=False))
        print("    UI流程   : " + json.dumps(report.summary.get("ui_flow", {}),
                                            ensure_ascii=False))
        return report.to_dict()