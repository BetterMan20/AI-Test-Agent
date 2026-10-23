# -*- coding: utf-8 -*-
"""失败 → 本地缺陷草稿（闭环尾段第一段）。

对执行结果为 fail/error 的 TC，在 output/defects/ 下生成：
- <tc_id>.json  结构化草稿（机器可读，供后续 PR/工单对接）
- <tc_id>.md    人读草稿（标题/复现步骤/期望vs实际/证据引用/环境）

设计约束：
- 纯确定性，不调 LLM；草稿内容全部来自 plan + result + env，保证可复核可追溯
- fail（断言失败）标疑似产品缺陷；error（执行异常）标疑似工具/环境问题，二者分开归因
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

FAIL_STATUSES = ("fail", "error")

_SEVERITY = {
    "fail": "疑似产品缺陷（断言未满足）",
    "error": "疑似执行/环境问题（步骤异常中断）",
}


def build_defect_draft(
    result_row: dict[str, Any],
    plan: Any | None,
    env: dict[str, Any],
) -> dict[str, Any]:
    """从单条 TC 结果行 + 对应计划构建缺陷草稿 dict。"""
    tc_id = result_row.get("tc_id", "UNKNOWN")
    status = result_row.get("status", "")
    plan_steps = {s.step_id: s for s in plan.steps} if plan else {}

    failed_steps: list[dict[str, Any]] = []
    repro: list[str] = []
    for s in result_row.get("steps", []):
        sid = s.get("step_id")
        st = plan_steps.get(sid)
        desc = st.description if st else ""
        cfg = st.action if st else {}
        if desc:
            repro.append(f"{sid}. [{s.get('type')}] {desc}")
        if s.get("status") in FAIL_STATUSES:
            failed_steps.append({
                "step_id": sid,
                "type": s.get("type"),
                "status": s.get("status"),
                "description": desc,
                "config": cfg,
                "error": s.get("error"),
                "assertions_failed": s.get("assertions_failed", 0),
                "evidence_refs": s.get("evidence_refs", []),
            })

    trace = getattr(plan, "traceability", None) or {}
    return {
        "defect_id": f"DRAFT-{tc_id}",
        "draft": True,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "title": f"[草稿][{status}] {result_row.get('title', tc_id)}",
        "tc_id": tc_id,
        "status": status,
        "severity_hint": _SEVERITY.get(status, status),
        "summary": {
            "duration_ms": result_row.get("duration_ms", 0),
            "failed_step_count": len(failed_steps),
            "total_steps": len(result_row.get("steps", [])),
            "error": result_row.get("error"),
        },
        "repro_steps": repro,
        "failed_steps": failed_steps,
        "evidence_refs": result_row.get("evidence_refs", []) or [
            ref for s in result_row.get("steps", []) for ref in s.get("evidence_refs", [])
        ],
        "traceability": trace,
        "environment": env,
    }


def render_defect_md(draft: dict[str, Any]) -> str:
    """渲染人读 Markdown 草稿。"""
    lines = [
        f"# {draft['title']}",
        "",
        f"- **缺陷编号**: {draft['defect_id']}（草稿，待人工确认后提单）",
        f"- **创建时间**: {draft['created_at']}",
        f"- **归因提示**: {draft['severity_hint']}",
        f"- **关联用例**: {draft['tc_id']}",
        "",
    ]
    trace = draft.get("traceability") or {}
    if any(trace.get(k) for k in ("test_point_id", "scenario_ref", "source_facts")):
        lines += [
            "## 追溯（意图层）",
            "",
            f"- 测试点: {trace.get('test_point_id') or '-'}",
            f"- 场景: {trace.get('scenario_ref') or '-'}",
            f"- 来源事实: {', '.join(trace.get('source_facts') or []) or '-'}",
            "",
        ]
    if draft.get("repro_steps"):
        lines += ["## 复现步骤", ""]
        lines += [f"{x}" for x in draft["repro_steps"]]
        lines += [""]
    lines += ["## 失败步骤（期望 vs 实际）", ""]
    for fs in draft.get("failed_steps", []):
        lines += [
            f"### 步骤 {fs['step_id']} [{fs['type']}] — {fs['status']}",
            "",
            f"- 描述: {fs.get('description') or '-'}",
            f"- 断言失败数: {fs.get('assertions_failed', 0)}",
        ]
        if fs.get("error"):
            lines.append(f"- 异常: `{fs['error']}`")
        cfg = fs.get("config") or {}
        if cfg:
            lines.append(f"- 配置: `{json.dumps(cfg, ensure_ascii=False)[:300]}`")
        if fs.get("evidence_refs"):
            lines.append("- 证据:")
            lines += [f"  - `{e}`" for e in fs["evidence_refs"]]
        lines += [""]
    env = draft.get("environment") or {}
    if env:
        lines += ["## 环境", ""]
        lines += [f"- {k}: `{v}`" for k, v in env.items() if v]
        lines += [""]
    lines.append("> 本草稿由执行引擎自动生成；确认为真实缺陷后请转正式缺陷单/PR。")
    return "\n".join(lines)


def save_defect_drafts(
    result_rows: list[dict[str, Any]],
    plans: list[Any],
    out_dir: str | os.PathLike,
    env: dict[str, Any] | None = None,
) -> list[str]:
    """对 fail/error 的 TC 批量落草稿，返回生成的 json 路径列表。"""
    plan_map = {p.tc_id: p for p in plans} if plans else {}
    out = Path(out_dir)
    written: list[str] = []
    for row in result_rows:
        if row.get("status") not in FAIL_STATUSES:
            continue
        draft = build_defect_draft(row, plan_map.get(row.get("tc_id")), env or {})
        out.mkdir(parents=True, exist_ok=True)
        tc_id = row.get("tc_id", "UNKNOWN")
        jpath = out / f"{tc_id}.json"
        jpath.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / f"{tc_id}.md").write_text(render_defect_md(draft), encoding="utf-8")
        written.append(str(jpath))
    return written
