"""真实设备 ADB 执行演示：把 ADBClient 接入 execution/ 执行 ADB 步骤.

被测 App: com.example.live (KTV live)  设备: emulator-5554
每条 adb 步骤均采集 adb_command.json / adb_output.json / adb_execution.json 三类证据，
并额外对指定步骤采集 screenshot + logcat。
"""

from __future__ import annotations

import json
from pathlib import Path

from engine import TestEngine
from execution.planner import ExecutionPlanner

DEVICE_SERIAL = "emulator-5554"
PACKAGE = "com.example.live"
LAUNCHER = "com.example.live/com.global.hiyapro.ui.SplashActivity"
EVIDENCE_DIR = Path("output/evidence")

PLAN_DATA = {
    "tc_id": "TC-ADB-001",
    "title": "真实设备 Smoke - 安装校验 / 拉起 App / 前台校验",
    "preconditions": [f"设备在线: {DEVICE_SERIAL}", f"已安装 {PACKAGE}"],
    "test_data": [f"device={DEVICE_SERIAL}", f"package={PACKAGE}"],
    "steps": [
        {
            "step_id": 1,
            "type": "adb",
            "description": f"pm list packages {PACKAGE}  校验 App 是否安装",
            "config": {"command": f"pm list packages {PACKAGE}"},
            "assertions": [
                {"type": "text_contains", "expected": PACKAGE},
            ],
            "evidence_types": [],
        },
        {
            "step_id": 2,
            "type": "adb",
            "description": f"am start -n {LAUNCHER}  拉起 App",
            "config": {"command": f"am start -n {LAUNCHER}"},
            "assertions": [
                {"type": "text_contains", "expected": "Starting"},
            ],
            "evidence_types": ["screenshot"],
        },
        {
            "step_id": 3,
            "type": "adb",
            "description": f"dumpsys activity activities | grep ResumedActivity  校验前台",
            "config": {
                "command": "dumpsys activity activities | grep ResumedActivity",
            },
            "assertions": [
                {"type": "text_contains", "expected": "com.example.live/"},
            ],
            "evidence_types": ["logcat"],
        },
    ],
}


def main() -> None:
    engine = TestEngine(
        adb_device_serial=DEVICE_SERIAL,
        evidence_dir=str(EVIDENCE_DIR),
        validate_plans=False,  # 确定性计划，跳过 LLM 驱动的 Plan 校验
    )

    plan = ExecutionPlanner.plan_from_dict(PLAN_DATA)
    result = engine.run_plan(plan)

    print("\n===== 执行结果 =====")
    print(f"TC 状态: {result.status}")
    for sr in result.step_results:
        print(
            f"  step{sr.step_id} [{sr.step_type}] -> {sr.status} "
            f"(assertions: {sr.assertions_passed} pass / {sr.assertions_failed} fail)"
        )

    print("\n===== 证据文件 =====")
    tc_dir = EVIDENCE_DIR / PLAN_DATA["tc_id"]
    expected = [
        "step1_adb_command.json",
        "step1_adb_output.json",
        "step1_adb_execution.json",
        "step2_adb_command.json",
        "step2_adb_output.json",
        "step2_adb_execution.json",
        "step2_screenshot.png",
        "step3_adb_command.json",
        "step3_adb_output.json",
        "step3_adb_execution.json",
        "step3_logcat.txt",
    ]
    for fname in expected:
        found = (tc_dir / fname).exists()
        print(f"  [{'OK ' if found else 'MISS'}] {fname}")

    missing = [f for f in expected if not (tc_dir / f).exists()]
    print(f"\n缺文件数: {len(missing)}; 步骤证据 refs 合计: {len(result.evidence_refs)}")

    # 展示一个证据样例
    cmd = json.loads((tc_dir / "step2_adb_command.json").read_text(encoding="utf-8"))
    print(f"证据样例 step2_adb_command.json -> {cmd}")


if __name__ == "__main__":
    main()