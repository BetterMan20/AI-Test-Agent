"""S4 用例生成联调：读取 test_design.json，跑 testcase_generator 并落盘 test_cases.json。"""
import json
from agents.testcase_generator import TestCaseGenerator

with open("output/test_design.json", "r", encoding="utf-8") as f:
    test_design = json.load(f)

n_tp = len(test_design.get("test_points", []))
print(f"[S4Gen] 读取 test_design: test_points={n_tp} 个, 开始用例生成...", flush=True)

result = TestCaseGenerator().run(test_design)

with open("output/test_cases.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"[S4Gen] 完成。已写入 output/test_cases.json", flush=True)
print(f"  test_cases={len(result.get('test_cases', []))} blocked_cases={len(result.get('blocked_cases', []))}", flush=True)
