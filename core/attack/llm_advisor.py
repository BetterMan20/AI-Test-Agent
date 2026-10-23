# -*- coding: utf-8 -*-
"""core.attack.llm_advisor — B 模块：LLM 驱动攻击决策层。

让 LLM 在「状态模型 + 攻击路径 + 真机系统事实(KB) + 历史质量知识 + 实时观测」
之上做两件事，引擎只负责执行：
  1) 选路径/定优先级：从候选 attack_paths 中挑出最值得攻击的，并给出理由；
  2) 定判定边界：给「哪种观测算真违例、哪种算允许的瞬态」一个策略，
     引擎据此在验证时对观测做解释性标注。

健壮性：LLM 解析失败/超时一律回退到「全部可执行路径」，绝不因 LLM 抖动打断 QA 循环。
"""
from __future__ import annotations

import json
import re
from typing import Any

from utils.llm import ask_llm
from utils.skill_engine import SkillEngine  # 复用统一的 JSON 卫生规则

_TASK_PROMPT = r"""你是移动端状态一致性攻击的决策参谋。
输入给定：状态模型、候选攻击路径、真机系统事实、历史质量知识、实时观测摘要。
请只输出一个 JSON 对象（不要 Markdown 围栏、不要多余文字），字段：
{
  "selected_paths": [字符串, 按攻击价值从高到低排列的路径 id 子集],
  "focus_dimensions": ["攻击应聚焦的一致性维度，如 status/open_at/server_time/ui_state/state_refresh"],
  "verdict_policy": {
      "explain": "把哪种观测判为真违例、哪种允许为瞬态的一句话依据",
      "trust_observed_ui_only": bool  // 是否宁信真机观测、暂缓无数值的判定
  },
  "per_path": { "路径id": {"reason": "选/不选它的理由", "rank": 数字, "primitives": ["只有清单里存在的原语id，按执行顺序"]} }
}
约束：
- selected_paths 只能从给出的 attack_paths 里挑选，不要发明新 id。
- per_path[path].primitives 只能取 reachable_primitives 清单里真实存在的原语 id，
  且应能完成该路径的扰动（先扰动→再读状态）；若该路径没有可用原语就留空数组。
"""


def _clean_json(text: str) -> str:
    text = text.strip()
    # 去掉可能的 ```json ... ``` 围栏
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text


def decide_attack(model: dict, *, system_facts: str = "",
                  historical: list[dict] | None = None,
                  observations: list[dict] | None = None,
                  reachable_primitives: list[dict] | None = None,
                  use_llm: bool = True) -> dict:
    """LLM 决策；use_llm=False 或 LLM 失败时回退全部可执行路径。"""
    paths = model.get("attack_paths", [])
    executable = [p.get("id") for p in paths if p.get("executable", True)]
    prim_ids = {p.get("id") for p in (reachable_primitives or [])}
    fallback = {
        "selected_paths": executable,
        "focus_dimensions": model.get("consistency_invariant", {}).get("dimensions", []),
        "verdict_policy": {"explain": "回退策略：默认执行全部可执行路径，观测按状态模型严格一致判定",
                           "trust_observed_ui_only": False},
        "per_path": {pid: {"reason": "fallback", "rank": i + 1, "primitives": []}
                     for i, pid in enumerate(executable)},
        "reachable": (reachable_primitives or []),
        "llm_used": False,
        "source": "fallback",
    }
    if not use_llm:
        return fallback

    data = {
        "state_model": {k: v for k, v in model.get("state_model", {}).items()},
        "attack_paths": [
            {k: p.get(k) for k in ("id", "name", "condition", "expected",
                                   "priority", "executable", "actions")}
            for p in paths
        ],
        "reachable_primitives": reachable_primitives or [],
        "system_facts": (system_facts or "")[:4000],
        "historical": (historical or [])[:8],
        "live_observations": (observations or [])[:20],
    }
    user_prompt = "状态模型/攻击路径/可执行原语/系统事实/历史/实时观测如下（JSON）：\n" + \
        json.dumps(data, ensure_ascii=False)

    try:
        result, _usage = ask_llm(_TASK_PROMPT + SkillEngine._JSON_HYGIENE_RULE,
                                 user_prompt, return_usage=True, max_tokens=8000)
        decision = json.loads(_clean_json(result))
        if not isinstance(decision, dict):
            raise ValueError("not dict")
    except Exception as e:
        decision = dict(fallback)
        decision["llm_error"] = str(e)
        decision["source"] = "fallback:llm-failed"
        return decision

    # 规整：selected_paths 只能是可执行子集，保留给定顺序
    sel = [pid for pid in decision.get("selected_paths", []) if pid in set(executable)]
    if not sel:
        sel = executable
    per = {}
    for i, pid in enumerate(sel):
        info = decision.get("per_path", {}).get(pid, {}) or {}
        prims = [x for x in info.get("primitives", []) if x in prim_ids][:8]
        per[pid] = {"reason": info.get("reason", ""), "rank": i + 1,
                    "primitives": prims}
    return {
        "selected_paths": sel,
        "focus_dimensions": decision.get("focus_dimensions", fallback["focus_dimensions"]),
        "verdict_policy": decision.get("verdict_policy", fallback["verdict_policy"]),
        "per_path": per,
        "reachable": reachable_primitives or [],
        "llm_used": True,
        "source": "llm",
    }