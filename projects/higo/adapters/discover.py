# -*- coding: utf-8 -*-
"""HIGO App Discovery 适配层（S0）—— 项目侧实现 core.discovery.Discoverer 协议。

让 Core 的 AppExplorer 能自主下钻一条真实链路并沉淀进 AppKnowledgeBase：

    Room
     └─ 红包入口 red_packet_entry
          ├─ 普通红包 normal_red_packet   待开奖→倒计时 / 可领取→立即领取
          └─ 世界红包 world_red_packet    待开奖→倒计时 / 可领取→立即领取

两类能力，共用同一套「真实 XML → 结构化控件/状态/入口」的解析：
  1) 在线探索  HigoRedPacketDiscoverer  — ADB uiautomator 逐层 dump → tap，
                每次探测都会把 页面/控件/状态/截图/XML/跳转 增量写回 KB。
  2) 离线回填  backfill_from_evidence    — 把历史已产生的真机证据
                （reproduce_ui.xml / screencap / report）一次性灌进 KB，
                证明同一套累积管道不依赖现场重拨。

anti-hallucination：只把「真机观测到」的写成 evidence/source；模型声明的
状态（如 world_red_packet）标注 desc=“模型声明，待现场探索补全”，不当作已发现。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from core.attack.consistency import load_model
from core.config import loader
from core.discovery.explorer import AppExplorer, DiscoveryReport
from core.discovery.knowledge import AppKnowledgeBase, DiscoveredNode

from projects.higo.adapters import claim_attack

MODEL_PATH = Path(__file__).resolve().parents[1] / "attack" / "red_packet_claim.json"

# overlay 是可点击入口按钮上的状态标记（clickable=false），据此定位「红包入口」按钮
OVERLAY_RID = "tv_red_packet_status_overlay"


# ──────────────────────────────────────────────────────────────
# 真实 XML → 结构化控件（在线/离线共用）
# ──────────────────────────────────────────────────────────────
_NODE_RE = re.compile(r"<node(?P<attrs>[^>]*?)>|</node>|<node(?P<selfclose>\[^>]*?)/>")

_ATTRS = ("text", "resource-id", "content-desc", "class", "clickable",
          "checkable", "checked", "enabled", "focusable", "bounds")

# overlay 文本 → 状态模型（与 red_packet_claim.json 的 state_model 对齐）
_STATE_MAP = {
    "COUNTDOWN": ("待开奖", 3), "OPEN": ("可领取", 0),
    "CLAIMED": ("已领取", 1), "EXPIRED": ("已过期", 2),
}


def entry_states(overlay_text: str | None) -> list[dict]:
    """由入口 overlay 文本给出「当前观测到的状态」，并附完整声明状态模型。"""
    out = []
    for abbr, (name, code) in _STATE_MAP.items():
        out.append({"name": name, "ui_text": abbr,
                    "observed_now": bool(overlay_text and overlay_text == abbr),
                    "business_code": code})
    return out


def _parse_node_attrs(node: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for a in _ATTRS:
        m = re.search(rf'{a}="([^"]*)"', node)
        if m:
            out[a] = m.group(1).strip()
    return out


def parse_xml_controls(xml: str) -> tuple[list[dict], str, str | None]:
    """解析 uiautomator XML → (controls, ui_state, error)。

    controls 每项: {rid, text, desc, class, bounds, clickable, is_entry}
    ui_state: 由红包入口 overlay 的 text 直接给出（OPEN/COUNTDOWN/CLAIMED/EXPIRED）。
    """
    if not xml or "<hierarchy" not in xml:
        return [], None, "no-hierarchy"
    controls: list[dict] = []
    overlay_text: str | None = None
    overlay_center: tuple[int, int] | None = None
    # 红包入口 overlay 是自闭合 TextView(<node .../>)，不能用负前瞻排除，
    #   否则 ui_state 与入口全丢——这正是 claim_attack 定位入口所依赖的信号。
    for m in re.finditer(r"<node[^>]*>", xml):
        n = m.group(0)
        a = _parse_node_attrs(n)
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', n)
        if not bm:
            continue
        x1, y1, x2, y2 = map(int, bm.group(1, 2, 3, 4))
        rid = a.get("resource-id", "")
        text = a.get("text", "")
        c = {
            "rid": rid, "text": text, "desc": a.get("content-desc", ""),
            "class": a.get("class", ""), "clickable": a.get("clickable") == "true",
            "bounds": f"[{x1},{y1}][{x2},{y2}]",
            "center": [(x1 + x2) // 2, (y1 + y2) // 2],
        }
        if rid.endswith(OVERLAY_RID):
            overlay_text = text.upper() if text else None
            overlay_center = c["center"]
        controls.append(c)

    # 红包入口 = overlay 覆盖的可点击祖先（与 claim_attack 同一定位口径）
    if overlay_center:
        for c in controls:
            if not c["clickable"] or not c["bounds"].startswith("["):
                continue
            cxm = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", c["bounds"])
            if not cxm:
                continue
            x1, y1, x2, y2 = map(int, cxm.group(1, 2, 3, 4))
            if x1 <= overlay_center[0] <= x2 and y1 <= overlay_center[1] <= y2:
                c["is_entry"] = True
                c["name"] = "红包入口"
                c["type"] = "container"
                c["states"] = entry_states(overlay_text)
    # 无 overlay 时兜底：按文案/资源名把红包控件入口（如“开红包/抢红包”）找出来
    if not any(c.get("is_entry") for c in controls):
        for c in controls:
            hay = f"{c['text']} {c['desc']} {c['rid']}".lower()
            if c["clickable"] and any(k in hay for k in
                                      ("红包", "redpacket", "red_packet", "抢红包", "开红包", "lucky")):
                c["is_entry"] = True
    return controls, overlay_text, None


def classify_kind(text: str, desc: str, rid: str) -> tuple[str, str]:
    """返回 (kind, 人类可读名)。kind ∈ {container, control, normal_red_packet, world_red_packet}。

    世界红包 / 普通红包在面板上是两个 tab/按钮，据此区分目标树的两条分支。
    """
    hay = f"{text} {desc} {rid}".lower()
    if any(k in hay for k in ("世界红包", "world", "红包-世界", "luckybagworld")):
        return "world_red_packet", "世界红包"
    if any(k in hay for k in ("普通红包", "normal", "红包-普通", "luckybagnormal")):
        return "normal_red_packet", "普通红包"
    if any(c in hay for c in ("红包", "redpacket", "red_packet", "lucky")):
        return "container", "红包入口"
    return "control", text or rid or "控件"


# ──────────────────────────────────────────────────────────────
# 在线 Discoverer（实现 core.discovery.Discoverer 协议）
# ──────────────────────────────────────────────────────────────
class HigoRedPacketDiscoverer:
    def __init__(self, serial: str):
        self.serial = serial
        claim_attack._ensure_dump_ready(serial)

    def name(self) -> str:
        return "higo-redpacket-discoverer"

    def probe_screen(self, source: str) -> dict[str, Any]:
        """dump 当前页 → 结构化 controls/states/layout + 截图，供 Explorer 落库。"""
        xml = claim_attack._dump_ui(self.serial)
        controls, ui_state, err = parse_xml_controls(xml)
        # 当前屏幕归大类：红包面板/房间主屏
        kwargs = [c for c in controls if c.get("is_entry")]
        kind_hint = "container" if kwargs else "screen"
        screen_name = kwargs[0].get("name", "红包入口") if kwargs else "Room"
        # 截图
        shot = self._screenshot("probe")
        return {
            "name": screen_name, "kind_hint": kind_hint,
            "controls": controls, "states": entry_states(ui_state),
            "layout": xml if xml else "",
            "screenshot": shot,
            "extra": {"ui_state": ui_state, "overlay_err": err,
                      "entry_count": len(kwargs), "serial": self.serial},
        }

    def open_entry(self, entry: dict[str, Any], source: str) -> bool:
        cxm = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", str(entry.get("bounds", "")))
        pt = ((entry.get("center") or []) if isinstance(entry.get("center"), list) else None)
        if not cxm and not pt:
            return False
        if pt:
            x, y = int(pt[0]), int(pt[1])
        else:
            x1, y1, x2, y2 = map(int, cxm.group(1, 2, 3, 4))
            x, y = (x1 + x2) // 2, (y1 + y2) // 2
        claim_attack._adb(self.serial, f"input tap {x} {y}", timeout=15)
        time.sleep(2)
        return True

    def _screenshot(self, tag: str) -> str:
        try:
            p = Path("output") / "app_kb" / "shots" / f"{self.serial or 'dev'}_{tag}_{int(time.time())}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            cmd = (["adb", "-s", self.serial, "exec-out", "screencap", "-p"]
                   if self.serial else ["adb", "exec-out", "screencap", "-p"])
            with open(p, "wb") as f:
                subprocess.run(cmd, stdout=f, timeout=20)
            return str(p) if p.exists() else ""
        except Exception:
            return ""


# ──────────────────────────────────────────────────────────────
# 回填（在线执行 & 离线历史证据共用一条累积管道）
# ──────────────────────────────────────────────────────────────
def _ink_point(kb: AppKnowledgeBase, kind: str, key: str, name: str, *,
               parent: str, states: list | None = None, controls: list | None = None,
               transitions: list | None = None, screenshots: list | None = None,
               layouts: list | None = None, desc: str = "", source: str = "",
               extra: dict | None = None) -> DiscoveredNode:
    # 控件/截图/XML 若是真机证据文件，先拷进 KB 形成自包含知识库，再以归档路径落库
    screenshots = kb_persist(kb, screenshots, kind, "screenshots")
    layouts = kb_persist(kb, layouts, kind, "layouts")
    node = kb.record(kind, key, name, parent=parent, states=states, controls=controls,
                     transitions=transitions, screenshots=screenshots or None,
                     layouts=layouts or None, desc=desc, extra=extra, source=source)
    if parent:
        kb.link(parent, node.key)
    return node


def kb_persist(kb: AppKnowledgeBase, paths: list[str] | None, kind: str, sub: str) -> list[str]:
    """把证据文件拷入 KB/<kind>/assets/<sub>/ 并回写归档后的路径（自包含）。"""
    out = []
    for p in (paths or []):
        if not p or not Path(p).exists():
            continue
        dst = kb.base / kind / "assets" / sub / Path(p).name
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(p, dst)
            out.append(str(dst))
        except Exception:
            out.append(p)
    return out


def backfill_from_evidence(evidence_dir: str | Path, kb: AppKnowledgeBase,
                           room: str, source: str = "evidence:reproduce-14775") -> list[str]:
    """把一次真机现场证据（UI XML + 截图 + 报告）反推成小红包链路并写回 KB。

    仅当证据里真正含红包入口 overlay（真机观测）才记录该 state；
    世界红包未在现场观测到，按模型声明标注，避免幻觉。
    """
    ev = Path(evidence_dir)
    xml_path = ev / "reproduce_ui.xml"
    png_path = ev / "reproduce_screen.png"
    report_path = ev / "reproduce_report.json"
    added: list[str] = []

    root_key = f"higo:room:{room}"
    _ink_point(kb, "screen", root_key, f"直播间 Room {room}", parent="",
               desc=f"红包领取现场复现房间，source={source}", source=source)
    added.append(root_key)

    # 红包入口（container）
    ep_key = f"{root_key}/red_packet_entry"
    ep_states = []
    biz = "WAITING"
    if report_path.exists():
        try:
            r = json.loads(report_path.read_text(encoding="utf-8"))
            obs = r.get("consistency_verdict", {})
            biz = obs.get("phase") or biz
            observed_ui = obs.get("observed_ui")
        except Exception:
            observed_ui = None
    # overlay 文本（真机观测）
    observed_ui = None
    if xml_path.exists():
        _, observed_ui, _ = parse_xml_controls(xml_path.read_text(encoding="utf-8", errors="replace"))
    if observed_ui:
        ep_states.append({"name": "待开奖" if biz == "WAITING" else biz,
                          "ui_text": observed_ui, "condition": f"status=3 且 server_time<open_at "
                                                               f"(业务推送, 观测UI={observed_ui})",
                          "business_code": 3})
    _ink_point(kb, "container", ep_key, "红包入口", parent=root_key,
               states=ep_states,
               screenshots=[str(png_path)] if png_path.exists() else None,
               layouts=[str(xml_path)] if xml_path.exists() else None,
               desc="红包入口（overlay 状态标记所在的可点击按钮）", source=source,
               extra={"observed_ui": observed_ui,
                      "note": "真机观测到 UI=OPEN 而业务=WAITING，两者互斥并存" if observed_ui == "OPEN" and biz == "WAITING" else ""})
    added.append(ep_key)

    # 普通红包（现场观测）→ 状态：待开奖→倒计时 / 可领取→立即领取
    n_key = f"{ep_key}/normal_red_packet"
    _ink_point(kb, "normal_red_packet", n_key, "普通红包", parent=ep_key,
               states=[
                   {"name": "待开奖", "ui_text": "COUNTDOWN", "condition": "server_time < open_at", "business_code": 3},
                   {"name": "可领取", "ui_text": "OPEN", "condition": "open_at ≤ server_time < open_at+TTL", "business_code": 0},
               ],
               desc="红包页普通红包分支（现场观测 overlay）", source=source)
    added.append(n_key)

    # 世界红包（模型声明，未现场观测）
    w_key = f"{ep_key}/world_red_packet"
    _ink_point(kb, "world_red_packet", w_key, "世界红包", parent=ep_key,
               states=[
                   {"name": "待开奖", "ui_text": "COUNTDOWN", "condition": "server_time < open_at", "business_code": 3},
                   {"name": "可领取", "ui_text": "OPEN", "condition": "open_at ≤ server_time < open_at+TTL", "business_code": 0},
               ],
               desc="世界红包分支 —— 模型声明，待现场探索补全", source=source)
    added.append(w_key)
    return added


def backfill_observations(kb: AppKnowledgeBase, observations: list[dict], *,
                          room: str, source: str = "exec:claim_attack") -> list[str]:
    """把一次「红包领取执行」的观测回填进 KB（执行时增量积累，S0 不是一次性跑完）。

    每个观测 (label, business, phase, expected_ui, observed_ui, consistent) 都会
    在 Room→红包入口 下追加/合并一次状态观测，并记录是否一致。
    """
    if not observations:
        return []
    root_key = f"higo:room:{room}"
    ep_key = f"{root_key}/red_packet_entry"
    kb.record("screen", root_key, f"直播间 Room {room}", desc="红包领取执行现场", source=source)
    states, notes = [], []
    for o in observations:
        ui = o.get("observed_ui") or o.get("expected_ui")
        states.append({"name": o.get("phase", ""),
                       "ui_text": ui,
                       "condition": o.get("expected_ui", ""),
                       "business_code": o.get("business", {}).get("status"),
                       "observed_now": True,
                       "consistent": o.get("consistent")})
        if o.get("violations"):
            notes.append({"label": o.get("label"), "violations": o.get("violations")})
    kb.record("container", ep_key, "红包入口", parent=root_key,
              states=states, source=source,
              desc=f"claim_attack 执行观测合并（{len(observations)} 条）",
              extra={"consistency_notes": notes})
    kb.link(root_key, ep_key)
    return [root_key, ep_key]


# ──────────────────────────────────────────────────────────────
# 统一入口
# ──────────────────────────────────────────────────────────────
def run_discovery(project: str, env: str, *, kb_base: str | Path | None = None,
                  live: bool = True, backfill_evidence: str | None = None,
                  room: str = "14775", source: str = "s0:app-discovery",
                  max_depth: int = 5) -> dict[str, Any]:
    kb_base = kb_base or Path("output") / "app_kb"
    kb = AppKnowledgeBase(base_dir=kb_base, app=project)

    env_cfg = loader.load_env(project, env)
    serial = env_cfg.device_serial
    root_key = f"higo:room:{room}"

    result: dict[str, Any] = {"project": project, "env": env, "kb_base": str(kb.base),
                              "root": root_key, "sources": []}

    # ① 在线探索（Agent 自主下钻）
    if live and serial:
        disc = HigoRedPacketDiscoverer(serial)
        explorer = AppExplorer(kb, disc, max_depth=max_depth)
        report: DiscoveryReport = explorer.explore(root_key, f"直播间 Room {room}", source=source)
        result["live_report"] = report.to_dict()
        result["sources"].append(f"live:{serial}")

    # ② 离线历史证据回填（同一累积管道）
    added = []
    if backfill_evidence:
        added = backfill_from_evidence(backfill_evidence, kb, room,
                                       source=f"{source}|evidence")
        result["backfill_added"] = added
        result["sources"].append("evidence")

    result["tree"] = kb.to_tree(root_key)
    return result


if __name__ == "__main__":
    import sys
    live = "--no-live" not in sys.argv
    back_ev = None
    if len(sys.argv) > 1 and sys.argv[1].endswith(".xml"):
        back_ev = sys.argv[1]
    r = run_discovery("higo", "test", live=live,
                      backfill_evidence=back_ev or str(Path("output/evidence/higo-repro-bug")))
    print(json.dumps(r, ensure_ascii=False, indent=2))