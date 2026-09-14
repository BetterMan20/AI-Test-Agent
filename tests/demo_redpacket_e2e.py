"""红包优化需求 E2E 执行驱动：需求分析产物 -> 执行.

阶段 A (API)：whistle 抓包回放红包相关端点（确定性，无需 LLM）
阶段 B (ADB)：从新鲜生成的 test_cases.json 中挑红包 UI 相关 TC，
             经 tc_to_plan(LLM) 转成 ExecutionPlan 后，在真机 emulator-5554
             上执行并采集证据。

用法（在项目根目录，注入 PYTHONPATH）:
    python tests/demo_redpacket_e2e.py
"""

from __future__ import annotations

import json
from pathlib import Path

from engine import TestEngine
from execution.planner import ExecutionPlanner

DEVICE_SERIAL = "emulator-5554"
CAPTURE_DIR = "D:/higo-api"
REDPACKET_KEYWORDS = ["red_packet", "send_red", "recv_red", "lucky_bag", "lucky_gift"]
EVIDENCE_DIR = Path("output/evidence")
TC_FILE = Path("output/test_cases.json")
REPORT_FILE = Path("output/e2e_report.json")


def run_api_replay(engine: TestEngine) -> dict:
    """回放红包相关抓包接口。"""
    result = engine.run_captures_from_dir(
        CAPTURE_DIR,
        keywords=REDPACKET_KEYWORDS,
        max_count=None,
    )
    return {
        "total": result.total,
        "pass": result.passed,
        "fail": result.failed,
        "error": result.errored,
        "detail": [t.to_dict() for t in result.results],
    }


def pick_adb_tcs() -> list[dict]:
    """从 test_cases.json 挑出红包 UI/真机可执行的 TC。"""
    if not TC_FILE.exists():
        raise FileNotFoundError(
            f"{TC_FILE} 不存在 —— 9 阶段分析管线尚未生成 TC。"
            "请先让 pipeline 跑完（看到 output/test_cases.json）再执行本脚本。"
        )
    data = json.loads(TC_FILE.read_text(encoding="utf-8"))
    cases = data if isinstance(data, list) else data.get("test_cases", [data])
    adb_markers = ["红包入口", "弹窗", "倒计时", "档位", "发送", "挂件", "icon", "拉包",
                   "截图", "界面", "展示", "点击", "toast"]
    picked = []
    for tc in cases:
        title = tc.get("title", "")
        if any(m in title for m in adb_markers):
            picked.append(tc)
    # 控制本次试点数量，避免过多 LLM 转换耗时
    return picked[:5]


def run_adb(engine: TestEngine, adb_tcs: list[dict]) -> dict:
    """将红包 UI TC 经 plan_from_test_case 转计划后真机执行。"""
    if not adb_tcs:
        return {"skipped": True, "reason": "no adb-able TC"}
    results = []
    for tc in adb_tcs:
        tc_id = tc.get("id", "?")
        print(f"\n--- ADB TC: {tc_id} {tc.get('title','')[:40]} ---")
        try:
            plan = ExecutionPlanner.plan_from_test_case(tc)
            r = engine.run_plan(plan)
            results.append(r.to_dict())
            print(f"  status={r.status} steps={len(r.step_results)}")
        except Exception as e:  # noqa: BLE001
            print(f"  error: {e}")
            results.append({"tc_id": tc_id, "status": "error", "error": str(e)})
    return {"skipped": False, "detail": results}


def main() -> None:
    engine = TestEngine(
        adb_device_serial=DEVICE_SERIAL,
        api_base_url="https://api-chat-test.youyisia.com",
        evidence_dir=str(EVIDENCE_DIR),
        validate_plans=False,
        capability=None,
    )

    print("=" * 60)
    print("阶段 A：API 抓包回放（红包相关端点）")
    print("=" * 60)
    api = run_api_replay(engine)
    print(f"API 回放: {api['pass']} PASS / {api['fail']} FAIL / {api['error']} ERROR / {api['total']} TOTAL")
    for d in api["detail"]:
        s = d.get("status", "?")
        print(f"  [{s.upper():<7}] {d.get('tc_id','?')}: {d.get('title','')[:50]}")

    print("\n" + "=" * 60)
    print("阶段 B：ADB 真机执行（红包 UI TC）")
    print("=" * 60)
    try:
        adb_tcs = pick_adb_tcs()
        print(f"挑出 ADB 候选 TC {len(adb_tcs)} 个")
        adb = run_adb(engine, adb_tcs)
    except FileNotFoundError as e:
        print(f"【跳过 ADB】{e}")
        adb = {"skipped": True, "reason": str(e)}

    report = {"api": api, "adb": adb}
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nE2E 报告已写入: {REPORT_FILE}")

    engine.close()


if __name__ == "__main__":
    main()