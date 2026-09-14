"""只读的 API 回放验证：回放红包接口并把结果写入 JSON，stdout 全程英文避免编码问题。"""
from __future__ import annotations

import json
from pathlib import Path

from engine import TestEngine

CAPTURE_DIR = "D:/higo-api"
KEYWORDS = ["red_packet", "send_red", "recv_red", "lucky_bag", "lucky_gift"]
OUT = Path("output/api_replay_check.json")


def main() -> None:
    engine = TestEngine(
        api_base_url="https://api-chat-test.youyisia.com",
        evidence_dir="output/evidence",
        validate_plans=False,
        capability=None,
    )
    result = engine.run_captures_from_dir(CAPTURE_DIR, keywords=KEYWORDS)

    report = {
        "summary": {
            "total": result.total, "pass": result.passed,
            "fail": result.failed, "error": result.errored,
        },
        "results": result.to_dict().get("results", []),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT)

    engine.close()


if __name__ == "__main__":
    main()