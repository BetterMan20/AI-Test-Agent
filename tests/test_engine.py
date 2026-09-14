"""Test — TestEngine 统一引擎产品级测试.

验证两个入口汇聚到同一个引擎:
  入口 A: Test Case → plan_from_test_case() → ExecutionPlan
  入口 B: Capture   → plan_from_capture()   → ExecutionPlan
  两者 → ExecutionRunner → API/DB/ADB → Assertion + Evidence
"""

from __future__ import annotations

import json
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from engine import TestEngine
from execution.planner import ExecutionPlan
from execution.result import ExecutionResult, TestCaseResult
from tools.whistle_parser import CapturedAPI


# ── Mock HTTP server ──────────────────────────────────────────

class MockAPIHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        _ = self.rfile.read(length)
        body = json.dumps(
            {"ret": 1, "msg": "ok", "data": {"user_id": "U001", "balance": 100}},
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
    server = HTTPServer(("127.0.0.1", 0), MockAPIHandler)
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


# ── Test data ─────────────────────────────────────────────────

MANUAL_PLAN = {
    "tc_id": "TC-MANUAL-001",
    "title": "手动构造 Plan 测试",
    "steps": [{
        "step_id": 1,
        "type": "api",
        "description": "POST /api/test",
        "config": {
            "method": "POST",
            "path": "/api/test",
            "headers": {"Content-Type": "application/json"},
            "body": {"user_id": "U001"},
        },
        "assertions": [
            {"type": "status_code", "expected": 200},
            {"type": "json_path", "path": "$.ret", "expected": 1},
        ],
        "evidence_types": ["api_response"],
    }],
}

CAPTURED_API = CapturedAPI(
    url="https://127.0.0.1:9999/live/account/test?sign=abc123",
    method="POST",
    req_headers={"host": "127.0.0.1:9999", "content-type": "application/json"},
    req_body={"user_id": "U001", "token": "test_token"},
    status_code=200,
    res_headers={"content-type": "application/json"},
    res_body={"ret": 1, "msg": "ok"},
    timestamp=0,
    capture_id="test-cap-001",
    source_file="test.txt",
)


# ── Tests: 入口 C (手动 Plan) ─────────────────────────────────

class TestEngineManualPlan:
    """入口 C: 手动构造 ExecutionPlan."""

    def test_run_plan_returns_result(self, mock_server: str, evidence_dir: Path):
        engine = TestEngine(
            api_base_url=mock_server,
            evidence_dir=str(evidence_dir),
        )
        plan = ExecutionPlan(
            tc_id="TC-MANUAL-001",
            title="手动 Plan",
            steps=[],
        )
        from execution.planner import ExecutionStep
        plan.steps.append(ExecutionStep(
            step_id=1,
            step_type="api",
            description="POST /api/test",
            action=MANUAL_PLAN["steps"][0]["config"],
            assertions=MANUAL_PLAN["steps"][0]["assertions"],
            evidence_types=["api_response"],
        ))
        result = engine.run_plan(plan)
        assert isinstance(result, TestCaseResult)
        assert result.status == "pass"
        engine.close()

    def test_run_plans_batch(self, mock_server: str, evidence_dir: Path):
        engine = TestEngine(
            api_base_url=mock_server,
            evidence_dir=str(evidence_dir),
        )
        plan_data = {**MANUAL_PLAN, "tc_id": "TC-BATCH-001"}
        plan = ExecutionPlanner_plan_from_dict(plan_data)
        result = engine.run_plans([plan])
        assert isinstance(result, ExecutionResult)
        assert result.total == 1
        assert result.passed == 1
        engine.close()

    def test_evidence_files_created(self, mock_server: str, evidence_dir: Path):
        engine = TestEngine(
            api_base_url=mock_server,
            evidence_dir=str(evidence_dir),
        )
        plan = ExecutionPlanner_plan_from_dict(MANUAL_PLAN)
        engine.run_plan(plan)
        tc_dir = evidence_dir / MANUAL_PLAN["tc_id"]
        assert (tc_dir / "step1_request.json").exists()
        assert (tc_dir / "step1_response.json").exists()
        assert (tc_dir / "step1_headers.json").exists()
        assert (tc_dir / "step1_execution.json").exists()
        engine.close()

    def test_response_content_verified(self, mock_server: str, evidence_dir: Path):
        engine = TestEngine(
            api_base_url=mock_server,
            evidence_dir=str(evidence_dir),
        )
        plan = ExecutionPlanner_plan_from_dict(MANUAL_PLAN)
        result = engine.run_plan(plan)

        response_path = evidence_dir / MANUAL_PLAN["tc_id"] / "step1_response.json"
        response = json.loads(response_path.read_text("utf-8"))
        assert response["ret"] == 1
        assert response["data"]["user_id"] == "U001"
        engine.close()


# ── Tests: 入口 B (Capture) ───────────────────────────────────

class TestEngineCapture:
    """入口 B: Whistle 抓包回放."""

    def test_run_capture_returns_result(self, mock_server: str, evidence_dir: Path):
        cap = CapturedAPI(
            url=f"{mock_server}/live/test?sign=abc",
            method="POST",
            req_headers={"content-type": "application/json"},
            req_body={"user_id": "U001"},
            status_code=200,
            res_headers={},
            res_body={"ret": 1},
            timestamp=0,
            capture_id="cap-001",
            source_file="test.txt",
        )
        engine = TestEngine(
            api_base_url=mock_server,
            evidence_dir=str(evidence_dir),
        )
        result = engine.run_capture(cap)
        assert isinstance(result, TestCaseResult)
        assert result.status == "pass"
        engine.close()

    def test_capture_evidence_files(self, mock_server: str, evidence_dir: Path):
        cap = CapturedAPI(
            url=f"{mock_server}/live/test?sign=abc",
            method="POST",
            req_headers={"content-type": "application/json"},
            req_body={"user_id": "U001"},
            status_code=200,
            res_headers={},
            res_body={"ret": 1},
            timestamp=0,
            capture_id="cap-002",
            source_file="test.txt",
        )
        engine = TestEngine(
            api_base_url=mock_server,
            evidence_dir=str(evidence_dir),
        )
        result = engine.run_capture(cap)

        tc_dir = evidence_dir / result.tc_id
        assert (tc_dir / "step1_request.json").exists()
        assert (tc_dir / "step1_response.json").exists()
        assert (tc_dir / "step1_headers.json").exists()
        assert (tc_dir / "step1_execution.json").exists()
        engine.close()


# ── Tests: 报告 ───────────────────────────────────────────────

class TestEngineReport:
    """报告生成."""

    def test_save_report_json(self, mock_server: str, evidence_dir: Path, tmp_path: Path):
        engine = TestEngine(
            api_base_url=mock_server,
            evidence_dir=str(evidence_dir),
        )
        plan = ExecutionPlanner_plan_from_dict(MANUAL_PLAN)
        result = engine.run_plan(plan)

        report_path = tmp_path / "report.json"
        saved = engine.save_report(result, report_path)
        assert saved.exists()
        report = json.loads(saved.read_text("utf-8"))
        assert report["tc_id"] == MANUAL_PLAN["tc_id"]
        assert report["status"] == "pass"
        engine.close()

    def test_save_batch_report(self, mock_server: str, evidence_dir: Path, tmp_path: Path):
        engine = TestEngine(
            api_base_url=mock_server,
            evidence_dir=str(evidence_dir),
        )
        plan = ExecutionPlanner_plan_from_dict(MANUAL_PLAN)
        result = engine.run_plans([plan])

        report_path = tmp_path / "batch_report.json"
        saved = engine.save_report(result, report_path)
        assert saved.exists()
        report = json.loads(saved.read_text("utf-8"))
        assert report["summary"]["total"] == 1
        assert report["summary"]["pass"] == 1
        engine.close()


# ── Tests: 引擎生命周期 ───────────────────────────────────────

class TestEngineLifecycle:
    """引擎构建和关闭."""

    def test_engine_constructs_without_error(self, evidence_dir: Path):
        engine = TestEngine(
            api_base_url="http://127.0.0.1:1",
            evidence_dir=str(evidence_dir),
        )
        assert engine is not None
        engine.close()

    def test_engine_evidence_dir_created(self, tmp_path: Path):
        ev_dir = tmp_path / "new_evidence"
        engine = TestEngine(
            api_base_url="http://127.0.0.1:1",
            evidence_dir=str(ev_dir),
        )
        assert ev_dir.exists()
        engine.close()

    def test_engine_without_db_and_adb(self, evidence_dir: Path):
        engine = TestEngine(
            api_base_url="http://127.0.0.1:1",
            evidence_dir=str(evidence_dir),
        )
        assert engine._db_client is None
        engine.close()


# ── Helper ────────────────────────────────────────────────────

def ExecutionPlanner_plan_from_dict(plan_data: dict) -> ExecutionPlan:
    from execution.planner import ExecutionPlanner
    return ExecutionPlanner.plan_from_dict(plan_data)
