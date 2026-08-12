from utils.skill_loader import load_skill
from utils.llm import ask_llm


class SkillEngine:

    @staticmethod
    def run(skill_path, user_input):

        print("=" * 50)
        print("SkillEngine 启动")

        print(f"Skill 路径：{skill_path}")

        print("① 开始加载 Skill...")
        system_prompt = load_skill(skill_path)
        print("① Skill 加载完成")

        print("② 开始调用 LLM...")
        result = ask_llm(
            system_prompt,
            user_input
        )
        print("② LLM 调用完成")

        print("SkillEngine 完成")
        print("=" * 50)

        return result