"""S3 链路分析联调 step2：用新业务模型 + 新 gaps 跑 test_design，落盘 test_design.json。"""
import json
from agents.test_design import TestDesign

with open("output/analysis_chunked.json", "r", encoding="utf-8") as f:
    analysis = json.load(f)
with open("output/gaps.json", "r", encoding="utf-8") as f:
    gaps = json.load(f)

n_model = sum(len(v) for v in analysis.values() if isinstance(v, list))
n_gaps = len(gaps.get("gaps", []))
print(f"[S3Design] 读取 analysis 模型元素: {n_model} 个, gaps: {n_gaps} 个, 开始测试设计...", flush=True)

design = TestDesign().run(analysis, gaps)

with open("output/test_design.json", "w", encoding="utf-8") as f:
    json.dump(design, f, ensure_ascii=False, indent=2)

tm = design.get("test_model", {})
print(f"[S3Design] 完成。已写入 output/test_design.json", flush=True)
print(f"  test_objects={len(tm.get('test_objects', []))} state_dimensions={len(tm.get('state_dimensions', []))} "
      f"condition_dimensions={len(tm.get('condition_dimensions', []))} business_flows={len(tm.get('business_flows', []))} "
      f"risk_points={len(tm.get('risk_points', []))} test_scenarios={len(design.get('test_scenarios', []))} "
      f"test_points={len(design.get('test_points', []))} blocked_points={len(design.get('blocked_points', []))}", flush=True)
