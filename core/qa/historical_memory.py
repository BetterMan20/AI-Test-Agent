# -*- coding: utf-8 -*-
"""core.qa.historical_memory — C 模块：历史质量知识 → 找风险 的记忆与反推。

跨轮闭环：每轮 learn() 把新一致性违例追加进 historical.yaml；下一轮 run() 开头重新加载，
risk() 就能看到"这里以前出过这类 bug"，并用 LLM 把历史 bug 模式反推成新一轮风险点。

本模块提供：
  1) render_historical_memory(historical, domain) → 人类可读的历史记忆块（供 LLM 注入）；
  2) llm_augment_risks(...) → 让 LLM 基于历史记忆反推/补齐风险点；失败/未开启时返回 []，
     保持规则兜底（attack_paths + historical 天然展开），不打断循环。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from utils.llm import ask_llm
from utils.skill_engine import SkillEngine  # 复用统一 JSON 卫生规则


def render_historical_memory(historical: list[dict] | None, domain: str = "",
                             max_items: int = 12) -> str:
    """把历史质量知识渲染成一段「已发生过 bug」的记忆文本。"""
    items = [h for h in (historical or []) if not domain or h.get("domain") == domain]
    if not items:
        return "（本域暂无历史质量记录）"
    lines = [
        "【历史质量记忆 —— 本业务域真实出过的 bug，找风险时对号入座，别再踩同坑】",
        f"共 {len(items)} 条历史违例；时间新→旧：", "",
    ]
    for h in items[-max_items:][::-1]:
        lines.append(f"- [{h.get('id')}][{h.get('at', '')}] "
                     f"{h.get('bug_brief', '').strip()}")
        if h.get("semantics"):
            lines.append(f"    业务态={h.get('semantics')} | "
                         f"期望UI={h.get('expected_ui')} → 实际UI={h.get('observed_ui')} "
                         f"(room {h.get('room', '?')})")
    return "\n".join(lines)


_TASK_PROMPT = r"""你是移动端状态一致性 QA 的风险反推参谋。
输入给出：当前业务的状态模型、已有的候选风险点、以及本业务域的历史质量记忆。
你的任务：从历史 bug 的规律反推出【新增/收敛出】更聚焦的风险点，帮下次测试命中同类问题。
只输出一个 JSON 对象（不要 Markdown 围栏、不要多余文字），字段：
{
  "augmented_risks": [
    {
      "id": "R-H-##",            // 编号
      "name": "风险点名称",
      "condition": "触发该风险的业务条件",
      "related_history_id": 数字,  // 反推自哪条历史；无则 0
      "reason": "为何这是风险（源于哪条历史 bug 的哪个规律）"
    }
  ]
}
约束：
- augmented_risks 必须是【新】风险点，不要重复已有风险；related_history_id 要真实引用给出的历史 id。
- 聚焦状态一致性：UI 显示状态 × 业务状态(status/open_at/server_time) × 状态刷新之间的错位。
"""


def _clean_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text


# ── 历史去重：按"根因类别 + 观测形态 + 房间"归并，避免同根因因 phase 推断不同被拆散 ──

def violation_category(violations, brief: str = "") -> str:
    """把违例描述归到少数稳定类别（用于去重键；phase 是推断值，不作键）。"""
    txt = " ".join(str(x) for x in (violations or [])) or str(brief or "")
    if "不在状态模型" in txt or ("状态模型" in txt and "不在" in txt):
        return "BAD_STATUS_VALUE"
    if "不一致" in txt or "期望" in txt or "互斥" in txt or "错位" in txt:
        return "UI_BUSINESS_MISMATCH"
    if "瞬态" in txt or "网络" in txt or "超时" in txt:
        return "TRANSIENT"
    if not txt.strip() or "无数值" in txt or "NO_LIVE" in txt:
        return "NO_LIVE_NUMBERS"
    return "OTHER"


def history_key(item: dict) -> tuple:
    """去重键：domain + room + observed_ui + 根因类别。
    刻意不使用 phase（它是从 status/open_at 推断出的展示阶段，同一根因可能被推成不同 phase）。"""
    return (item.get("domain", ""), str(item.get("room", "")),
            str(item.get("observed_ui", "")),
            violation_category(item.get("violations"), item.get("bug_brief")))


def dedup_items(items: list[dict]) -> list[dict]:
    """存量清理：语义键去重，冲突时保留明细更全的一条。"""
    seen: dict[tuple, dict] = {}
    order: list[tuple] = []
    for it in items:
        key = history_key(it)
        if key not in seen:
            seen[key] = it
            order.append(key)
            continue
        cur = seen[key]
        # 保留"明细更全 / 更新"的一条：violations 更多 或 时间更新
        cur_n = len(" ".join(str(x) for x in cur.get("violations", [])))
        it_n = len(" ".join(str(x) for x in it.get("violations", [])))
        if it_n > cur_n or (it_n == cur_n and it.get("at", "") > cur.get("at", "")):
            seen[key] = it
    # 稳定重编号 id
    out: list[dict] = []
    for i, key in enumerate(order, 1):
        it = dict(seen[key])
        it["id"] = i
        it["violation_category"] = violation_category(it.get("violations"), it.get("bug_brief"))
        out.append(it)
    return out


def dedup_historical_file(path) -> tuple[int, int]:
    """清理 historical.yaml 存量；返回 (清理前, 清理后) 条数。"""
    import yaml
    p = Path(path)
    if not p.exists():
        return 0, 0
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    items = data.get("items", []) if isinstance(data, dict) else []
    before = len(items)
    cleaned = dedup_items(items)
    p.write_text(yaml.safe_dump({"items": cleaned}, allow_unicode=True,
                                sort_keys=False), encoding="utf-8")
    return before, len(cleaned)


def llm_augment_risks(model: dict, *, historical_memory: str = "",
                      existing_risks: list[dict] | None = None,
                      use_llm: bool = True) -> list[dict]:
    """基于历史记忆反推新风险点；未开启/失败返回 []。"""
    if not use_llm:
        return []
    data = {
        "state_model": model.get("state_model", {}),
        "existing_risks": existing_risks or [],
        "historical_memory": (historical_memory or "")[:4000],
    }
    user_prompt = "当前状态模型/已有风险/历史记忆如下（JSON）：\n" + \
        json.dumps(data, ensure_ascii=False)
    try:
        result, _usage = ask_llm(_TASK_PROMPT + SkillEngine._JSON_HYGIENE_RULE,
                                 user_prompt, return_usage=True, max_tokens=4000)
        obj = json.loads(_clean_json(result))
        risks = obj.get("augmented_risks", []) if isinstance(obj, dict) else []
    except Exception:
        return []
    out: list[dict] = []
    for r in risks:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        existing_ids = {x.get("id") for x in (existing_risks or [])}
        if r.get("id") in existing_ids:
            continue
        out.append({"id": r.get("id", f"R-H-{len(out) + 1}"),
                    "name": r["name"], "condition": r.get("condition", ""),
                    "related_history_id": r.get("related_history_id", 0),
                    "reason": r.get("reason", ""),
                    "source": "historical-llm"})
    return out