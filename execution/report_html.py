# -*- coding: utf-8 -*-
"""把 S6 批量回归的 execution_result.json 渲染成人类可观看的 HTML 报告。

用法:
    python -m execution.report_html [执行结果json] [输出html]
默认: output/evidence_batch_regression/execution_result.json
      → output/evidence_batch_regression/execution_report.html
"""
from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from execution.business_verdict import (
    ENV_VERDICTS, VERDICT_REPRODUCED, classify_business_verdict, verdict_note,
)

_VERDICT_LABEL = {
    "reproduced": "业务复现",
    "auth_expired": "凭证失效",
    "anti_replay": "防重放",
    "rate_limited": "限频",
    "no_response": "无业务码",
    "business_mismatch": "业务不符",
}


def _status_label(v: str) -> str:
    return {
        "pass": '<span class="pill ok">通过</span>',
        "fail": '<span class="pill bad">失败</span>',
        "error": '<span class="pill bad">错误</span>',
        "skip": '<span class="pill info">跳过</span>',
    }.get(v, f'<span class="pill info">{html.escape(v)}</span>')


def _step_verdict(st: dict) -> str | None:
    """取步骤业务归因；旧产物缺字段时由原始 ret 现算（确定性）。"""
    if "business_verdict" in st:
        return st["business_verdict"]
    if "replayed_ret" in st:
        return classify_business_verdict(st.get("captured_ret"), st.get("replayed_ret"))
    return None


def _verdict_pill(verdict: str) -> str:
    label = _VERDICT_LABEL.get(verdict, verdict)
    if verdict == VERDICT_REPRODUCED:
        cls = "ok"
    elif verdict in ENV_VERDICTS:
        cls = "warnx"
    else:
        cls = "bad"
    return f'<span class="pill {cls}" title="{html.escape(verdict_note(verdict))}">业务·{label}</span>'


def _render(r: dict) -> str:
    s = r.get("summary", {})
    tc = s.get("tc_batch", {})
    api = s.get("api_replay", {})
    ui = s.get("ui_flow", {})
    tcs = r.get("tc_results", [])
    api_rep = r.get("api_replay", [])
    ui_flow = r.get("ui_flow", [])
    total_tc = tc.get("total", 0)
    pass_tc = tc.get("pass", 0)
    fail_tc = tc.get("fail", 0)

    # 聚合各 step 类型统计
    step_stats = {"api": 0, "db": 0, "adb": 0}
    for t in tcs:
        for st in t.get("steps", []):
            step_stats[st.get("type", "?")] = step_stats.get(st.get("type", "?"), 0)

    tc_rows = []
    for t in tcs:
        steps_html = []
        tc_verdict = None
        for st in t.get("steps", []):
            ev = st.get("evidence_refs", [])
            ev_short = "".join(
                f'<li>{html.escape(p.rsplit(chr(92),1)[-1] if chr(92) in p else p)}</li>'
                for p in ev)
            ret = st.get("replayed_ret")
            ret_txt = f' · <span class="mono">ret={st["captured_ret"]}→{ret}</span>' if (
                "replayed_ret" in st) else ""
            v = _step_verdict(st)
            if v and tc_verdict is None:
                tc_verdict = v
            v_txt = _verdict_pill(v) if v else ""
            note_txt = (f'<div class="sm" style="margin:4px 0 0 58px">{html.escape(verdict_note(v))}</div>'
                        if v and v != VERDICT_REPRODUCED else "")
            steps_html.append(
                f'<div class="step"><span class="sl">{st.get("type","?").upper()}#{st.get("step_id")}</span>'
                f'{_status_label(st.get("status",""))}{v_txt}{ret_txt}'
                f'<span class="sm">断言 {st.get("assertions_passed",0)}/'
                f'{st.get("assertions_passed",0)+st.get("assertions_failed",0)} 通过 · {st.get("duration_ms",0)}ms</span>'
                f'{note_txt}'
                f'<details class="ev"><summary>证据({len(ev)})</summary><ul>{ev_short}</ul></details>'
                f'</div>')
        tc_v_txt = _verdict_pill(tc_verdict) if tc_verdict else ""
        tc_rows.append(
            f'<details class="tc"><summary><span class="cid">{html.escape(t.get("tc_id",""))}</span>'
            f'{html.escape(t.get("title",""))}{_status_label(t.get("status",""))}{tc_v_txt}'
            f'<span class="sm">{(t.get("duration_ms",0)/1000):.1f}s</span></summary>'
            f'{"".join(steps_html)}</details>')

    api_rows = []
    for a in api_rep:
        c = a.get("captured", {})
        a_verdict = classify_business_verdict(c.get("ret"), a.get("replayed_ret"))
        api_rows.append(
            f'<tr><td class="mono">{html.escape(a.get("tc_id",""))}</td>'
            f'<td class="mono">{html.escape(a.get("endpoint",""))}</td>'
            f'<td>{a.get("replayed",{}).get("status_code")}</td>'
            f'<td>{_status_label("pass" if c.get("success") else "fail")}</td>'
            f'<td class="mono">{c.get("ret")} → {a.get("replayed_ret")}</td>'
            f'<td>{_verdict_pill(a_verdict)}</td></tr>')

    ui_rows = []
    for u in ui_flow:
        ui_rows.append(
            f'<tr><td class="mono">{html.escape(str(u.get("tc_id"))) if u.get("tc_id") else "-"}</td>'
            f'<td>{html.escape(u.get("kind",""))}</td>'
            f'<td>{html.escape(u.get("title",""))}</td>'
            f'<td class="sm">{html.escape(str(u.get("detail","")))}</td>'
            f'<td>{_status_label(u.get("status",""))}</td></tr>')

    # 业务层观察分布：优先 summary.business_observation，旧产物缺字段时现算
    biz_dist = dict(s.get("business_observation") or {})
    if not biz_dist:
        for t in tcs:
            for st in t.get("steps", []):
                v = _step_verdict(st)
                if v and st.get("step_id") == 1 and st.get("type") == "api":
                    biz_dist[v] = biz_dist.get(v, 0) + 1
    reproduced_n = biz_dist.get(VERDICT_REPRODUCED, 0)
    biz_total = sum(biz_dist.values())
    dist_txt = " / ".join(
        f"{_VERDICT_LABEL.get(k, k)} {v}" for k, v in sorted(biz_dist.items())) or "无"

    # 决策块（由 execution/report.py 注入 _gate；缺省则不显示，保持向后兼容）
    gate = r.get("_gate") or {}
    gate_html = ""
    if gate:
        g = gate.get("gate", "")
        reasons = "".join(f"<li>{html.escape(x)}</li>" for x in gate.get("reasons", []))
        gate_html = (
            f'<div class="gate {g}"><div class="gv">Release Gate：{html.escape(g)}</div>'
            f'<ul>{reasons}</ul></div>')

    # 缺陷草稿区（由 report.py 注入 _defects）
    defects = r.get("_defects") or []
    defect_rows = []
    for d in defects:
        ev_n = len(d.get("evidence_refs", []) or [])
        defect_rows.append(
            f'<div class="dft"><div class="dh">{html.escape(d.get("defect_id",""))}'
            f' <span class="pill warnx">{html.escape(d.get("status",""))}</span></div>'
            f'<div class="sm">{html.escape(d.get("title",""))}</div>'
            f'<div class="sm">归因：{html.escape(d.get("severity_hint",""))} · '
            f'失败步骤 {d.get("summary",{}).get("failed_step_count",0)} · 证据 {ev_n}</div></div>')
    defects_html = ""
    if defect_rows:
        defects_html = (
            f'<h2>缺陷草稿（{len(defect_rows)}，待人工确认）</h2>' + "".join(defect_rows))

    run_time = html.escape(str(r.get("run_time", "")))
    endpoint = html.escape(str(r.get("endpoint_substring", "")))
    capture = html.escape(str(r.get("capture_dir", "")))

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>S6 批量回归报告 · {run_time}</title>
<style>
:root{{--bg:#0d1117;--s:#161b22;--s2:#21262d;--b:#30363d;--t:#e6edf3;--m:#8b949e;--ok:#3fb950;--bad:#f85149;--info:#58a6ff;--accent:#f0883e}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:var(--bg);color:var(--t);font:15px/1.7 -apple-system,'Segoe UI','Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif;padding:32px 20px 80px}}
.wrap{{max-width:1060px;margin:0 auto}}
h1{{font-size:26px}} .meta{{color:var(--m);font-size:13px;margin:6px 0 18px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin:18px 0}}
.card{{background:var(--s);border:1px solid var(--b);border-radius:12px;padding:16px}}
.card .n{{font-size:30px;font-weight:700}}.card .l{{color:var(--m);font-size:12.5px}}
.good{{color:var(--ok)}} .badc{{color:var(--bad)}}
h2{{font-size:19px;margin:30px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--b)}}
table{{width:100%;border-collapse:collapse;font-size:13.5px;margin:10px 0}}
th,td{{border:1px solid var(--b);padding:6px 9px;text-align:left;vertical-align:top}}
th{{background:var(--s2)}}
.pill{{display:inline-block;padding:0 8px;border-radius:999px;font-size:12px;font-weight:600;margin-left:8px}}
.pill.ok{{background:rgba(63,185,80,.15);color:var(--ok)}}
.pill.bad{{background:rgba(248,81,73,.15);color:var(--bad)}}
.pill.info{{background:rgba(88,166,255,.15);color:var(--info)}}
.pill.warnx{{background:rgba(210,153,34,.18);color:#d29922}}
.sm{{color:var(--m);font-size:12.5px;margin-left:6px}}
.mono{{font-family:Consolas,Menlo,monospace;font-size:12px}}
details.tc{{background:var(--s);border:1px solid var(--b);border-radius:10px;padding:10px 14px;margin:8px 0}}
details.tc summary{{cursor:pointer;font-weight:600}}
.step{{background:var(--s2);border:1px solid var(--b);border-radius:8px;padding:8px 12px;margin:8px 0 8px 0}}
.sl{{font-weight:700;color:var(--info);display:inline-block;width:58px}}
details.ev summary{{cursor:pointer;color:var(--m);font-size:12.5px;margin-top:6px}}
details.ev ul{{margin:6px 0 0 18px;font-size:12px}}
.note{{background:rgba(63,185,80,.08);border-left:3px solid var(--ok);padding:12px 16px;border-radius:8px;margin:14px 0}}
.warn{{background:rgba(210,153,34,.1);border-left:3px solid #d29922;padding:12px 16px;border-radius:8px;margin:14px 0}}
.gate{{border-radius:12px;padding:16px 20px;margin:16px 0;font-size:15px}}
.gate.GO{{background:rgba(63,185,80,.12);border:1px solid var(--ok)}}
.gate.GO_WITH_WARNINGS{{background:rgba(210,153,34,.12);border:1px solid #d29922}}
.gate.NO_GO{{background:rgba(248,81,73,.12);border:1px solid var(--bad)}}
.gate .gv{{font-size:20px;font-weight:700}}
.gate.GO .gv{{color:var(--ok)}} .gate.GO_WITH_WARNINGS .gv{{color:#d29922}} .gate.NO_GO .gv{{color:var(--bad)}}
.gate ul{{margin:8px 0 0 20px}}
.dft{{background:var(--s);border:1px solid var(--b);border-radius:8px;padding:10px 14px;margin:8px 0}}
.dft .dh{{font-weight:600}}
</style></head><body><div class="wrap">
<h1>S6 批量回归报告</h1>
<p class="meta">运行时间：{run_time} · 接口：{endpoint} · 抓包源：{capture}</p>
{gate_html}

<div class="cards">
  <div class="card"><div class="n {('good' if fail_tc==0 else 'badc')}">{pass_tc}/{total_tc}</div><div class="l">协议层通过 / 总数（status_code 断言）</div></div>
  <div class="card"><div class="n {('good' if reproduced_n else 'badc')}">{reproduced_n}/{biz_total}</div><div class="l">业务复现 / 总数（ret 对比）</div></div>
  <div class="card"><div class="n good">{step_stats.get('api',0)}</div><div class="l">API 步骤</div></div>
  <div class="card"><div class="n good">{step_stats.get('adb',0)}</div><div class="l">ADB 步骤</div></div>
  <div class="card"><div class="n good">{ui.get('pass',0)}/{ui.get('total',0)}</div><div class="l">UI 下钻通过 / 总数</div></div>
</div>

<div class="note"><b>结论（两层语义）：</b>本轮 {total_tc} 条用例<b>协议层</b> {pass_tc} 通过、{fail_tc} 失败/错误（HTTP status_code 断言）；
<b>业务层</b>复现 {reproduced_n}/{biz_total}（ret 对比分布：{dist_txt}）。两层独立判定——协议层通过 ≠ 业务复现。UI 下钻 {ui.get('pass',0)} 通过、{ui.get('skip',0)} 跳过。</div>
<div class="warn"><b>业务观察归因说明：</b>回放业务码与抓包不一致时按归因分类呈现，<u>不判产品缺陷、不计 TC 失败</u>：
<span class="mono">ret=-11</span> 凭证失效（Authorization code error，需刷新登录态后重跑）；
<span class="mono">ret=-1</span> 后端防重放（同一抓包字节重复提交被拒，回放请勿刷新 h_ts 或重建 body）；
<span class="mono">ret=-101</span> 频率限制。仅「业务不符」（不属已知归因）才需人工排查。</div>

<h2>API 抓包复现</h2>
<table><thead><tr><th>TC</th><th>接口</th><th>HTTP</th><th>抓包成功</th><th>ret(抓包→回放)</th><th>业务归因</th></tr></thead>
<tbody>{''.join(api_rows) or '<tr><td colspan=6 class=sm>无</td></tr>'}</tbody></table>

<h2>用例批量执行（{len(tc_rows)} 条）</h2>
<p class="sm">每条展开可见其 API/ADB 步骤、断言与证据文件。</p>
{''.join(tc_rows) or '<p class=sm>无</p>'}

<h2>UI 交互下钻</h2>
<table><thead><tr><th>TC</th><th>类型</th><th>步骤</th><th>详情</th><th>状态</th></tr></thead>
<tbody>{''.join(ui_rows) or '<tr><td colspan=5 class=sm>无</td></tr>'}</tbody></table>
{defects_html}
</div></body></html>"""


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else str(
        _PROJECT_ROOT / "output" / "evidence_batch_regression" / "execution_result.json")
    dst = sys.argv[2] if len(sys.argv) > 2 else str(
        Path(src).with_name("execution_report.html"))
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    out = _render(data)
    Path(dst).write_text(out, encoding="utf-8")
    print("已渲染:", dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())