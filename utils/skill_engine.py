from utils.skill_loader import load_skill
from utils.llm import ask_llm


class SkillEngine:

    @staticmethod
    def run(skill_path, user_input):

        system_prompt = load_skill(skill_path)

        return ask_llm(
            system_prompt,
            user_input
        )