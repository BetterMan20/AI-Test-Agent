"""独立跑 Stage 2 事实抽取，验证 32000 max_tokens 是否够。"""
from __future__ import annotations

import json
from pathlib import Path

from agents.fact_extraction import FactExtraction
from configs.skills import SKILLS


def main() -> None:
    parsed = Path("output/parsed.json").read_text(encoding="utf-8")
    # parsed.json 是 {"parsed": ...} 结构时取出来；否则直接当字符串
    try:
        obj = json.loads(parsed)
        if isinstance(obj, dict) and "parsed" in obj:
            text = obj["parsed"]
        elif isinstance(obj, dict) and len(obj) == 1:
            text = next(iter(obj.values()))
        else:
            text = parsed
    except Exception:
        text = parsed

    ext = FactExtraction()
    result = ext.run(str(text))
    facts = result.get("facts", [])
    print(f"N_FACTS={len(facts)}")
    Path("output/facts.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("WROTE output/facts.json")


if __name__ == "__main__":
    main()