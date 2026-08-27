from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class TestCaseGenerator:

    def run(self, design):

        print("========== Test Case Generator ==========")

        return SkillEngine.run(
            SKILLS["generation"],
            design,
            "schema/test_case.schema.json",
            output_mode="json"
        )