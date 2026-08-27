from configs.skills import SKILLS
from utils.skill_engine import SkillEngine

class RequirementAnalysis:

    def run(self, parsed):

        print("========== Requirement Analysis ==========")

        result = SkillEngine.run(
            skill_path=SKILLS["analysis"],
            user_input=parsed,
            schema_path="schema/requirement_analysis.schema.json",
            output_mode="json"
        )

        print("Requirement Analysis 输出完成")

        return result