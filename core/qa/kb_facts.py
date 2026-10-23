# -*- coding: utf-8 -*-
"""core.qa.kb_facts — 把 App Knowledge Base 渲染成 LLM 可消费的「系统事实」片段。

A 模块：让 LLM 在 fact_extraction / test_design 阶段就能"看到"真机探索到的
动态系统结构（页面/控件/状态/跳转），而非只读静态需求文本。

反幻觉约束：仅输出 KB 里真实落库的观测；模型声明但未观测的节点明确标注
「声明未观测」，交由 LLM 自行区分事实与推断。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.discovery.knowledge import AppKnowledgeBase


@dataclass
class SystemFacts:
    domain: str
    room: str
    block: str
    node_count: int = 0
    observed_states: int = 0

    def to_dict(self) -> dict:
        return {"domain": self.domain, "room": self.room, "node_count": self.node_count,
                "observed_states": self.observed_states, "block": self.block}


def _key_to_room(key: str, room: str | None) -> bool:
    if not room:
        return True
    return room in key


def build_system_facts(kb: AppKnowledgeBase, *, domain: str = "",
                       room: str | None = None,
                       max_chars: int = 6000) -> SystemFacts:
    """收集 KB 中属于该域/房间的节点，渲染成一段受控长度的系统事实块。"""
    lines: list[str] = [
        "【真机已探测的系统事实 —— 权威，优先于任何推断】",
        "来源: App Knowledge Base（S0 探索 + 执行回填，长期积累）",
        "",
    ]
    node_count = 0
    observed = 0
    for kind, nodes in getattr(kb, "_index", {}).items():
        for key, meta in nodes.items():
            if not _key_to_room(key, room):
                continue
            node = kb.get(key)
            if not node:
                continue
            node_count += 1
            st_desc = []
            for st in node.states or []:
                mark = "(实测)" if st.get("observed_now") else "(声明)"
                if st.get("observed_now") and st.get("business_code") is not None:
                    observed += 1
                ui = st.get("ui_text") or st.get("name")
                con_ = st.get("condition") or ""
                st_desc.append(f"   - {st.get('name')}: UI={ui} {mark} {con_}")
            lines.append(f"- [{node.kind}] {node.name}  key={node.key}")
            lines.extend(st_desc if st_desc else ["   - (无状态)"])
            for c in node.controls or []:
                pass  # controls 已含在 states/跳转里表达，避免过长
            if node.transitions:
                tgt = ", ".join(t.get("target") for t in node.transitions[:5])
                lines.append(f"   → 跳转: {tgt}")
            lines.append("")
    sf = SystemFacts(domain=domain, room=room or "", block="", node_count=node_count,
                     observed_states=observed)
    block = "\n".join(lines)
    sf.block = block if len(block) <= max_chars else block[:max_chars] + "\n…(截断)"
    return sf


def render_system_facts(kb: AppKnowledgeBase, *, domain: str = "", room: str | None = None,
                        max_chars: int = 6000) -> str:
    """便捷：直接得到一字不用再贴的 system_facts 文本块。"""
    sf = build_system_facts(kb, domain=domain, room=room, max_chars=max_chars)
    return sf.block