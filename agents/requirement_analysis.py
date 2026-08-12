from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class RequirementAnalysis:

    def run(self, requirement):

        print("========== Requirement Analysis ==========")
        print("Analysis 输入长度：", len(requirement))

        result = SkillEngine.run(
            SKILLS["analysis"],
            requirement
        )

        print("Analysis 输出长度：", len(result))

        return result