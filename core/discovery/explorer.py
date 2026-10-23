# -*- coding: utf-8 -*-
"""AppExplorer — S0 App Discovery 探针.

职责：驱动 App 层层下钻，发现「页面 → 容器入口 → 控件 → 业务状态 → 跳转关系」，
并把每一层证据（控件清单、状态模型、截图、uiautomator XML）增量沉淀进 AppKnowledgeBase。

关键设计：Core 不感知具体 App 的业务。所有「怎么走到下一层、怎么识别某类控件、
怎么打开某个入口」的动作，都由项目适配层通过 `Discoverer` 协议注入。
AppExplorer 只负责：递归下钻、去重、防死循环、把结果写回 KV。

探索协议（项目适配层实现）：
    probe_screen():  返回当前页面结构化信息 {name, controls, states, layout, screenshot, entry_points}
                     entry_points = [{key, name, type, how_to_open, reachable}]
                     states = [{name, ui_text, condition, business_code}]
    open_entry(ep):  执行「打开该入口」的动作，返回 True/False
    detect_kind(ep): 用控件特征把入口归类（如 normal_red_packet / world_red_packet）。
                     无匹配则返回 None（由 Explorer 统一归类为 control/container）。

第一版聚焦红包链路：Room → red_packet_entry → [normal/world] → WAITING(倒计时)/OPEN(立即领取)。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from core.discovery.knowledge import AppKnowledgeBase, DiscoveredNode


# ──────────────────────────────────────────────────────────────
# 适配层协议
# ──────────────────────────────────────────────────────────────
class Discoverer(Protocol):
    """项目适配层必须实现的一组【发现动作】。"""

    def name(self) -> str: ...

    def probe_screen(self, source: str) -> dict[str, Any]:
        """探测当前页面。返回 {name, kind_hint, controls[], states[], layout, screenshot}。

        controls = [{rid, text, bounds, clickable, is_entry}]
        states   = [{name, ui_text, condition, business_code}]
        entry_points 额外通过 controls 中 is_entry=True 的项表达。
        """

    def open_entry(self, entry: dict[str, Any], source: str) -> bool:
        """执行打开某入口的动作。成功返回 True。"""


@dataclass
class DiscoveryReport:
    discovered: list[DiscoveredNode] = field(default_factory=list)
    visited: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    depth_reached: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"depth_reached": self.depth_reached,
                "visited": self.visited,
                "discovered_nodes": [n.key for n in self.discovered],
                "skipped": self.skipped}


class AppExplorer:
    """递归下钻式 App 探索器。"""

    def __init__(self, kb: AppKnowledgeBase, discoverer: Discoverer,
                 max_depth: int = 5, max_entries_per_screen: int = 10):
        self.kb = kb
        self.disc = discoverer
        self.max_depth = max_depth
        self.max_entries = max_entries_per_screen
        self._report = DiscoveryReport()
        self._source = ""
        self._opened_centers: set[tuple[int, int]] = set()   # 同一入口坐标只打开一次，防无限下钻
        self._opened_keys: set[str] = set()                  # 同一条关键路径只递归一次

    # ── 主入口 ──────────────────────────────────────────────
    def explore(self, root_key: str, root_name: str, *, source: str = "") -> DiscoveryReport:
        """从根节点（如 Room）开始逐层下钻探索。"""
        self._source = source
        self._report = DiscoveryReport()
        self._opened_centers.clear()
        self._opened_keys.clear()
        root = self.kb.record(
            "screen", root_key, root_name, desc="探索根页面", source=source)
        self._report.discovered.append(root)
        self._walk(root_key, root_name, depth=0)
        return self._report

    # ── 递归下钻 ────────────────────────────────────────────
    def _walk(self, node_key: str, node_name: str, depth: int) -> None:
        if depth >= self.max_depth:
            self._report.depth_reached = max(self._report.depth_reached, depth)
            return

        rec = self.disc  # discoverer
        try:
            probe = rec.probe_screen(self._source)
        except Exception as e:
            self._report.skipped.append(f"{node_key}:probe_failed:{e}")
            return

        screen_name = probe.get("name", node_name)
        screen_kind = probe.get("kind_hint", "screen")
        # 屏幕/容器归 screen/container，其余归 control
        rec_kind = "screen" if screen_kind == "screen" else (
            "container" if screen_kind == "container" else "control")
        controls = probe.get("controls", []) or []
        states = probe.get("states", []) or []
        layout = probe.get("layout", "")
        screenshot = probe.get("screenshot", "")

        # 收敛护栏：本层探测到的入口若全部是上个已打开过的入口（如红包入口在面板层级里反复残留），
        #     说明没有新内容可钻，不再冗余登记一层"同名节点"。
        entries_hint = [c for c in controls if c.get("is_entry")]
        fresh = [c for c in entries_hint
                 if _q(c) and tuple(_q(c)) not in self._opened_centers]
        if depth > 0 and entries_hint and not fresh:
            self._report.skipped.append(f"{node_key}:no_new_entry")
            return

        # 沉淀当前屏幕状态模型
        cur = self.kb.record(
            rec_kind, _key(node_key, screen_name), screen_name,
            parent=node_key,
            controls=self._compact_controls(controls),
            states=states,
            screenshots=[screenshot] if screenshot else [],
            layouts=[layout] if layout else [],
            desc=probe.get("desc", ""),
            extra=probe.get("extra", {}),
            source=self._source,
        )
        if cur.key not in self._report.visited:
            self._report.visited.append(cur.key)
            self._report.discovered.append(cur)
        if node_key:
            self.kb.link(node_key, cur.key)

        # 找到入口点，逐个进入
        entries = entries_hint
        if len(entries) > self.max_entries:
            entries = entries[: self.max_entries]

        for ep in entries:
            center = _q(ep)
            ep_key = _key(cur.key, ep.get("name") or ep.get("rid") or "entry")
            # 同一入口坐标只打开一次：红包入口在面板层级里反复出现，避免无限下钻
            if center and center in self._opened_centers:
                self._report.skipped.append(f"{ep_key}:repeat_entry")
                continue
            # 同一条路径固有 key（如入口名与资源 id 都为空）只递归一次
            if ep_key in self._opened_keys:
                self._report.skipped.append(f"{ep_key}:repeat_key")
                continue
            self._opened_keys.add(ep_key)
            ep_kind = self._classify_entry(ep)
            # 状态模型（如红包的待开奖/可领取）来自 probe 的 states，或由适配层在 entry.extras 给
            ep_states = ep.get("states", [])
            entry_node = self.kb.record(
                ep_kind, ep_key, ep.get("name") or ep.get("rid") or "entry",
                parent=cur.key,
                controls=[self._compact_control(ep)],
                states=ep_states,
                desc=ep.get("desc", ""),
                extra={k: v for k, v in ep.items()
                       if k not in ("rid", "text", "bounds", "clickable", "is_entry",
                                    "name", "states", "desc", "how_to_open")},
                source=self._source,
            )
            self.kb.link(cur.key, entry_node.key)
            if entry_node.key not in self._report.visited:
                self._report.visited.append(entry_node.key)
                self._report.discovered.append(entry_node)
            # 记录跳转
            cur.transitions.append({"target": entry_node.key, "via": "open_entry",
                                    "reason": ep.get("desc", "")})
            self.kb.upsert(cur)

            # 下钻一层
            try:
                ok = rec.open_entry(ep, self._source)
            except Exception:
                ok = False
            if ok:
                if center:
                    self._opened_centers.add(center)
                self._report.depth_reached = max(self._report.depth_reached, depth + 1)
                self._walk(entry_node.key, entry_node.name, depth + 1)
                # 返回本层（若适配层回退，则重新 probe 当前屏幕）
                try:
                    rec.probe_screen(self._source)
                except Exception:
                    pass
            else:
                self._report.skipped.append(f"{ep_key}:open_failed")

    # ── 工具 ────────────────────────────────────────────────
    def _classify_entry(self, ep: dict[str, Any]) -> str:
        """用控件特征把入口归类为 container / control / 具体业务容器。"""
        hint = ep.get("type") or ""
        text = f"{ep.get('text','')} {ep.get('rid','')}".lower()
        if hint:
            return hint
        if any(k in text for k in ("red_packet", "红包", "lucky")):
            return "container"
        return "control"

    @staticmethod
    def _compact_controls(controls: list[dict]) -> list[dict]:
        return [AppExplorer._compact_control(c) for c in controls]

    @staticmethod
    def _compact_control(c: dict) -> dict:
        return {k: c.get(k) for k in ("rid", "text", "bounds", "clickable", "type")
                if k in c and c.get(k) not in (None, "")}


def _key(parent: str, name: str) -> str:
    safe = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in name)
    return f"{parent}/{safe}" if parent else safe


def _q(entry: dict) -> tuple[int, int] | tuple:
    """入口中心量化到 20px，吸附 dump 间动画微抖动，同一入口稳定判重。"""
    c = entry.get("center") if isinstance(entry.get("center"), list) else ()
    return tuple((int(c[0]) // 20, int(c[1]) // 20)) if c else ()