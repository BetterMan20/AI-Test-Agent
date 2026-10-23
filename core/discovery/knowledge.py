# -*- coding: utf-8 -*-
"""App Knowledge Base — S0 App Discovery 的长期积累库.

目标：把 App 的「页面结构、控件、截图、XML、跳转关系」沉淀成可复用知识，
让测试 Agent 从「会生成用例」迈向「会探索 App」。

存储：文件式 KV。每个对象一目录/一 JSON，目录结构与项目 knowledge/ 平级但独立，
     由 AppKnowledgeBase 统一读写，避免与 whitelist 的 API capability 混在一起。

顶层模型（对应 HIGO 结构，可由 Explorer 逐步增量补全）：

    App
     └─ Room
         ├─ red_packet_entry  (红包入口)
         │    ├─ normal_red_packet  普通红包: WAITING(待开奖→倒计时) / OPEN(可领取→立即领取)
         │    └─ world_red_packet   世界红包: WAITING(待开奖→倒计时) / OPEN(可领取→立即领取)
         ├─ gift_entry
         └─ ...

每个发现对象记示：id、name、type、状态模型、UI 控件、截图、xml、跳转关系、在哪些执行中被发现。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# ──────────────────────────────────────────────────────────────
# 知识对象类型（第一版聚焦红包链路，可扩展）
# ──────────────────────────────────────────────────────────────
OBJ_TYPES = {
    "screen":      "页面/场景",
    "container":   "容器/入口（如红包入口）",
    "control":     "控件（按钮/文本/弹窗）",
    "state":       "业务状态（WAITING/OPEN/COMPLETED/EXPIRED...）",
    "navigation":  "跳转关系（A → B）",
    "screenshot":  "截图证据",
    "layout":      "uiautomator 层级 XML 证据",
}


@dataclass
class DiscoveredNode:
    """一条已发现的知识节点（页面/控件/状态/跳转）。"""
    kind: str                 # screen/container/control/state/navigation
    key: str                  # 唯一标识，如 higo:room:red_packet_entry
    name: str                 # 人类可读名
    obj_type: str = ""        # OBJ_TYPES 映射
    parent: str = ""          # 父节点 key
    desc: str = ""
    # 结构信息
    children: list[str] = field(default_factory=list)
    # UI 控件清单 [{rid, text, bounds, clickable, ...}]
    controls: list[dict[str, Any]] = field(default_factory=list)
    # 状态模型 [{name, ui_text, condition, business_code}]
    states: list[dict[str, Any]] = field(default_factory=list)
    # 跳转 [{target, via, reason}]
    transitions: list[dict[str, Any]] = field(default_factory=list)
    # 证据
    screenshots: list[str] = field(default_factory=list)
    layouts: list[str] = field(default_factory=list)
    # 溯源：在哪次执行/探索中被发现
    sources: list[str] = field(default_factory=list)
    # 元数据
    first_seen: str = ""
    last_seen: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DiscoveredNode":
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


class AppKnowledgeBase:
    """文件式 KV 知识库：按 (app, kind) 分目录，每节点一 JSON。

    目录结构（BASE，默认 knowledge/app_kb/<app>）：
        <kind>/<safe_key>.json        # 每节点
        index.json                    # 全量索引 {kind: {key: meta}}
    """

    def __init__(self, base_dir: str | Path, app: str = "default"):
        self.base = Path(base_dir) / app
        self.base.mkdir(parents=True, exist_ok=True)
        self.app = app
        self._index: dict[str, dict[str, Any]] = self._load_index()

    # ── 路径与索引 ──────────────────────────────────────
    @staticmethod
    def _safe(key: str) -> str:
        return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in key)

    def _node_path(self, kind: str, key: str) -> Path:
        d = self.base / kind
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{self._safe(key)}.json"

    def _load_index(self) -> dict[str, dict[str, Any]]:
        p = self.base / "index.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_index(self) -> None:
        (self.base / "index.json").write_text(
            json.dumps(self._index, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 读写节点 ────────────────────────────────────────
    def _kinds(self) -> list[str]:
        """知识库下所有实际存在的 kind 目录（含自定义 kind，如 normal_red_packet）。"""
        return sorted(p.name for p in self.base.iterdir() if p.is_dir())

    def get(self, key: str) -> DiscoveredNode | None:
        for kind in self._kinds():
            p = self._node_path(kind, key)
            if p.exists():
                try:
                    return DiscoveredNode.from_dict(json.loads(p.read_text(encoding="utf-8")))
                except Exception:
                    return None
        return None

    def upsert(self, node: DiscoveredNode) -> DiscoveredNode:
        """增量合并：已存在则合并 controls/states/transitions/screenshots，否则新建。"""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        existing = self.get(node.key)
        if existing and existing.kind == node.kind:
            node.first_seen = existing.first_seen or now
            node.sources = list(dict.fromkeys(existing.sources + node.sources))
            node.screenshots = list(dict.fromkeys(existing.screenshots + node.screenshots))
            node.layouts = list(dict.fromkeys(existing.layouts + node.layouts))
            # 合并子节点、控件、状态、跳转（按自然去重）
            node.children = list(dict.fromkeys(existing.children + node.children))
            node.controls = self._merge_dicts(existing.controls, node.controls)
            node.states = self._merge_dicts(existing.states, node.states)
            node.transitions = self._merge_dicts(existing.transitions, node.transitions)
        node.last_seen = now
        if not node.first_seen:
            node.first_seen = now
        (self._node_path(node.kind, node.key)).write_text(
            json.dumps(node.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        # 更新索引
        self._index.setdefault(node.kind, {})[node.key] = {
            "name": node.name, "parent": node.parent, "last_seen": node.last_seen}
        self._save_index()
        return node

    @staticmethod
    def _merge_dicts(a: list[dict], b: list[dict]) -> list[dict]:
        seen, out = set(), []
        for it in list(a) + list(b):
            sig = json.dumps(it, ensure_ascii=False, sort_keys=True)
            if sig not in seen:
                seen.add(sig)
                out.append(it)
        return out

    def link(self, parent_key: str, child_key: str) -> None:
        """把 child 挂到 parent 的 children 下（同一节点可被多父引用，按 key 去重）。"""
        parent = self.get(parent_key)
        if parent is None or child_key == parent_key:
            return
        parent.children = list(dict.fromkeys(parent.children + [child_key]))
        self.upsert(parent)

    # ── 便捷发现记录 ────────────────────────────────────
    def record(self, kind: str, key: str, name: str, *, parent: str = "",
               controls: list | None = None, states: list | None = None,
               transitions: list | None = None, screenshots: list | None = None,
               layouts: list | None = None, desc: str = "",
               extra: dict | None = None, source: str = "") -> DiscoveredNode:
        n = DiscoveredNode(
            kind=kind, key=key, name=name, obj_type=OBJ_TYPES.get(kind, ""),
            parent=parent, desc=desc,
            controls=controls or [], states=states or [], transitions=transitions or [],
            screenshots=screenshots or [], layouts=layouts or [], extra=extra or {},
            sources=[source] if source else [],
        )
        return self.upsert(n)

    # ── 查询 ────────────────────────────────────────────
    def subtree(self, root_key: str) -> list[DiscoveredNode]:
        """返回以 root_key 为根的整棵子树（广度优先）。"""
        nodes: list[DiscoveredNode] = []
        seen: set[str] = set()
        queue = [root_key]
        while queue:
            k = queue.pop(0)
            if k in seen:
                continue
            seen.add(k)
            n = self.get(k)
            if n is None:
                continue
            nodes.append(n)
            queue.extend(n.children)
        return nodes

    def find(self, name_substr: str) -> list[DiscoveredNode]:
        out = []
        for kind in self._kinds():
            d = self.base / kind
            if not d.exists():
                continue
            for f in d.glob("*.json"):
                try:
                    node = DiscoveredNode.from_dict(json.loads(f.read_text(encoding="utf-8")))
                except Exception:
                    continue
                if name_substr.lower() in (node.key + node.name + node.desc).lower():
                    out.append(node)
        return out

    def to_tree(self, root_key: str | None = None) -> str:
        """打印知识树（人可读，供 Agent/报告）。"""
        if root_key is None:
            roots = [k for k, meta in self._index.get("screen", {}).items()
                     if not meta.get("parent")]
            root_key = roots[0] if roots else ""
        if not root_key:
            return "(empty kb)"
        from functools import reduce
        def _fmt(n: DiscoveredNode, depth: int) -> str:
            pad = "  " * depth
            lines = [f"{pad}▸ [{n.kind}] {n.name}  ({n.key})"]
            for st in n.states:
                lines.append(f"{pad}    · 状态 {st.get('name')}: UI={st.get('ui_text')} "
                             f"业务={st.get('condition')} code={st.get('business_code')}")
            for tr in n.transitions:
                lines.append(f"{pad}    → {tr.get('target')} via {tr.get('via')}")
            return lines
        lines: list[str] = []
        def _walk(k: str, depth: int):
            n = self.get(k)
            if n is None:
                return
            lines.extend(_fmt(n, depth))
            for c in n.children:
                _walk(c, depth + 1)
        _walk(root_key, 0)
        return "\n".join(lines)