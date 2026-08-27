from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class TestCaseValidator:

    def run(self, requirement_analysis, test_design, test_cases):

        print("========== Test Case Validator ==========")

        validator_input = {
            "requirement_analysis": requirement_analysis,
            "test_design": test_design,
            "test_cases": test_cases
        }

        return SkillEngine.run(
            skill_path=SKILLS["validation"],
            user_input=validator_input,
            schema_path="schema/validation_result.schema.json",
            output_mode="json"
        )