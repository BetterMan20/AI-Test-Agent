"""真实设备 Appium 执行演示：把 AppiumController 接入 execution/ 执行 appium 步骤.

被测 App: com.example.live (KTV live)  设备: emulator-5554
每条 appium 步骤采集 appium_action.json / appium_page_source.xml / appium_execution.json 三件套，
下钻步骤额外采集 screenshot。

用法:
    python tests/demo_real_appium.py            # 安全冒烟：建会话 → dump 页面 → 断言 hierarchy
    python tests/demo_real_appium.py --drill    # 追加业务下钻（需设备处于直播间且红包/礼物入口可见）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from engine import TestEngine
from execution.planner import ExecutionPlanner

DEVICE_SERIAL = "emulator-5554"
PACKAGE = "com.example.live"
EVIDENCE_DIR = Path("output/evidence_appium_chain")
TC_ID = "TC-APPIUM-REAL-001"

ENTRY_KW = "red|packet|红包|gift|礼物"
PANEL_KW = "send|发送|coin|金币|confirm|发红包"


def build_plan(drill: bool) -> dict:
    steps = [
        {
            "step_id": 1,
            "type": "appium",
            "description": "懒启动 server+session，dump 当前页面源",
            "config": {"operation": "page_source"},
            "assertions": [
                {"type": "text_contains", "expected": "hierarchy"},
            ],
            "evidence_types": ["appium_snapshot"],
        },
    ]
    if drill:
        steps.append({
            "step_id": 2,
            "type": "appium",
            "description": f"按关键词下钻入口({ENTRY_KW}) → 校验发送面板({PANEL_KW})",
            "config": {"operation": "tap_by_keyword", "keyword": ENTRY_KW, "timeout": 10},
            "assertions": [
                {"type": "text_contains", "expected": PANEL_KW},
            ],
            "evidence_types": ["appium_snapshot", "screenshot"],
        })
    return {
        "tc_id": TC_ID,
        "title": "真实设备 Appium 混合编排冒烟" + ("（含业务下钻）" if drill else ""),
        "preconditions": [f"设备在线: {DEVICE_SERIAL}", f"已安装 {PACKAGE}"],
        "test_data": [f"device={DEVICE_SERIAL}", f"package={PACKAGE}"],
        "steps": steps,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--drill", action="store_true", help="追加按关键词下钻入口的业务步骤")
    args = ap.parse_args()

    engine = TestEngine(
        adb_device_serial=DEVICE_SERIAL,
        appium_device_serial=DEVICE_SERIAL,
        evidence_dir=str(EVIDENCE_DIR),
        validate_plans=False,  # 确定性计划，跳过 LLM 驱动的 Plan 校验
    )
    try:
        plan = ExecutionPlanner.plan_from_dict(build_plan(args.drill))
        result = engine.run_plan(plan)
    finally:
        engine.close()

    print("\n===== 执行结果 =====")
    print(f"TC 状态: {result.status}")
    for sr in result.step_results:
        print(
            f"  step{sr.step_id} [{sr.step_type}] -> {sr.status} "
            f"(assertions: {sr.assertions_passed} pass / {sr.assertions_failed} fail)"
        )

    print("\n===== 证据文件 =====")
    tc_dir = EVIDENCE_DIR / TC_ID
    found = sorted(p.name for p in tc_dir.glob("*")) if tc_dir.exists() else []
    for name in found:
        print(f"  [OK] {name}")
    suffixes = ("_appium_action.json", "_appium_page_source.xml", "_appium_execution.json")
    missing = [s for s in suffixes if not any(n.endswith(s) for n in found)]
    print(f"\n三件套缺失数: {len(missing)}; 证据 refs 合计: {len(result.evidence_refs)}")

    action = next((n for n in found if n.endswith("_appium_action.json")), None)
    if action:
        sample = json.loads((tc_dir / action).read_text(encoding="utf-8"))
        print(f"证据样例 {action} -> {json.dumps(sample, ensure_ascii=False)[:200]}")


if __name__ == "__main__":
    main()
