"""S5 用例评审联调：validator(LLM) -> quality_review(确定性) -> release_gate(确定性)，全部落盘。"""
import json
from agents.testcase_validator import TestCaseValidator
from agents.quality_review import QualityReview
from agents.release_gate import ReleaseGate

with open("output/analysis_chunked.json", "r", encoding="utf-8") as f:
    analysis = json.load(f)
with open("output/facts.json", "r", encoding="utf-8") as f:
    facts = json.load(f)
with open("output/gaps.json", "r", encoding="utf-8") as f:
    gaps = json.load(f)
with open("output/test_design.json", "r", encoding="utf-8") as f:
    test_design = json.load(f)
with open("output/test_cases.json", "r", encoding="utf-8") as f:
    test_cases = json.load(f)

print("[S5.1] 开始用例校验 (LLM)...", flush=True)
validation = TestCaseValidator().run(analysis, test_design, test_cases)
with open("output/validation_result.json", "w", encoding="utf-8") as f:
    json.dump(validation, f, ensure_ascii=False, indent=2)
print(f"[S5.1] 完成。validation_status={validation.get('validation_status')}, issues={len(validation.get('issues', []))}", flush=True)

print("[S5.2] 开始质量评审 (确定性)...", flush=True)
quality = QualityReview().run(facts, analysis, gaps, test_design, test_cases, validation)
with open("output/quality_review.json", "w", encoding="utf-8") as f:
    json.dump(quality, f, ensure_ascii=False, indent=2)
print(f"[S5.2] 完成。quality_status={quality.get('quality_status')}, p0={quality.get('summary', {}).get('p0_count')}, p1={quality.get('summary', {}).get('p1_count')}", flush=True)

print("[S5.3] 开始发布门禁 (确定性)...", flush=True)
gate = ReleaseGate().run(quality)
with open("output/release_gate.json", "w", encoding="utf-8") as f:
    json.dump(gate, f, ensure_ascii=False, indent=2)
print(f"[S5.3] 完成。gate={gate.get('gate')}, reasons={gate.get('reasons')}", flush=True)
print("[S5] S5 用例评审全部完成", flush=True)
