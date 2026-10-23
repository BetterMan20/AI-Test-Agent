# -*- coding: utf-8 -*-
"""把探索型全景 QA 循环的 cycle_report.json 渲染成人类可观看的 HTML 报告。

用法:
    python -m core.qa.report_html [cycle_report.json] [输出html]
默认: output/qa/cycle_report.json → output/qa/cycle_report.html
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

_P = Path(__file__).resolve().parent.parent.parent
if str(_P) not in sys.path:
    sys.path.insert(0, str(_P))


def _pill(v: str) -> str:
    ok = v in (True, "true", "wired", "pass")
    return (f'<span class="pill {"" if ok else "bad"}">'
            f'{("开启" if ok else "未启用" if isinstance(v,bool) else html.escape(str(v)))}</span>')


def _artifact_table(a: dict) -> str:
    rows = []
    for k, v in a.items():
        if k in ("system_facts_block", "historical_memory_block", "kb_tree"):
            continue
        if isinstance(v, (dict, list)):
            txt = json.dumps(v, ensure_ascii=False)[:400]
        else:
            txt = str(v)
        rows.append(f'<div class="kv"><span class="k">{html.escape(k)}</span>'
                    f'<span class="mono v">{html.escape(txt)}</span></div>')
    return "".join(rows) if rows else '<p class="sm">无 artifact</p>'


def _render_qa(r: dict) -> str:
    stages = r.get("stages", [])
    domain = html.escape(str(r.get("domain", "")))
    room = html.escape(str(r.get("room", "")))
    kb = html.escape(str(r.get("kb_base", "")))
    history = html.escape(str(r.get("history_summary", "")))
    kb_tree = r.get("kb_tree", "")

    # 各阶段卡片
    cards = []
    for s in stages:
        art = s.get("artifact", {})
        body = _artifact_table(art)
        block = ""
        for bk in ("system_facts_block", "historical_memory_block"):
            if art.get(bk):
                block += (f'<details><summary>{bk}</summary>'
                          f'<pre class="blk">{html.escape(str(art[bk]))}</pre></details>')
        pend = s.get("pending", [])
        pend_html = f'<div class="pend">{"; ".join(html.escape(p) for p in pend)}</div>' if pend else ""
        wired = s.get("wired")
        cards.append(
            f'<div class="stage {("ok" if wired else "off")}">'
            f'<div class="sh"><span class="tag">{html.escape(s.get("stage",""))}</span>'
            f'<b>{html.escape(s.get("name",""))}</b>{_pill(wired)}</div>'
            f'<div class="via">via · <span class="mono">{html.escape(str(s.get("via","")))}</span></div>'
            f'<div class="ab">{body}{block}</div>{pend_html}'
            f'</div>')

    # 验证阶段的违例高亮
    verify = next((s for s in stages if s.get("stage") == "verify"), {})
    violations_html = ""
    for d in verify.get("artifact", {}).get("detail", []):
        if not d.get("consistent"):
            violations_html += (
                f'<div class="viol"><div class="vio-row">'
                f'业务态:<b class="mono">{html.escape(str(d.get("phase")))}</b>'
                f'期望UI:<b class="mono">{html.escape(str(d.get("expected_ui")))}</b>'
                f'观测UI:<b class="mono badc">{html.escape(str(d.get("observed_ui")))}</b></div>'
                f'<ul>{"".join("<li>"+html.escape(v)+"</li>" for v in d.get("violations",[]))}</ul>'
                f'<div class="sm">{html.escape(str(d.get("label","")))}</div></div>')

    # 找风险列表
    risk_art = next((s.get("artifact", {}) for s in stages if s.get("stage") == "risk"), {})
    risk_rows = "".join(
        f'<tr><td class="mono">{html.escape(str(x.get("id")))}</td>'
        f'<td>{html.escape(str(x.get("name")))}</td>'
        f'<td><span class="pill pri">P{html.escape(str(x.get("priority","")).lstrip("P"))}</span></td>'
        f'<td class="mono">{html.escape(str(x.get("condition"))) if x.get("condition") else "-"}</td>'
        f'<td>{html.escape(str(x.get("expected_anomaly")))}</td></tr>'
        for x in risk_art.get("risk", []))

    # 状态机表
    model_art = next((s.get("artifact", {}) for s in stages if s.get("stage") == "model"), {})
    sm = model_art.get("state_model", {}) or {}
    sm_rows = "".join(f'<tr><td class="mono">{html.escape(k)}</td><td class="mono">{html.escape(str(v))}</td></tr>'
                      for k, v in sm.items())

    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>全景 QA 循环报告 · {domain}@{room}</title><style>
:root{{--bg:#0d1117;--s:#161b22;--s2:#21262d;--b:#30363d;--t:#e6edf3;--m:#8b949e;--ok:#3fb950;--bad:#f85149;--info:#58a6ff;--accent:#f0883e}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:var(--bg);color:var(--t);font:15px/1.7 -apple-system,'Segoe UI','Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif;padding:32px 20px 80px}}
.wrap{{max-width:1060px;margin:0 auto}} h1{{font-size:26px}}
.meta{{color:var(--m);font-size:13px;margin:6px 0 16px;line-height:1.9}}
.hist{{background:var(--s);border:1px solid var(--b);border-left:3px solid var(--info);border-radius:8px;padding:12px 16px;margin:14px 0}}
.stage{{background:var(--s);border:1px solid var(--b);border-radius:12px;padding:16px 18px;margin:12px 0}}
.stage.ok{{border-left:4px solid var(--ok)}} .stage.off{{border-left:4px solid var(--m);opacity:.85}}
.sh{{display:flex;align-items:center;gap:10px}} .sh b{{font-size:17px}}
.tag{{background:var(--s2);border:1px solid var(--b);border-radius:6px;padding:1px 8px;font:12px Consolas,monospace;color:var(--info)}}
.pill{{display:inline-block;padding:0 8px;border-radius:999px;font-size:12px;font-weight:600;background:rgba(63,185,80,.15);color:var(--ok)}}
.pill.bad{{background:rgba(248,81,73,.15);color:var(--bad)}}
.pill.pri{{background:rgba(240,136,62,.15);color:var(--accent)}}
.via{{color:var(--m);font-size:13px;margin:6px 0 4px}}
.ab{{margin-top:6px}} .kv{{margin:3px 0}} .k{{color:var(--m);font-size:13px;display:inline-block;width:170px}}
.v{{word-break:break-all}} .mono{{font-family:Consolas,Menlo,monospace;font-size:12px}}
.sm{{color:var(--m);font-size:12.5px}} .badc{{color:var(--bad)}}
details summary{{cursor:pointer;color:var(--m);font-size:13px;margin-top:8px}}
pre.blk{{background:#0b0f14;border:1px solid var(--b);border-radius:8px;padding:10px;font:12px/1.6 Consolas,monospace;white-space:pre-wrap}}
.pend{{color:var(--accent);font-size:12.5px;margin-top:8px;border-top:1px dashed var(--b);padding-top:6px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin:8px 0}} th,td{{border:1px solid var(--b);padding:6px 9px;text-align:left}}
th{{background:var(--s2)}}
.viol{{background:rgba(248,81,73,.08);border:1px solid rgba(248,81,73,.4);border-radius:10px;padding:14px 16px;margin:10px 0}}
.vio-row{{font-size:15px;display:flex;gap:18px;flex-wrap:wrap}} .vio-row b{{margin-left:2px}}
.viol ul{{margin:8px 0 4px 18px}}
h2{{font-size:19px;margin:30px 0 8px;padding-bottom:6px;border-bottom:1px solid var(--b)}}
</style></head><body><div class="wrap">
<h1>探索型全景 QA 循环报告</h1>
<p class="meta">业务域：<b>{domain}</b> · 房间：<b>{room}</b> · 知识库：<span class="mono">{kb}</span><br>
模型来源：<span class="mono">{html.escape(str(r.get("model_ref","")))}</span></p>
<div class="hist"><b>历史记忆 / 结论：</b>{history}</div>

<h2>七阶段执行</h2>
{''.join(cards)}

<h2>验证焦点 · 一致性违例</h2>
{violations_html or '<p class="sm">本轮未判出一致性违例（一致）。</p>'}

<h2>状态模型（{html.escape(str(len(sm)))} 态 → UI）</h2>
<table><thead><tr><th>业务态</th><th>UI 期望</th></tr></thead><tbody>{sm_rows or '<tr><td colspan=2>无</td></tr>'}</tbody></table>

<h2>找风险列表（{html.escape(str(len(risk_art.get("risk", []))))} 条）</h2>
<p class="sm">LLM 历史反推新增：{risk_art.get("llm_augmented", 0)} 条 ｜ 历史记忆条目：{risk_art.get("historical_memory_items", 0)} 条</p>
<table><thead><tr><th>ID</th><th>风险</th><th>优先级</th><th>触发条件</th><th>期望异常</th></tr></thead>
<tbody>{risk_rows or '<tr><td colspan=5>无</td></tr>'}</tbody></table>

<h2>App Knowledge Base（S0 累积，树形）</h2>
<pre class="blk">{html.escape(kb_tree) if kb_tree else "（无 KB 树）"}</pre>
</div></body></html>"""


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else str(_P / "output" / "qa" / "cycle_report.json")
    dst = sys.argv[2] if len(sys.argv) > 2 else str(Path(src).with_name("cycle_report.html"))
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    Path(dst).write_text(_render_qa(data), encoding="utf-8")
    print("已渲染:", dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())