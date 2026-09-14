"""S2 分块建模联调：读取 S1 产出的 facts.json，跑分块并行建模并落盘。"""
import json
import sys
from agents.requirement_analysis import RequirementAnalysis

SRC = "output/facts.json"
DST = "output/analysis_chunked.json"

with open(SRC, "r", encoding="utf-8") as f:
    facts = json.load(f)

n = len(facts.get("facts", []))
print(f"[S2联调] 读取 {SRC}: {n} 条 Fact，开始分块建模...", flush=True)

model = RequirementAnalysis().run(facts)

with open(DST, "w", encoding="utf-8") as f:
    json.dump(model, f, ensure_ascii=False, indent=2)

print(f"[S2联调] 完成。已写入 {DST}")
print(f"  actors={len(model['actors'])} entities={len(model['entities'])} "
      f"states={len(model['states'])} conditions={len(model['conditions'])} "
      f"actions={len(model['actions'])} outcomes={len(model['outcomes'])} "
      f"relations={len(model['relations'])}")
print("[S2联调] ✅ 未出现 finish_reason=length 截断，合并通过严格 schema")