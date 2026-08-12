from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class RequirementParser:

    def run(self, requirement):

        print("========== parser ==========")

        result = SkillEngine.run(
            SKILLS["parser"],
            requirement
        )

        return result