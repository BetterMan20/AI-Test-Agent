# -*- coding: utf-8 -*-
"""效率基线：手工基线耗时 vs Agent 耗时，量化每个原子 Skill 的提效比。

用法（库）：
    from core.efficiency import timed, record, report
    with timed("element_locator", items=10):        # Agent 侧计时
        ... 跑 Skill ...
    record("element_locator", agent_seconds=95, items=10)   # 或直接登记

    report()  # 读 config/efficiency_baseline.yaml + output/baselines/*.jsonl → 提效对比

用法（CLI）：
    python -m core.efficiency report                 # 打印提效对比表
    python -m core.efficiency report --html          # 落 output/baselines/efficiency_report.html
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BASELINE_CFG = _PROJECT_ROOT / "config" / "efficiency_baseline.yaml"
_OUT_DIR = _PROJECT_ROOT / "output" / "baselines"

# 默认手工基线（秒/次）——首次使用请用 `record --manual` 实测 3 次取中位数后改写 config
# 来源：典型测试工程师经验值，仅作占位，需按团队实测覆盖
_DEFAULT_MANUAL = {
    "element_locator": {"seconds_per_item": 150, "note": "手工改 1 个失效元素定位（打开页面/找新XPath/改脚本/验证）"},
    "report_synth": {"seconds_per_item": 480, "note": "手工拼 1 份带截图+复现步骤+风险分级的回归报告"},
    "env_guardian": {"seconds_per_item": 600, "note": "回归值守处理 1 次崩溃/弹窗/超时（重启App/重跑）"},
}


@contextmanager
def timed(skill: str, items: int = 1):
    """Agent 侧计时上下文：退出时自动登记耗时。

    items=本次处理的对象数（个/份/次）。耗时按 items 摊销为"每单位耗时"，
    与基线 seconds_per_item 同口径可比。例如一次定位生成 5 个控件定位，
    items=5，耗时/5 即单个定位的 Agent 成本。
    """
    t0 = time.perf_counter()
    box = {"items": items}
    yield box
    dt = time.perf_counter() - t0
    n = max(int(box.get("items", items)), 1)
    record(skill, agent_seconds=round(dt / n, 2), items=n)


def _load_manual_baselines() -> dict[str, dict[str, Any]]:
    """读 config 手工基线；缺省回落 _DEFAULT_MANUAL。"""
    if _BASELINE_CFG.exists():
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(_BASELINE_CFG.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict) and data:
                return {**_DEFAULT_MANUAL, **data}
        except Exception:
            pass
    return dict(_DEFAULT_MANUAL)


def record(skill: str, agent_seconds: float | None = None, items: int = 1,
           manual_seconds: float | None = None, note: str = "") -> dict[str, Any]:
    """登记一次执行：agent_seconds=Agent 耗时；manual_seconds=实测手工耗时（用于校准基线）。"""
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "skill": skill,
        "items": items,
        "agent_seconds": agent_seconds,
        "manual_seconds": manual_seconds,
        "note": note,
    }
    (_OUT_DIR / f"{skill}.jsonl").write_text("", encoding="utf-8") if not (_OUT_DIR / f"{skill}.jsonl").exists() else None
    with (_OUT_DIR / f"{skill}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return 0.0
    mid = n // 2
    return xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2


def _load_runs(skill: str) -> list[dict[str, Any]]:
    p = _OUT_DIR / f"{skill}.jsonl"
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return out


def compare(skill: str) -> dict[str, Any]:
    """单个 Skill 的提效对比：手工基线 vs Agent 实测中位数 → 提效比%。"""
    manual_cfg = _load_manual_baselines().get(skill, {})
    runs = _load_runs(skill)
    agent_times = [r["agent_seconds"] for r in runs if r.get("agent_seconds") is not None]
    manual_measured = [r["manual_seconds"] for r in runs if r.get("manual_seconds") is not None]
    # 手工基线：优先实测中位数，否则 config/默认
    if manual_measured:
        manual_base = _median(manual_measured)
        base_src = "实测中位数"
    else:
        manual_base = float(manual_cfg.get("seconds_per_item", 0))
        base_src = "config/默认"
    agent_med = _median(agent_times) if agent_times else None
    total_items = sum(r.get("items", 1) for r in runs)
    saving = None
    if manual_base and agent_med is not None and agent_med >= 0:
        saving = round((1 - agent_med / manual_base) * 100, 1)
    return {
        "skill": skill,
        "manual_baseline_s": manual_base,
        "baseline_source": base_src,
        "agent_median_s": agent_med,
        "runs": len(agent_times),
        "total_items": total_items,
        "saving_pct": saving,
        "note": manual_cfg.get("note", ""),
    }


def report(skills: list[str] | None = None) -> list[dict[str, Any]]:
    """汇总各 Skill 提效对比（默认全部已知 Skill）。"""
    known = skills or sorted(set(_DEFAULT_MANUAL) |
                             {p.stem for p in _OUT_DIR.glob("*.jsonl")} if _OUT_DIR.exists() else set(_DEFAULT_MANUAL))
    return [compare(s) for s in known]


def render_html(rows: list[dict[str, Any]]) -> str:
    """渲染提效对比 HTML（人读，可决策）。"""
    def _fmt_s(v):
        return "-" if v is None else (f"{v:.0f}s" if v < 120 else f"{v/60:.1f}min")

    trs = []
    for r in rows:
        pct = r["saving_pct"]
        color = "#3fb950" if (pct or 0) >= 70 else ("#d29922" if (pct or 0) >= 40 else "#f85149")
        pct_txt = f'<b style="color:{color}">{pct}%</b>' if pct is not None else '<span style="color:#8b949e">待实测</span>'
        trs.append(
            f"<tr><td><code>{r['skill']}</code></td><td>{_fmt_s(r['manual_baseline_s'])}"
            f"<div style='color:#8b949e;font-size:11px'>{r['baseline_source']}</div></td>"
            f"<td>{_fmt_s(r['agent_median_s'])}<div style='color:#8b949e;font-size:11px'>{r['runs']} 次运行</div></td>"
            f"<td>{r['total_items']}</td><td>{pct_txt}</td>"
            f"<td style='color:#8b949e;font-size:12px'>{r['note']}</td></tr>")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>效率基线对比 · {now}</title>
<style>body{{background:#0d1117;color:#e6edf3;font:14px/1.6 -apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;padding:32px 20px}}
.wrap{{max-width:1000px;margin:0 auto}}h1{{font-size:22px}}.meta{{color:#8b949e;font-size:13px;margin:6px 0 18px}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}th,td{{border:1px solid #30363d;padding:8px 10px;text-align:left;vertical-align:top}}
th{{background:#161b22}}code{{background:#161b22;border:1px solid #30363d;border-radius:5px;padding:1px 6px;font-size:12px}}
.note{{background:rgba(88,166,255,.08);border-left:3px solid #58a6ff;padding:12px 16px;border-radius:8px;margin:14px 0;font-size:13px}}</style>
</head><body><div class="wrap"><h1>原子 Skill 效率基线对比</h1>
<p class="meta">生成 {now} · 数据 output/baselines/*.jsonl · 基线 config/efficiency_baseline.yaml</p>
<div class="note"><b>读法：</b>提效比 = (1 − Agent耗时/手工基线) × 100%。≥70% 绿（已定向击穿）、40–70% 黄、&lt;40% 红（未达标需优化）。
首次使用请先用 <code>record --manual</code> 实测 3 次手工耗时写入基线，否则按经验占位值估算。</div>
<table><thead><tr><th>Skill</th><th>手工基线</th><th>Agent 耗时(中位)</th><th>累计处理</th><th>提效比</th><th>说明</th></tr></thead>
<tbody>{''.join(trs)}</tbody></table></div></body></html>"""


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="效率基线：手工 vs Agent 耗时对比")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report", help="打印提效对比表")
    rp.add_argument("--html", action="store_true", help="落 output/baselines/efficiency_report.html")
    rp.add_argument("--skill", action="append", default=None, help="只看指定 skill")
    rc = sub.add_parser("record", help="登记一次执行耗时")
    rc.add_argument("skill")
    rc.add_argument("--agent", type=float, default=None, help="Agent 耗时（秒）")
    rc.add_argument("--manual", type=float, default=None, help="实测手工耗时（秒，用于校准基线）")
    rc.add_argument("--items", type=int, default=1)
    rc.add_argument("--note", default="")
    args = ap.parse_args()

    if args.cmd == "record":
        row = record(args.skill, agent_seconds=args.agent, items=args.items,
                     manual_seconds=args.manual, note=args.note)
        print("已登记:", json.dumps(row, ensure_ascii=False))
        return 0

    rows = report(args.skill)
    # 控制台表
    print(f"{'Skill':<18} {'手工基线':>10} {'Agent中位':>10} {'提效比':>8}  说明")
    print("-" * 78)
    for r in rows:
        pct = f"{r['saving_pct']}%" if r['saving_pct'] is not None else "待实测"
        am = (f"{r['agent_median_s']:.2f}s" if r['agent_median_s'] is not None and r['agent_median_s'] < 10
              else (f"{r['agent_median_s']:.0f}s" if r['agent_median_s'] is not None else "-"))
        print(f"{r['skill']:<18} {r['manual_baseline_s']:>8.0f}s {am:>10} {pct:>8}  {r['note'][:30]}")
    if args.html:
        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        p = _OUT_DIR / "efficiency_report.html"
        p.write_text(render_html(rows), encoding="utf-8")
        print("\nHTML:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
