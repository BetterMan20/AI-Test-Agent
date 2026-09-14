# -*- coding: utf-8 -*-
"""测试策略决策者 CLI —— S6 分层测试统一入口。

用法:
  python -m orchestrator.run_strategy --mode smoke   [--risk low] [--target 发送红包]
  python -m orchestrator.run_strategy --mode regression --risk high
  python -m orchestrator.run_strategy --mode nightly --dry-run

流程：StrategyDecision 决策 → 落盘 plan.json → Dispatcher 按层执行 → 聚合报告。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orchestrator.delegate import Dispatcher
from orchestrator.strategy import TestPlan, StrategyDecision

OUT_PLAN = Path("output/plan.json")


def build_plan(mode: str, risk: str, target: str,
               options: dict | None = None) -> dict:
    """规则决策 → 落盘 plan.json，返回 plan dict 供分派。"""
    plan = StrategyDecision().decide(
        mode=mode, risk=risk, target=target, options=options)
    data = plan.to_dict()
    OUT_PLAN.parent.mkdir(parents=True, exist_ok=True)
    OUT_PLAN.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="测试策略决策者（S6 入口）")
    p.add_argument("--mode", choices=["smoke", "regression", "nightly"],
                   default="smoke")
    p.add_argument("--risk", choices=["low", "medium", "high", "critical"],
                   default="low")
    p.add_argument("--target", default="发送红包")
    p.add_argument("--endpoint", default=None, help="业务回放端点，默认 send_red_packet")
    p.add_argument("--capture-dir", default="D:/higo-api")
    p.add_argument("--device", default="")
    p.add_argument("--stability-events", type=int, default=None,
                   help="覆盖稳定性事件量（默认按模式矩阵）")
    p.add_argument("--dry-run", action="store_true",
                   help="只做决策落盘，不触发真机执行")
    a = p.parse_args(argv)

    options: dict = {}
    if a.endpoint:
        options["endpoint"] = a.endpoint
    if a.stability_events is not None:
        options["stability_events"] = a.stability_events
    plan = build_plan(a.mode, a.risk, a.target, options)
    print("== 决策结果 ==")
    print("  mode=%s risk=%s target=%s" % (plan["mode"], a.risk, a.target))
    for lp in plan["layers"]:
        print("  [%s] enabled=%s ref=%s events=%d" % (
            lp["layer"], lp["enabled"], lp["ref"], lp["events"]))
    for r in plan["rationale"]:
        print("  -", r)
    print("  计划: %s" % OUT_PLAN)

    if a.dry_run:
        print("\n[dry-run] 跳过真机执行（输出到 %s）" % "output/plan.json")
        return 0

    plan_obj = TestPlan(**{**plan, "layers": [
        __import__("orchestrator.strategy", fromlist=["LayerPlan"]).LayerPlan(**l)
        for l in plan["layers"]]})
    disp = Dispatcher(capture_dir=a.capture_dir, device_serial=a.device)
    report = disp.execute(plan_obj)

    print("\n== 策略报告 ==")
    print("  layers_on:", report["layers_on"])
    print("  业务通过率:", report["pass_rate"], "判定:", report["verdict"])
    for layer, lr in report["summary"].items():
        if lr["enabled"]:
            print("  %-10s %-6s n_run=%d n_pass=%d" % (
                layer, lr["status"], lr["n_run"], lr["n_pass"]))
    print("  输出:", report["output_path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())