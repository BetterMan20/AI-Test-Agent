from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class RequirementParser:

    def run(self, requirement):

        print("========== Requirement Parser ==========")

        result = SkillEngine.run(
            skill_path=SKILLS["parser"],
            user_input=requirement,
            output_mode="text"
        )

        print(
            "Requirement Parser 输出完成"
        )

        return result