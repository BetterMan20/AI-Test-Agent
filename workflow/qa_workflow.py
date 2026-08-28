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


class QAWorkflow:

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

    def run(self, requirement):

        ctx = WorkflowContext(requirement)

        print("=" * 60)
        print("========== QA Workflow ==========")
        print("=" * 60)

        # ==================================================
        # Stage 1: Requirement Parser
        # ==================================================

        print("\n========== Stage 1: Requirement Parser ==========")

        ctx.parsed = self.parser.run(ctx.requirement)
        Output.save("parsed.json", ctx.parsed)

        # ==================================================
        # Stage 2: Fact Extraction
        # ==================================================

        print("\n========== Stage 2: Fact Extraction ==========")

        ctx.facts = self.fact_extraction.run(ctx.parsed)
        Output.save("facts.json", ctx.facts)

        # ==================================================
        # Stage 3: Requirement Analysis
        # ==================================================

        print("\n========== Stage 3: Requirement Analysis ==========")

        ctx.analysis = self.analysis.run(ctx.facts)
        Output.save("analysis.json", ctx.analysis)

        # ==================================================
        # Stage 4: Gap Detection
        # ==================================================

        print("\n========== Stage 4: Requirement Gap Detection ==========")

        ctx.gaps = self.gap_detection.run(
            ctx.facts,
            ctx.analysis
        )
        Output.save("gaps.json", ctx.gaps)

        # ==================================================
        # Stage 5: Test Design
        # ==================================================

        print("\n========== Stage 5: Test Design ==========")

        ctx.test_design = self.test_design.run(
            ctx.analysis,
            ctx.gaps
        )
        Output.save("test_design.json", ctx.test_design)

        # ==================================================
        # Stage 6: Test Case Generator
        # ==================================================

        print("\n========== Stage 6: Test Case Generator ==========")

        ctx.test_cases = self.generator.run(ctx.test_design)
        Output.save("test_cases.json", ctx.test_cases)

        # ==================================================
        # Stage 7: Test Case Validator
        # ==================================================

        print("\n========== Stage 7: Test Case Validator ==========")

        ctx.validation = self.validator.run(
            ctx.analysis,
            ctx.test_design,
            ctx.test_cases
        )
        Output.save("validation_result.json", ctx.validation)

        # ==================================================
        # Stage 8: Quality Review
        # ==================================================

        print("\n========== Stage 8: Quality Review ==========")

        ctx.quality_review = self.quality_review.run(
            ctx.facts,
            ctx.analysis,
            ctx.gaps,
            ctx.test_design,
            ctx.test_cases,
            ctx.validation
        )
        Output.save("quality_review.json", ctx.quality_review)

        # ==================================================
        # Stage 9: Release Gate
        # ==================================================

        print("\n========== Stage 9: Release Gate ==========")

        ctx.release_gate = self.release_gate.run(
            ctx.quality_review
        )
        Output.save("release_gate.json", ctx.release_gate)

        # ==================================================
        # Final
        # ==================================================

        print("\n" + "=" * 60)
        print("========== QA Workflow Finished ==========")
        print("=" * 60)

        print("Parsed           : output/parsed.json")
        print("Facts            : output/facts.json")
        print("Analysis         : output/analysis.json")
        print("Gaps             : output/gaps.json")
        print("Test Design      : output/test_design.json")
        print("Test Cases       : output/test_cases.json")
        print("Validation       : output/validation_result.json")
        print("Quality Review   : output/quality_review.json")
        print("Release Gate     : output/release_gate.json")

        return ctx.to_dict()
