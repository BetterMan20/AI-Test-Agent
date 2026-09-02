"""Demo — API execution chain: TC → Plan → API → Evidence → Verification → Result.

Run:  python -m tests.demo_api_chain
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

from execution.context import ExecutionContext, EnvironmentConfig
from execution.planner import ExecutionPlanner
from execution.runner import ExecutionRunner
from evidence.collector import EvidenceCollector
from evidence.store import EvidenceStore
from tools.api.client import APIClient


class MockHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        _ = self.rfile.read(length)
        body = json.dumps(
            {
                "success": True,
                "message": "体验卡过期提醒已发送",
                "data": {
                    "card_name": "SVIP体验卡",
                    "days_remaining": 0,
                    "user_id": "U001",
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


PLAN = {
    "tc_id": "TC-API-001",
    "title": "API执行链路验证-体验卡过期通知",
    "preconditions": ["用户持有有效体验卡", "系统设置为当天过期"],
    "test_data": ["体验卡=SVIP体验卡(7天)", "用户ID=U001"],
    "steps": [
        {
            "step_id": 1,
            "type": "api",
            "description": "POST /api/send-expiration-notice 发送体验卡过期提醒",
            "config": {
                "method": "POST",
                "path": "/api/send-expiration-notice",
                "headers": {"Content-Type": "application/json"},
                "body": {"user_id": "U001", "card_name": "SVIP体验卡"},
            },
            "assertions": [
                {"type": "status_code", "expected": 200},
                {"type": "json_path", "path": "$.success", "expected": True},
                {"type": "json_path", "path": "$.data.card_name", "expected": "SVIP体验卡"},
                {"type": "text_contains", "expected": "体验卡过期提醒"},
            ],
            "evidence_types": ["api_response"],
        }
    ],
}


def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), MockHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"

    evidence_dir = Path("output/evidence_demo")
    if evidence_dir.exists():
        import shutil

        shutil.rmtree(evidence_dir)

    try:
        plan = ExecutionPlanner.plan_from_dict(PLAN)
        store = EvidenceStore(base_dir=str(evidence_dir))
        collector = EvidenceCollector(store)
        api_client = APIClient(base_url=base_url)
        runner = ExecutionRunner(
            api_client=api_client,
            evidence_collector=collector,
        )
        env = EnvironmentConfig(api_base_url=base_url)
        context = ExecutionContext(environment=env, tc_id=plan.tc_id)
        result = runner.run_plan(plan, context)

        print("=" * 60)
        print("Execution Result")
        print("=" * 60)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))

        print("\n" + "=" * 60)
        print("Evidence Files")
        print("=" * 60)
        tc_dir = evidence_dir / plan.tc_id
        for fname in sorted(tc_dir.iterdir()):
            print(f"\n--- {fname.name} ---")
            print(fname.read_text("utf-8"))

    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
