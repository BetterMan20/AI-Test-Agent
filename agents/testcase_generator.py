from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class TestCaseGenerator:

    def run(self, analysis):

        print("========== testcase generator ==========")

        result = SkillEngine.run(
            SKILLS["generation"],
            analysis
        )

        return result