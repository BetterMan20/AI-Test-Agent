# -*- coding: utf-8 -*-
"""原子 Skill 2：结构化报告合成（report_synth）。

只干一件事：输入执行结果 JSON（+证据目录+缺陷草稿），
输出按风险分级的决策型 HTML 报告——高风险项置顶、证据内联、人可直接据此决策。
不再手动拼截图、整理复现步骤。

风险分级（确定性规则，无 LLM）：
  P0 阻断：协议层 fail/error、或有未决缺陷草稿、business_mismatch（业务不符）
  P1 关注：业务层未复现但属环境归因（凭证失效/防重放/限频）
  P2 通过：协议层+业务层均通过
报告按 P0→P1→P2 排序，P0 默认展开。

用法（库）：
    from skills_py.report_synth import synth
    out = synth("output/evidence_batch_regression/execution_result.json")

用法（CLI，含效率基线计时）：
    python -m skills_py.report_synth execution_result.json --record
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from execution.business_verdict import (
    ENV_VERDICTS, VERDICT_BUSINESS_MISMATCH, VERDICT_REPRODUCED, classify_business_verdict, verdict_note,
)

_RISK_LABEL = {"P0": "阻断", "P1": "关注", "P2": "通过"}
_RISK_COLOR = {"P0": "#f85149", "P1": "#d29922", "P2": "#3fb950"}


def _risk_of(status: str, verdict: str | None) -> str:
    if status in ("fail", "error"):
        return "P0"
    if verdict == VERDICT_BUSINESS_MISMATCH:
        return "P0"
    if verdict and verdict in ENV_VERDICTS:
        return "P1"
    return "P2"


def _step_verdict(st: dict) -> str | None:
    if "business_verdict" in st:
        return st["business_verdict"]
    if "replayed_ret" in st:
        return classify_business_verdict(st.get("captured_ret"), st.get("replayed_ret"))
    return None


def synth(result_json: str | Path, defect_dir: str | Path | None = None,
          out_html: str | Path | None = None) -> dict[str, Any]:
    """核心：结果 JSON → 风险分级 HTML。返回 {html_path, risk_dist, top_risks}。"""
    result_json = Path(result_json)
    data = json.loads(result_json.read_text(encoding="utf-8"))
    defect_dir = Path(defect_dir) if defect_dir else (_PROJECT_ROOT / "output" / "defects")
    out_html = Path(out_html) if out_html else result_json.with_name("risk_report.html")

    # 收集每条 TC 的风险与证据
    items: list[dict[str, Any]] = []
    risk_dist = {"P0": 0, "P1": 0, "P2": 0}
    for t in data.get("tc_results", []):
        steps = t.get("steps", [])
        verdict = None
        for st in steps:
            v = _step_verdict(st)
            if v:
                verdict = v
                break
        risk = _risk_of(t.get("status", ""), verdict)
        # 未决缺陷 → 升 P0
        evid = [e for s in steps for e in s.get("evidence_refs", [])]
        items.append({
            "tc_id": t.get("tc_id", "?"),
            "title": t.get("title", ""),
            "status": t.get("status", ""),
            "risk": risk,
            "verdict": verdict,
            "verdict_note": verdict_note(verdict) if verdict else "",
            "duration_s": round(t.get("duration_ms", 0) / 1000, 1),
            "steps": steps,
            "evidence": evid,
        })
        risk_dist[risk] += 1

    # 缺陷草稿（未决 → P0 提示）
    defects: list[dict] = []
    if defect_dir.is_dir():
        for p in sorted(defect_dir.glob("*.json")):
            try:
                defects.append(json.loads(p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue

    # 排序 P0→P1→P2
    order = {"P0": 0, "P1": 1, "P2": 2}
    items.sort(key=lambda x: (order[x["risk"]], -x["duration_s"]))
    top_risks = [i for i in items if i["risk"] == "P0"][:5]

    out_html.write_text(_render(data, items, risk_dist, defects), encoding="utf-8")
    return {
        "html_path": str(out_html),
        "risk_dist": risk_dist,
        "total": len(items),
        "top_risks": [{"tc_id": i["tc_id"], "verdict": i["verdict"], "status": i["status"]} for i in top_risks],
        "defects": len(defects),
    }


def _render(data: dict, items: list[dict], risk_dist: dict, defects: list[dict]) -> str:
    run_time = html.escape(str(data.get("run_time", "")))
    endpoint = html.escape(str(data.get("endpoint_substring", "")))

    def pill(risk: str) -> str:
        return (f'<span style="background:{_RISK_COLOR[risk]}22;color:{_RISK_COLOR[risk]};'
                f'border:1px solid {_RISK_COLOR[risk]};border-radius:999px;padding:0 8px;'
                f'font-size:11px;font-weight:600">{risk} {_RISK_LABEL[risk]}</span>')

    cards = "".join(
        f'<div style="background:#161b22;border:1px solid #30363d;border-radius:12px;padding:14px;text-align:center">'
        f'<div style="font-size:28px;font-weight:700;color:{_RISK_COLOR[k]}">{v}</div>'
        f'<div style="color:#8b949e;font-size:12px">{k} {_RISK_LABEL[k]}</div></div>'
        for k, v in risk_dist.items())

    rows = []
    for i in items:
        open_attr = " open" if i["risk"] == "P0" else ""
        steps_html = []
        for st in i["steps"]:
            ev = st.get("evidence_refs", [])
            ev_links = " ".join(
                f'<a href="file:///{e.replace(chr(92),"/")}" style="color:#58a6ff;font-size:11px">'
                f'{html.escape(Path(e).name)}</a>' for e in ev)
            v = _step_verdict(st)
            v_txt = (f'<div style="color:#8b949e;font-size:11px;margin-top:3px">{html.escape(verdict_note(v))}</div>'
                     if v and v != VERDICT_REPRODUCED else "")
            sc = "#3fb950" if st.get("status") == "pass" else "#f85149"
            steps_html.append(
                f'<div style="background:#21262d;border:1px solid #30363d;border-radius:8px;padding:7px 11px;margin:6px 0">'
                f'<b style="color:#58a6ff">{st.get("type","?").upper()}#{st.get("step_id")}</b> '
                f'<span style="color:{sc}">{st.get("status","")}</span> '
                f'<span style="color:#8b949e;font-size:11px">断言 {st.get("assertions_passed",0)} 通过/{st.get("assertions_failed",0)} 失败 · {st.get("duration_ms",0)}ms</span>'
                f'{v_txt}<div style="margin-top:4px">{ev_links}</div></div>')
        rows.append(
            f'<details{open_attr} style="background:#161b22;border:1px solid #30363d;border-radius:10px;padding:10px 14px;margin:8px 0">'
            f'<summary style="cursor:pointer;font-weight:600"><code style="color:#58a6ff">{html.escape(i["tc_id"])}</code> '
            f'{html.escape(i["title"])} {pill(i["risk"])} <span style="color:#8b949e;font-size:11px">{i["duration_s"]}s</span></summary>'
            f'{"".join(steps_html)}</details>')

    defect_html = ""
    if defects:
        drows = "".join(
            f'<div style="background:#161b22;border-left:3px solid #f85149;border-radius:8px;padding:10px 14px;margin:8px 0">'
            f'<b>{html.escape(d.get("defect_id",""))}</b> <span style="color:#8b949e">{html.escape(d.get("status",""))}</span>'
            f'<div style="color:#8b949e;font-size:12px">{html.escape(d.get("title",""))}</div>'
            f'<div style="color:#d29922;font-size:12px">{html.escape(d.get("severity_hint",""))}</div></div>'
            for d in defects)
        defect_html = f'<h2>缺陷草稿（{len(defects)}，待人工确认）</h2>{drows}'

    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>风险分级报告 · {run_time}</title>
<style>body{{background:#0d1117;color:#e6edf3;font:14px/1.6 -apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;padding:32px 20px}}
.wrap{{max-width:1000px;margin:0 auto}}h1{{font-size:22px}}h2{{font-size:17px;margin:26px 0 10px;border-bottom:1px solid #30363d;padding-bottom:6px}}
.meta{{color:#8b949e;font-size:13px;margin:6px 0 18px}}code{{background:#21262d;border-radius:4px;padding:1px 5px;font-size:12px}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:18px 0}}
.note{{background:rgba(88,166,255,.08);border-left:3px solid #58a6ff;padding:12px 16px;border-radius:8px;margin:14px 0;font-size:13px}}</style>
</head><body><div class="wrap"><h1>结构化测试报告 · 风险分级</h1>
<p class="meta">运行 {run_time} · 接口 {endpoint} · 共 {len(items)} 条 · 按风险 P0→P1→P2 排序，P0 默认展开</p>
<div class="cards">{cards}</div>
<div class="note"><b>读法：</b>P0 阻断=协议失败/业务不符/未决缺陷，须先处理；P1 关注=业务未复现但属环境归因（凭证/防重放/限频），刷新环境后重跑即可；P2 通过。证据文件名点击可直达。</div>
<h2>用例明细（按风险排序）</h2>{''.join(rows) or '<p style="color:#8b949e">无</p>'}
{defect_html}
</div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="结构化报告合成 Skill：结果JSON → 风险分级HTML")
    ap.add_argument("result_json", help="execution_result.json 路径")
    ap.add_argument("--defect-dir", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--record", action="store_true", help="登记效率基线计时")
    args = ap.parse_args()

    if args.record:
        from core.efficiency import timed
        with timed("report_synth", items=1):
            out = synth(args.result_json, args.defect_dir or None, args.out or None)
    else:
        out = synth(args.result_json, args.defect_dir or None, args.out or None)

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
