# -*- coding: utf-8 -*-
"""原子 Skill 1：元素定位增强（element_locator）。

只干一件事：输入 Appium/uiautomator 页面 XML 快照 + 目标关键词，
输出可直接写进脚本的定位三元组（resource_id / xpath / uiautomator），带置信度。
页面改版后无需手动找 XPath——重新跑一遍即生成新定位，吃掉脚本维护时间。

定位优先级（与 tools/appium/higo_ui.tap_by_keyword 口径一致）：
  1. resource-id（最稳，AppiumBy.ID）
  2. content-desc（Accessibility ID，AppiumBy.ACCESSIBILITY_ID）
  3. text → UiAutomator
  4. 结构 XPath（兜底，含索引，易随改版失效 → 标 low 置信度）

用法（库）：
    from skills_py.element_locator import locate
    res = locate(xml_string, keyword="红包")
    # {"keyword":..., "matches":[{confidence, resource_id, xpath, uiautomator, text, desc, bounds}...]}

用法（CLI，含效率基线计时）：
    python -m skills_py.element_locator page.xml --keyword 红包
    python -m skills_py.element_locator page.xml --keyword 红包 --record   # 登记效率基线
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _esc(s: str) -> str:
    return s.replace('"', '\\"')


class _Node:
    __slots__ = ("tag", "attrs", "children", "parent", "index")

    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[_Node] = []
        self.index = 1  # 同 tag 兄弟中的 1-based 序号


def _clean_xml(xml: str) -> str:
    """剥壳：真实 adb dump 文件可能混入噪声头/尾（如 'UI hierchary dumped to:...'），
    截取 <?xml 到 </hierarchy> 的合法片段。"""
    start = xml.find("<?xml")
    if start < 0:
        start = xml.find("<hierarchy")
    end = xml.rfind("</hierarchy>")
    if start >= 0 and end > start:
        return xml[start:end + len("</hierarchy>")]
    return xml


def _parse_tree(xml: str) -> _Node | None:
    """解析 uiautomator XML 为带父子/序号关系的节点树（保留层级以回溯 XPath）。"""
    try:
        root_el = ET.fromstring(_clean_xml(xml))
    except ET.ParseError:
        return None

    def build(el, parent) -> _Node:
        n = _Node(el.tag, dict(el.attrib), parent)
        # 统计同 tag 兄弟序号
        same = [c for c in (parent.children if parent else []) if c.tag == el.tag]
        n.index = len(same) + 1
        if parent is not None:
            parent.children.append(n)
        for ch in el:
            build(ch, n)
        return n

    return build(root_el, None)


def _xpath(n: _Node) -> str:
    """生成可读 XPath：uiautomator dump 的 tag 全叫 node，真实类型在 class 属性，
    用 class 末段作段名（android.widget.TextView → TextView），索引用同 class 兄弟序号。"""
    def seg_name(cur: _Node) -> str:
        cls = cur.attrs.get("class", "")
        return cls.rsplit(".", 1)[-1] if cls else cur.tag

    parts = []
    cur: _Node | None = n
    while cur is not None and cur.tag != "hierarchy":
        name = seg_name(cur)
        # 同 class 兄弟序号
        if cur.parent:
            same = [c for c in cur.parent.children if seg_name(c) == name]
            if len(same) > 1:
                idx = same.index(cur) + 1
                name = f"{name}[{idx}]"
        parts.append(name)
        cur = cur.parent
    return "//" + "/".join(reversed(parts))


def _is_interactive(attrs: dict) -> bool:
    return attrs.get("clickable") == "true" or attrs.get("focusable") == "true" or bool(
        attrs.get("resource-id") or attrs.get("content-desc") or attrs.get("text"))


def locate(xml: str, keyword: str, max_results: int = 5) -> dict[str, Any]:
    """核心：XML + 关键词 → 定位三元组列表（按置信度排序）。"""
    if not xml or "<hierarchy" not in xml:
        return {"keyword": keyword, "error": "no-hierarchy", "matches": []}
    root = _parse_tree(xml)
    if root is None:
        return {"keyword": keyword, "error": "xml-parse-error", "matches": []}

    pat = re.compile(keyword, re.IGNORECASE)
    matches: list[dict[str, Any]] = []

    def visit(n: _Node):
        a = n.attrs
        rid, text, desc = a.get("resource-id", ""), a.get("text", ""), a.get("content-desc", "")
        hay = " ".join(x for x in (rid, text, desc) if x)
        if hay and pat.search(hay) and _is_interactive(a):
            # 置信度：rid > desc > text > xpath
            if rid:
                conf, primary = "high", "resource_id"
            elif desc:
                conf, primary = "high", "accessibility_id"
            elif text:
                conf, primary = "medium", "text"
            else:
                conf, primary = "low", "xpath"
            matches.append({
                "confidence": conf,
                "primary": primary,
                "resource_id": rid or None,
                "accessibility_id": desc or None,
                "xpath": _xpath(n),
                "uiautomator": (f'new UiSelector().text("{_esc(text)}")' if text else
                                (f'new UiSelector().description("{_esc(desc)}")' if desc else None)),
                "text": text or None,
                "desc": desc or None,
                "class": a.get("class", ""),
                "bounds": a.get("bounds", ""),
                "clickable": a.get("clickable") == "true",
                "appium_locator": (
                    ("id", rid) if rid else
                    ("accessibility_id", desc) if desc else
                    ("android_uiautomator", f'new UiSelector().text("{_esc(text)}")') if text else
                    ("xpath", _xpath(n))
                ),
            })
        for c in n.children:
            visit(c)

    visit(root)
    # 排序：clickable 优先，再高置信度优先
    rank = {"high": 0, "medium": 1, "low": 2}
    matches.sort(key=lambda m: (not m["clickable"], rank[m["confidence"]]))
    matches = matches[:max_results]
    return {
        "keyword": keyword,
        "count": len(matches),
        "error_rate_hint": "低（rid/desc 命中）" if any(m["confidence"] == "high" for m in matches)
        else "中高（仅 text/xpath 命中，建议补 resource-id）" if matches else "未命中",
        "matches": matches,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="元素定位增强 Skill：XML 快照 + 关键词 → 定位三元组")
    ap.add_argument("xml_file", help="页面 XML 快照路径（uiautomator dump）")
    ap.add_argument("--keyword", required=True, help="目标关键词（正则，匹配 rid/text/desc）")
    ap.add_argument("--max", type=int, default=5)
    ap.add_argument("--record", action="store_true", help="登记效率基线计时")
    args = ap.parse_args()

    xml = Path(args.xml_file).read_text(encoding="utf-8", errors="replace")
    if args.record:
        from core.efficiency import timed
        with timed("element_locator", items=1) as box:
            res = locate(xml, args.keyword, args.max)
            box["items"] = max(res.get("count", 1), 1)  # 按生成定位数摊销耗时
    else:
        res = locate(xml, args.keyword, args.max)

    print(json.dumps(res, ensure_ascii=False, indent=2))
    if res["count"]:
        best = res["matches"][0]
        strat, val = best["appium_locator"]
        print(f"\n推荐定位（{best['confidence']} 置信度）: {strat} = {val}")
    return 0 if res["count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
