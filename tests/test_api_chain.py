"""Smoke test — API execution chain: TC → Plan → API → Evidence → Verification → Result.

Runs a local mock HTTP server, executes a POST request, and verifies that:
  1. The execution result is PASS.
  2. Four evidence files are auto-saved: request.json, response.json, headers.json, execution.json.
  3. Each evidence file contains correct data.
"""

from __future__ import annotations

import json
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest

from execution.context import ExecutionContext, EnvironmentConfig
from execution.planner import ExecutionPlanner
from execution.runner import ExecutionRunner
from evidence.collector import EvidenceCollector
from evidence.store import EvidenceStore
from tools.api.client import APIClient


# ── Mock server ──────────────────────────────────────────────

class _MockHandler(BaseHTTPRequestHandler):
    """Echoes back a fixed JSON response for POST /api/send-expiration-notice."""

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


@pytest.fixture()
def mock_server():
    server = HTTPServer(("127.0.0.1", 0), _MockHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


@pytest.fixture()
def evidence_dir(tmp_path: Path) -> Path:
    ev_dir = tmp_path / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    yield ev_dir
    if ev_dir.exists():
        shutil.rmtree(ev_dir, ignore_errors=True)


# ── Plan definition (TC → Execution Plan) ─────────────────────

PLAN_DATA = {
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


# ── Tests ─────────────────────────────────────────────────────


class TestAPIChain:
    """端到端验证 API 执行链路。"""

    def test_full_chain_pass(self, mock_server: str, evidence_dir: Path) -> None:
        # 1. TC → Execution Plan
        plan = ExecutionPlanner.plan_from_dict(PLAN_DATA)

        # 2. Set up execution infrastructure
        store = EvidenceStore(base_dir=str(evidence_dir))
        collector = EvidenceCollector(store)
        api_client = APIClient(base_url=mock_server)
        runner = ExecutionRunner(
            api_client=api_client,
            evidence_collector=collector,
        )

        # 3. Execute
        env = EnvironmentConfig(api_base_url=mock_server)
        context = ExecutionContext(environment=env, tc_id=plan.tc_id)
        result = runner.run_plan(plan, context)

        # 4. Assert result is PASS
        assert result.status == "pass", f"Expected pass, got {result.status}"
        assert len(result.step_results) == 1
        step_result = result.step_results[0]
        assert step_result.status == "pass"
        assert step_result.assertions_passed == 4
        assert step_result.assertions_failed == 0

    def test_evidence_files_created(self, mock_server: str, evidence_dir: Path) -> None:
        plan = ExecutionPlanner.plan_from_dict(PLAN_DATA)
        store = EvidenceStore(base_dir=str(evidence_dir))
        collector = EvidenceCollector(store)
        api_client = APIClient(base_url=mock_server)
        runner = ExecutionRunner(
            api_client=api_client,
            evidence_collector=collector,
        )
        env = EnvironmentConfig(api_base_url=mock_server)
        context = ExecutionContext(environment=env, tc_id=plan.tc_id)
        runner.run_plan(plan, context)

        tc_dir = evidence_dir / plan.tc_id
        expected_files = [
            "step1_request.json",
            "step1_response.json",
            "step1_headers.json",
            "step1_execution.json",
        ]
        for fname in expected_files:
            assert (tc_dir / fname).exists(), f"Missing evidence file: {fname}"

    def test_request_evidence_content(self, mock_server: str, evidence_dir: Path) -> None:
        plan = ExecutionPlanner.plan_from_dict(PLAN_DATA)
        store = EvidenceStore(base_dir=str(evidence_dir))
        collector = EvidenceCollector(store)
        runner = ExecutionRunner(
            api_client=APIClient(base_url=mock_server),
            evidence_collector=collector,
        )
        env = EnvironmentConfig(api_base_url=mock_server)
        context = ExecutionContext(environment=env, tc_id=plan.tc_id)
        runner.run_plan(plan, context)

        req = json.loads(
            (evidence_dir / plan.tc_id / "step1_request.json").read_text("utf-8")
        )
        assert req["method"] == "POST"
        assert req["path"] == "/api/send-expiration-notice"
        assert req["headers"]["Content-Type"] == "application/json"
        assert req["body"]["user_id"] == "U001"
        assert req["body"]["card_name"] == "SVIP体验卡"

    def test_response_evidence_content(self, mock_server: str, evidence_dir: Path) -> None:
        plan = ExecutionPlanner.plan_from_dict(PLAN_DATA)
        store = EvidenceStore(base_dir=str(evidence_dir))
        collector = EvidenceCollector(store)
        runner = ExecutionRunner(
            api_client=APIClient(base_url=mock_server),
            evidence_collector=collector,
        )
        env = EnvironmentConfig(api_base_url=mock_server)
        context = ExecutionContext(environment=env, tc_id=plan.tc_id)
        runner.run_plan(plan, context)

        resp = json.loads(
            (evidence_dir / plan.tc_id / "step1_response.json").read_text("utf-8")
        )
        assert resp["success"] is True
        assert resp["data"]["card_name"] == "SVIP体验卡"
        assert resp["data"]["days_remaining"] == 0

    def test_headers_evidence_content(self, mock_server: str, evidence_dir: Path) -> None:
        plan = ExecutionPlanner.plan_from_dict(PLAN_DATA)
        store = EvidenceStore(base_dir=str(evidence_dir))
        collector = EvidenceCollector(store)
        runner = ExecutionRunner(
            api_client=APIClient(base_url=mock_server),
            evidence_collector=collector,
        )
        env = EnvironmentConfig(api_base_url=mock_server)
        context = ExecutionContext(environment=env, tc_id=plan.tc_id)
        runner.run_plan(plan, context)

        headers = json.loads(
            (evidence_dir / plan.tc_id / "step1_headers.json").read_text("utf-8")
        )
        ct = headers.get("Content-Type") or headers.get("content-type", "")
        assert "application/json" in ct

    def test_execution_evidence_content(self, mock_server: str, evidence_dir: Path) -> None:
        plan = ExecutionPlanner.plan_from_dict(PLAN_DATA)
        store = EvidenceStore(base_dir=str(evidence_dir))
        collector = EvidenceCollector(store)
        runner = ExecutionRunner(
            api_client=APIClient(base_url=mock_server),
            evidence_collector=collector,
        )
        env = EnvironmentConfig(api_base_url=mock_server)
        context = ExecutionContext(environment=env, tc_id=plan.tc_id)
        runner.run_plan(plan, context)

        meta = json.loads(
            (evidence_dir / plan.tc_id / "step1_execution.json").read_text("utf-8")
        )
        assert meta["tc_id"] == "TC-API-001"
        assert meta["step_id"] == 1
        assert meta["step_type"] == "api"
        assert meta["status_code"] == 200
        assert meta["status"] == "pass"
        assert meta["assertions_passed"] == 4
        assert meta["assertions_failed"] == 0

    def test_assertion_failure_produces_fail(
        self, mock_server: str, evidence_dir: Path
    ) -> None:
        """Wrong expected status code should produce FAIL, not PASS."""
        plan_data = {
            **PLAN_DATA,
            "steps": [
                {
                    **PLAN_DATA["steps"][0],
                    "assertions": [
                        {"type": "status_code", "expected": 404},
                    ],
                }
            ],
        }
        plan = ExecutionPlanner.plan_from_dict(plan_data)
        store = EvidenceStore(base_dir=str(evidence_dir))
        collector = EvidenceCollector(store)
        runner = ExecutionRunner(
            api_client=APIClient(base_url=mock_server),
            evidence_collector=collector,
        )
        env = EnvironmentConfig(api_base_url=mock_server)
        context = ExecutionContext(environment=env, tc_id=plan.tc_id)
        result = runner.run_plan(plan, context)

        assert result.status == "fail"
        assert result.step_results[0].assertions_failed == 1
