"""S6 批量回归联调：抓包API回放(原语A) + 文档级TC批量执行(原语C) + ADB/UI验证(原语B)。

仅跑执行阶段，不依赖 S1-S5（TC 默认复用 output/test_cases.json）。
用法:
  python run_s6_execution.py [capture_dir] [endpoint_substring] [device_serial]
"""
import json
import sys

from execution.batch_regression import RegressionConfig, run_batch_regression

cap = sys.argv[1] if len(sys.argv) > 1 else "D:/higo-api"
sub = sys.argv[2] if len(sys.argv) > 2 else "send_red_packet"
serial = sys.argv[3] if len(sys.argv) > 3 else "emulator-5554"

report, path, _ = run_batch_regression(RegressionConfig(
    capture_dir=cap,
    endpoint_substring=sub,
    tc_field="output/test_cases.json#test_cases",
    device_serial=serial,
    evidence_root="output/evidence_batch_regression",
))
print("\n========== S6 批量回归 汇总 ==========", flush=True)
print(json.dumps(report.summary, ensure_ascii=False, indent=2))
print(f"报告: {path}", flush=True)