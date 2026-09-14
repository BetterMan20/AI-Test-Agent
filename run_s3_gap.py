"""S3 链路分析联调 step1：用新 facts + 新业务模型重跑 gap_detection，落盘 gaps.json。"""
import json
from agents.gap_detection import GapDetection

with open("output/facts.json", "r", encoding="utf-8") as f:
    facts = json.load(f)
with open("output/analysis_chunked.json", "r", encoding="utf-8") as f:
    analysis = json.load(f)

n_facts = len(facts.get("facts", []))
n_model = sum(len(v) for v in analysis.values() if isinstance(v, list))
print(f"[S3Gap] 读取 facts: {n_facts} 条, analysis 模型元素: {n_model} 个, 开始缺口检测...", flush=True)

gaps = GapDetection().run(facts, analysis)

with open("output/gaps.json", "w", encoding="utf-8") as f:
    json.dump(gaps, f, ensure_ascii=False, indent=2)

n_gaps = len(gaps.get("gaps", []))
print(f"[S3Gap] 完成。已写入 output/gaps.json, gaps={n_gaps}, summary={gaps.get('summary')}", flush=True)
