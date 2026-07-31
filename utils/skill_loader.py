from pathlib import Path


def load_skill(skill_path: str) -> str:
    """
    加载 Skill Prompt
    """

    with open(skill_path, "r", encoding="utf-8") as f:
        return f.read()