"""Demo — full E2E chain: API + DB + Android.

  Step 1: API POST /api/grant-reward      → code == 0     (接口成功)
  Step 2: DB SELECT reward_status          → reward_status == 1 (业务成功)
  Step 3: ADB am start (打开App)           → "Starting" in output
  Step 4: ADB input tap (点击领取)          → screenshot + logcat

Run:  python -m tests.demo_e2e_chain
"""

from __future__ import annotations

import json
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

from execution.context import ExecutionContext, EnvironmentConfig
from execution.planner import ExecutionPlanner
from execution.runner import ExecutionRunner
from evidence.collector import EvidenceCollector
from evidence.store import EvidenceStore
from tools.api.client import APIClient


class MockAPIHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        _ = self.rfile.read(length)
        body = json.dumps(
            {"code": 0, "message": "success", "data": {"reward_id": "RW-001"}},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


class MockDBClient:
    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = [
            {"reward_status": 1, "card_name": "SVIP体验卡", "user_id": "U001"}
        ]

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def query(self, sql: str, params: Any | None = None) -> list[dict[str, Any]]:
        return list(self._rows)

    def execute(self, sql: str, params: Any | None = None) -> int:
        return len(self._rows)


class MockADBClient:
    _MOCK_SHELL = {
        "am start": (
            "Starting: Intent { cmp=com.higo.app/.MainActivity }\n"
            "WARNING: not logged in\n"
        ),
        "input tap": "",
    }

    def shell(self, command: str) -> str:
        for prefix, output in self._MOCK_SHELL.items():
            if command.startswith(prefix):
                return output
        return ""

    def screenshot(self, save_path: str) -> str:
        Path(save_path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        return save_path

    def logcat(self, filter_spec: str = "", dump: bool = True) -> str:
        return (
            "09-01 10:00:00.000  I ActivityManager: Start com.higo.app\n"
            "09-01 10:00:01.000  D RewardFragment: Showing reward dialog\n"
            "09-01 10:00:02.000  I RewardService: reward_status=1\n"
        )


PLAN = {
    "tc_id": "TC-E2E-001",
    "title": "E2E验证-发奖励→DB验证→打开App→截图",
    "preconditions": ["用户U001持有SVIP体验卡", "体验卡当天过期", "Android设备已连接"],
    "test_data": ["用户ID=U001", "体验卡=SVIP体验卡(7天)", "设备=emulator-5554"],
    "steps": [
        {
            "step_id": 1,
            "type": "api",
            "description": "POST /api/grant-reward 发放奖品",
            "config": {
                "method": "POST",
                "path": "/api/grant-reward",
                "headers": {"Content-Type": "application/json"},
                "body": {"user_id": "U001", "card_name": "SVIP体验卡"},
            },
            "assertions": [
                {"type": "status_code", "expected": 200},
                {"type": "json_path", "path": "$.code", "expected": 0},
            ],
            "evidence_types": ["api_response"],
        },
        {
            "step_id": 2,
            "type": "db",
            "description": "SELECT reward_status FROM user_rewards WHERE user_id='U001'",
            "config": {
                "phase": "verify",
                "query": "SELECT reward_status, card_name FROM user_rewards WHERE user_id = %s",
                "params": ["U001"],
            },
            "assertions": [
                {"type": "json_path", "path": "$.0.reward_status", "expected": 1},
                {"type": "json_path", "path": "$.0.card_name", "expected": "SVIP体验卡"},
            ],
            "evidence_types": ["db_snapshot"],
        },
        {
            "step_id": 3,
            "type": "adb",
            "description": "am start -n com.higo.app/.MainActivity 打开App",
            "config": {"command": "am start -n com.higo.app/.MainActivity"},
            "assertions": [
                {"type": "text_contains", "expected": "Starting"},
                {"type": "text_contains", "expected": "com.higo.app"},
            ],
            "evidence_types": ["screenshot"],
        },
        {
            "step_id": 4,
            "type": "adb",
            "description": "input tap 540 960 点击领取按钮 + 截图 + 日志",
            "config": {"command": "input tap 540 960"},
            "assertions": [],
            "evidence_types": ["screenshot", "logcat"],
        },
    ],
}


def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), MockAPIHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"

    evidence_dir = Path("output/evidence_e2e_demo")
    if evidence_dir.exists():
        shutil.rmtree(evidence_dir)

    try:
        plan = ExecutionPlanner.plan_from_dict(PLAN)
        store = EvidenceStore(base_dir=str(evidence_dir))
        collector = EvidenceCollector(store)
        api_client = APIClient(base_url=base_url)
        db_client = MockDBClient()
        adb_client = MockADBClient()
        runner = ExecutionRunner(
            api_client=api_client,
            db_client=db_client,
            adb_client=adb_client,
            evidence_collector=collector,
        )
        env = EnvironmentConfig(api_base_url=base_url)
        context = ExecutionContext(environment=env, tc_id=plan.tc_id)
        result = runner.run_plan(plan, context)

        print("=" * 60)
        print("E2E Execution Result")
        print("=" * 60)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))

        print("\n" + "=" * 60)
        print("All Evidence Files")
        print("=" * 60)
        tc_dir = evidence_dir / plan.tc_id
        for fname in sorted(tc_dir.iterdir()):
            if fname.name.endswith("_meta.json"):
                continue
            print(f"\n--- {fname.name} ---")
            if fname.suffix == ".png":
                print(f"(binary, {fname.stat().st_size} bytes)")
            else:
                content = fname.read_text("utf-8")
                if len(content) > 300:
                    print(content[:300] + "\n... (truncated)")
                else:
                    print(content)

    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
