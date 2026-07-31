from configs.skills import SKILLS

from utils.skill_engine import SkillEngine


requirement = """
需求：

用户每天签到一次。

签到奖励100金币。

连续签到7天奖励500金币。
"""


analysis = SkillEngine.run(
    SKILLS["analysis"],
    requirement
)

print(analysis)