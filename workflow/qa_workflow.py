from agents.requirement_parser import RequirementParser
from agents.requirement_analysis import RequirementAnalysis
from agents.test_design import TestDesign
from agents.testcase_generator import TestCaseGenerator
from agents.testcase_validator import TestCaseValidator

from utils.output import Output


class QAWorkflow:

    def __init__(self):

        self.parser = RequirementParser()
        self.analysis = RequirementAnalysis()
        self.test_design = TestDesign()
        self.generator = TestCaseGenerator()
        self.validator = TestCaseValidator()

    def run(self, requirement):

        print("=" * 60)
        print("========== QA Workflow ==========")
        print("=" * 60)

        # ==================================================
        # Step 1
        # ==================================================

        print(
            "\n========== Step 1: Requirement Parser =========="
        )

        parsed = self.parser.run(
            requirement
        )

        Output.save(
            "parsed.json",
            parsed
        )

        # ==================================================
        # Step 2
        # ==================================================

        print(
            "\n========== Step 2: Requirement Analysis =========="
        )

        analysis = self.analysis.run(
            parsed
        )

        Output.save(
            "analysis.json",
            analysis
        )

        # ==================================================
        # Step 3
        # ==================================================

        print(
            "\n========== Step 3: Test Design =========="
        )

        test_design = self.test_design.run(
            analysis
        )

        Output.save(
            "test_design.json",
            test_design
        )

        # ==================================================
        # Step 4
        # ==================================================

        print(
            "\n========== Step 4: Test Case Generator =========="
        )

        test_cases = self.generator.run(
            test_design
        )

        Output.save(
            "test_cases.json",
            test_cases
        )

        # ==================================================
        # Step 5
        # ==================================================

        print(
            "\n========== Step 5: Test Case Validator =========="
        )

        validation = self.validator.run(
            analysis,
            test_design,
            test_cases
        )

        Output.save(
            "validation_result.json",
            validation
        )

        # ==================================================
        # Final
        # ==================================================

        print("\n" + "=" * 60)
        print("========== QA Workflow Finished ==========")
        print("=" * 60)

        print(
            "Parsed           : output/parsed.json"
        )

        print(
            "Analysis         : output/analysis.json"
        )

        print(
            "Test Design      : output/test_design.json"
        )

        print(
            "Test Cases       : output/test_cases.json"
        )

        print(
            "Validation       : output/validation_result.json"
        )

        return {

            "parsed":
                parsed,

            "analysis":
                analysis,

            "test_design":
                test_design,

            "test_cases":
                test_cases,

            "validation":
                validation
        }