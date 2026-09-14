"""Demo — 回放真实 Higo API，生成证据文件。

从 D:\\higo-api 的 Whistle 抓包中解析 API 调用，
用真实 APIClient 回放，保存证据文件，输出 PASS/FAIL。

Run:  python -m tests.demo_real_higo_api
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from execution.context import ExecutionContext, EnvironmentConfig
from execution.planner import ExecutionPlanner
from execution.runner import ExecutionRunner
from evidence.collector import EvidenceCollector
from evidence.store import EvidenceStore
from tools.api.client import APIClient
from tools.whistle_parser import WhistleParser


HIGO_API_DIR = r"D:\higo-api"
EVIDENCE_DIR = Path("output/evidence_higo_real")

TARGET_ENDPOINTS = [
    "/live/facetime/check_in_detail",
    "/live/game/play_sign_in_status",
    "/live/account/trade_wealth_detail",
    "/live/room/match_entrys",
    "/live/gift/send_gift",
]


def find_captures() -> list:
    """从抓包目录中找到目标 API 的抓包记录。"""
    grouped = WhistleParser.find_endpoints(HIGO_API_DIR)
    captures = []
    for endpoint in TARGET_ENDPOINTS:
        if endpoint in grouped:
            captures.append(grouped[endpoint][0])
    return captures


def run_single_capture(capture) -> dict:
    """回放单个抓包 API，返回结果。"""
    api_client = APIClient(
        base_url=capture.base_url,
        timeout=30,
    )
    store = EvidenceStore(base_dir=str(EVIDENCE_DIR))
    collector = EvidenceCollector(store)
    runner = ExecutionRunner(
        api_client=api_client,
        evidence_collector=collector,
    )

    plan = ExecutionPlanner.plan_from_capture(capture)
    env = EnvironmentConfig(api_base_url=capture.base_url)
    ctx = ExecutionContext(environment=env, tc_id=plan.tc_id)
    result = runner.run_plan(plan, ctx)

    step_results = []
    for sr in result.step_results:
        step_results.append({
            "step_id": sr.step_id,
            "status": sr.status,
            "assertions_passed": sr.assertions_passed,
            "assertions_failed": sr.assertions_failed,
            "duration_ms": sr.duration_ms,
            "evidence_count": len(sr.evidence_refs),
        })
        if sr.error:
            step_results[-1]["error"] = sr.error

    return {
        "tc_id": plan.tc_id,
        "title": plan.title,
        "endpoint": capture.endpoint,
        "method": capture.method,
        "original_status": capture.status_code,
        "result_status": result.status,
        "step_results": step_results,
        "evidence_refs": result.evidence_refs,
    }


def main() -> None:
    if EVIDENCE_DIR.exists():
        shutil.rmtree(EVIDENCE_DIR)

    print("=" * 60)
    print("Higo API 真实回放 Demo")
    print(f"抓包目录: {HIGO_API_DIR}")
    print(f"证据目录: {EVIDENCE_DIR}")
    print("=" * 60)

    captures = find_captures()
    if not captures:
        print("未找到目标 API 抓包记录")
        return

    print(f"\n找到 {len(captures)} 个目标 API:\n")
    for i, cap in enumerate(captures, 1):
        print(f"  {i}. {cap.method} {cap.endpoint}")
        print(f"     原始状态码: {cap.status_code}")
        if cap.res_body and isinstance(cap.res_body, dict):
            ret = cap.res_body.get("ret")
            print(f"     原始 ret: {ret}")
    print()

    all_results = []
    for cap in captures:
        print(f"--- 回放: {cap.method} {cap.endpoint} ---")
        try:
            result = run_single_capture(cap)
        except Exception as e:
            result = {
                "tc_id": "ERROR",
                "endpoint": cap.endpoint,
                "result_status": "error",
                "error": str(e),
            }
        all_results.append(result)

        status_icon = "PASS" if result.get("result_status") == "pass" else "FAIL"
        print(f"  Result: {status_icon}")
        if result.get("step_results"):
            for sr in result["step_results"]:
                print(f"  Step {sr['step_id']}: {sr['status']} "
                      f"({sr['assertions_passed']} passed, {sr['assertions_failed']} failed)")
                if sr.get("error"):
                    print(f"    Error: {sr['error']}")
        print()

    print("=" * 60)
    print("Summary")
    print("=" * 60)

    pass_count = sum(1 for r in all_results if r.get("result_status") == "pass")
    fail_count = sum(1 for r in all_results if r.get("result_status") == "fail")
    error_count = sum(1 for r in all_results if r.get("result_status") == "error")
    print(f"  PASS: {pass_count}  FAIL: {fail_count}  ERROR: {error_count}")
    print(f"  Total: {len(all_results)}")

    print("\n" + "=" * 60)
    print("Evidence Files")
    print("=" * 60)
    for tc_dir in sorted(EVIDENCE_DIR.iterdir()):
        if not tc_dir.is_dir():
            continue
        files = sorted(
            f.name for f in tc_dir.iterdir()
            if not f.name.endswith("_meta.json")
        )
        print(f"\n  {tc_dir.name}/")
        for fname in files:
            print(f"    {fname}")

    summary_path = EVIDENCE_DIR / "execution_result.json"
    summary_path.write_text(
        json.dumps(
            {
                "total": len(all_results),
                "pass": pass_count,
                "fail": fail_count,
                "error": error_count,
                "results": all_results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nExecution Result: {summary_path}")


if __name__ == "__main__":
    main()
