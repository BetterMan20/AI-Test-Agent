from pathlib import Path

# 技能路径(SKILLS)存的是相对路径，锚定到项目根，避免依赖运行时工作目录(cwd)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_skill(skill_path: str) -> str:
    """
    加载 Skill Prompt
    """

    p = Path(skill_path)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    with open(p, "r", encoding="utf-8") as f:
        return f.read()