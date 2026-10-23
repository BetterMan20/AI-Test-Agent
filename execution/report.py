# -*- coding: utf-8 -*-
"""报告聚合入口（最后一公里）：原始执行数据 → 人看得懂、能决策的最终报告。

定位：
  execution/runner.py（执行）落盘 execution_result.json + 证据 + 缺陷草稿，属中间产物；
  execution/report_html.py（渲染）把结果 JSON 渲成人读 HTML，但不含决策、不管缺陷、不管业务归因汇总；
  本模块（聚合）是二者的入口编排器 + 决策层：
    读 execution_result.json + output/defects/* → 判 Release Gate →
    生成 execution_report.html（人读）+ release_gate.json（机读决策）→ 打印人工核查清单。

用法（CLI）：
    python -m execution.report                                  # 默认读 output/evidence_batch_regression
    python -m execution.report <execution_result.json> [--defect-dir output/defects] [--open]

用法（库，供 runner 收尾调用）：
    from execution.report import aggregate_report
    out = aggregate_report(result_json_path)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from execution.business_verdict import VERDICT_REPRODUCED, ENV_VERDICTS
from execution.report_html import _render

# Release Gate 决策（机读）：三态，确定性规则，无 LLM
GATE_GO = "GO"                    # 协议层全过且无未决缺陷 → 放行
GATE_GO_WITH_WARNINGS = "GO_WITH_WARNINGS"  # 协议层全过但业务未复现/仅环境归因 → 放行但需关注
GATE_NO_GO = "NO_GO"              # 存在 fail/error 或缺陷草稿未决 → 不放行


def _load_defects(defect_dir: Path) -> list[dict[str, Any]]:
    """读取缺陷草稿目录（DRAFT-*.json），按 tc_id 排序。目录不存在返回空。"""
    if not defect_dir.is_dir():
        return []
    out = []
    for p in sorted(defect_dir.glob("DRAFT-*.json")) + sorted(
        q for q in defect_dir.glob("*.json") if not q.name.startswith("DRAFT-")
    ):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    # 去重（DRAFT-<tc>.json 与 <tc>.json 同指向）
    seen, uniq = set(), []
    for d in out:
        k = d.get("tc_id") or d.get("defect_id")
        if k and k not in seen:
            seen.add(k)
            uniq.append(d)
    return uniq


def _business_dist(result: dict[str, Any]) -> dict[str, int]:
    """业务层观察分布：优先 summary.business_observation，缺失时从步骤现算。"""
    s = result.get("summary", {})
    dist = dict(s.get("business_observation") or {})
    if dist:
        return dist
    from execution.business_verdict import classify_business_verdict
    for t in result.get("tc_results", []):
        for st in t.get("steps", []):
            if st.get("step_id") == 1 and st.get("type") == "api" and "replayed_ret" in st:
                v = st.get("business_verdict") or classify_business_verdict(
                    st.get("captured_ret"), st.get("replayed_ret"))
                dist[v] = dist.get(v, 0) + 1
    return dist


def decide_gate(result: dict[str, Any], defects: list[dict[str, Any]]) -> dict[str, Any]:
    """Release Gate 决策：确定性规则，返回机读判定 + 依据。

    规则（按优先级）：
      1. 协议层有 fail/error 或有未决缺陷草稿 → NO_GO
      2. 协议层全过但业务复现数 < 总数（存在未复现）→ GO_WITH_WARNINGS
      3. 否则 → GO
    """
    s = result.get("summary", {})
    tc = s.get("tc_batch", {})
    fail_n = tc.get("fail", 0) + tc.get("error", 0)
    dist = _business_dist(result)
    reproduced = dist.get(VERDICT_REPRODUCED, 0)
    biz_total = sum(dist.values())
    env_only = all(k in ENV_VERDICTS or k == VERDICT_REPRODUCED for k in dist) if dist else True

    reasons: list[str] = []
    if fail_n or defects:
        gate = GATE_NO_GO
        if fail_n:
            reasons.append(f"协议层存在 {fail_n} 条 fail/error")
        if defects:
            reasons.append(f"{len(defects)} 份缺陷草稿未人工确认")
    elif biz_total and reproduced < biz_total:
        gate = GATE_GO_WITH_WARNINGS
        not_reproduced = biz_total - reproduced
        kinds = "、".join(f"{k}×{v}" for k, v in sorted(dist.items()) if k != VERDICT_REPRODUCED)
        reasons.append(
            f"业务层 {not_reproduced}/{biz_total} 未复现（{kinds}），"
            + ("均为环境归因（凭证/防重放/限频），非产品缺陷" if env_only else "含非环境归因，需人工排查"))
    else:
        gate = GATE_GO
        reasons.append("协议层与业务层全部通过")

    return {
        "gate": gate,
        "decided_at": datetime.now().isoformat(timespec="seconds"),
        "reasons": reasons,
        "metrics": {
            "protocol": dict(tc),
            "business": dist,
            "business_reproduced": f"{reproduced}/{biz_total}",
            "defects_open": len(defects),
        },
    }


def _checklist(gate: dict[str, Any], defects: list[dict[str, Any]]) -> list[str]:
    """人工核查 SOP 清单：按决策给出下一步动作。"""
    g = gate["gate"]
    items: list[str] = []
    if g == GATE_NO_GO:
        if defects:
            items.append(f"人工确认 {len(defects)} 份缺陷草稿（output/defects/*.md），转正式缺陷单或标记误报")
        items.append("修复后重跑回归直至协议层全过")
    elif g == GATE_GO_WITH_WARNINGS:
        items.append("业务未复现属环境归因时：刷新登录态/更换抓包凭证后重跑，确认可复现")
        items.append("若出现 business_mismatch：人工排查后再放行")
    else:
        items.append("可直接进入 Release；归档本轮 execution_result.json 与证据")
    return items


def aggregate_report(
    result_json: str | Path,
    defect_dir: str | Path | None = None,
    out_html: str | Path | None = None,
    out_gate: str | Path | None = None,
) -> dict[str, Any]:
    """聚合：读结果 JSON + 缺陷草稿 → 决策 → 渲 HTML + 落 gate JSON。返回决策 dict。"""
    result_json = Path(result_json)
    result = json.loads(result_json.read_text(encoding="utf-8"))
    base = result_json.parent
    defect_dir = Path(defect_dir) if defect_dir else (_PROJECT_ROOT / "output" / "defects")
    out_html = Path(out_html) if out_html else base / "execution_report.html"
    out_gate = Path(out_gate) if out_gate else base / "release_gate.json"

    defects = _load_defects(defect_dir)
    gate = decide_gate(result, defects)

    # 把决策与缺陷注入渲染数据（不动原 JSON，构造渲染副本）
    render_data = dict(result)
    render_data["_gate"] = gate
    render_data["_defects"] = defects
    out_html.write_text(_render(render_data), encoding="utf-8")
    out_gate.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "gate": gate,
        "defects": defects,
        "checklist": _checklist(gate, defects),
        "html": str(out_html),
        "gate_json": str(out_gate),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="报告聚合入口：execution_result.json → 人读 HTML + 机读 release_gate.json + 人工核查清单")
    ap.add_argument("result_json", nargs="?",
                    default=str(_PROJECT_ROOT / "output" / "evidence_batch_regression" / "execution_result.json"))
    ap.add_argument("--defect-dir", default="", help="缺陷草稿目录（默认 output/defects）")
    ap.add_argument("--open", action="store_true", help="生成后用默认浏览器打开 HTML")
    args = ap.parse_args()

    out = aggregate_report(
        args.result_json,
        defect_dir=args.defect_dir or None,
    )
    gate = out["gate"]
    icon = {GATE_GO: "✔", GATE_GO_WITH_WARNINGS: "▲", GATE_NO_GO: "✖"}.get(gate["gate"], "?")
    print(f"\n===== Release Gate: {icon} {gate['gate']} =====")
    for r in gate["reasons"]:
        print("  -", r)
    if out["defects"]:
        print(f"\n缺陷草稿（{len(out['defects'])}，待人工确认）:")
        for d in out["defects"]:
            print(f"  - {d.get('defect_id')}: {d.get('severity_hint')}")
    print("\n人工核查清单:")
    for i, c in enumerate(out["checklist"], 1):
        print(f"  {i}. {c}")
    print(f"\n报告: {out['html']}")
    print(f"决策: {out['gate_json']}")

    if args.open:
        import os
        os.startfile(out["html"])  # noqa: S606
    return 0 if gate["gate"] != GATE_NO_GO else 1


if __name__ == "__main__":
    raise SystemExit(main())
