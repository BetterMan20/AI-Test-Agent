"""Smoke test — API + DB execution chain.

Verifies that API success ≠ business success: both API (code==0) and DB (reward_status==1)
must pass for a true PASS.

Flow:
  Step 1: API POST → verify code == 0       (interface success)
  Step 2: DB SELECT → verify reward_status == 1  (business success)
  Both PASS → true PASS
"""

from __future__ import annotations

import json
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from execution.context import ExecutionContext, EnvironmentConfig
from execution.planner import ExecutionPlanner
from execution.runner import ExecutionRunner
from evidence.collector import EvidenceCollector
from evidence.store import EvidenceStore
from tools.api.client import APIClient


# ── Mock HTTP server ──────────────────────────────────────────

class _MockAPIHandler(BaseHTTPRequestHandler):
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


# ── Mock DB client ────────────────────────────────────────────

class MockDBClient:
    """In-memory mock that mimics DBClient.query / DBClient.execute."""

    def __init__(self, rows: list[dict[str, Any]] | None = None):
        self._rows = rows if rows is not None else [
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


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture()
def mock_api_server():
    server = HTTPServer(("127.0.0.1", 0), _MockAPIHandler)
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


def _build_runner(
    api_base_url: str,
    db_client: MockDBClient | None,
    evidence_dir: Path,
) -> ExecutionRunner:
    store = EvidenceStore(base_dir=str(evidence_dir))
    collector = EvidenceCollector(store)
    api_client = APIClient(base_url=api_base_url)
    return ExecutionRunner(
        api_client=api_client,
        db_client=db_client,
        evidence_collector=collector,
    )


def _run_plan(runner: ExecutionRunner, plan_data: dict, base_url: str) -> Any:
    plan = ExecutionPlanner.plan_from_dict(plan_data)
    env = EnvironmentConfig(api_base_url=base_url)
    ctx = ExecutionContext(environment=env, tc_id=plan.tc_id)
    return runner.run_plan(plan, ctx)


# ── Plan definitions ─────────────────────────────────────────

PLAN_API_DB = {
    "tc_id": "TC-DBAPI-001",
    "title": "API+DB联合验证-发放奖品业务成功",
    "preconditions": ["用户U001持有SVIP体验卡", "体验卡当天过期"],
    "test_data": ["用户ID=U001", "体验卡=SVIP体验卡(7天)"],
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
                {"type": "json_path", "path": "$.data.reward_id", "expected": "RW-001"},
            ],
            "evidence_types": ["api_response"],
        },
        {
            "step_id": 2,
            "type": "db",
            "description": "SELECT reward_status FROM user_rewards WHERE user_id='U001'",
            "config": {
                "phase": "verify",
                "query": "SELECT reward_status, card_name, user_id FROM user_rewards WHERE user_id = %s",
                "params": ["U001"],
            },
            "assertions": [
                {"type": "json_path", "path": "$.0.reward_status", "expected": 1},
                {"type": "json_path", "path": "$.0.card_name", "expected": "SVIP体验卡"},
                {"type": "count", "expected": 1},
            ],
            "evidence_types": ["db_snapshot"],
        },
    ],
}


# ── Tests ─────────────────────────────────────────────────────


class TestAPIDBChain:
    """API + DB 联合验证链路。"""

    def test_both_pass_produces_true_pass(
        self, mock_api_server: str, evidence_dir: Path
    ) -> None:
        """API code==0 + DB reward_status==1 → true PASS."""
        db = MockDBClient(rows=[
            {"reward_status": 1, "card_name": "SVIP体验卡", "user_id": "U001"}
        ])
        runner = _build_runner(mock_api_server, db, evidence_dir)
        result = _run_plan(runner, PLAN_API_DB, mock_api_server)

        assert result.status == "pass"
        assert len(result.step_results) == 2
        assert result.step_results[0].status == "pass"   # API step
        assert result.step_results[1].status == "pass"   # DB step
        assert result.step_results[0].assertions_passed == 3
        assert result.step_results[1].assertions_passed == 3

    def test_api_pass_db_fail_produces_fail(
        self, mock_api_server: str, evidence_dir: Path
    ) -> None:
        """API code==0 但 DB reward_status==0 → FAIL（业务未真正成功）。"""
        db = MockDBClient(rows=[
            {"reward_status": 0, "card_name": "SVIP体验卡", "user_id": "U001"}
        ])
        runner = _build_runner(mock_api_server, db, evidence_dir)
        result = _run_plan(runner, PLAN_API_DB, mock_api_server)

        assert result.status == "fail"
        assert result.step_results[0].status == "pass"   # API still passes
        assert result.step_results[1].status == "fail"   # DB fails

    def test_api_pass_db_empty_produces_fail(
        self, mock_api_server: str, evidence_dir: Path
    ) -> None:
        """API 成功但 DB 查无数据 → FAIL。"""
        db = MockDBClient(rows=[])
        runner = _build_runner(mock_api_server, db, evidence_dir)
        result = _run_plan(runner, PLAN_API_DB, mock_api_server)

        assert result.status == "fail"
        assert result.step_results[0].status == "pass"
        assert result.step_results[1].status == "fail"

    def test_all_evidence_files_created(
        self, mock_api_server: str, evidence_dir: Path
    ) -> None:
        """验证 API(4 files) + DB(3 files) = 7 个证据文件全部生成。"""
        db = MockDBClient()
        runner = _build_runner(mock_api_server, db, evidence_dir)
        _run_plan(runner, PLAN_API_DB, mock_api_server)

        tc_dir = evidence_dir / PLAN_API_DB["tc_id"]
        api_files = [
            "step1_request.json",
            "step1_response.json",
            "step1_headers.json",
            "step1_execution.json",
        ]
        db_files = [
            "step2_db_query.json",
            "step2_db_snapshot.json",
            "step2_db_execution.json",
        ]
        for fname in api_files + db_files:
            assert (tc_dir / fname).exists(), f"Missing: {fname}"

    def test_db_query_evidence_content(
        self, mock_api_server: str, evidence_dir: Path
    ) -> None:
        db = MockDBClient()
        runner = _build_runner(mock_api_server, db, evidence_dir)
        _run_plan(runner, PLAN_API_DB, mock_api_server)

        query_ev = json.loads(
            (evidence_dir / PLAN_API_DB["tc_id"] / "step2_db_query.json").read_text("utf-8")
        )
        assert query_ev["phase"] == "verify"
        assert "user_id" in query_ev["query"]
        assert query_ev["params"] == ["U001"]

    def test_db_snapshot_evidence_content(
        self, mock_api_server: str, evidence_dir: Path
    ) -> None:
        db = MockDBClient()
        runner = _build_runner(mock_api_server, db, evidence_dir)
        _run_plan(runner, PLAN_API_DB, mock_api_server)

        snapshot = json.loads(
            (evidence_dir / PLAN_API_DB["tc_id"] / "step2_db_snapshot.json").read_text("utf-8")
        )
        assert isinstance(snapshot, list)
        assert len(snapshot) == 1
        assert snapshot[0]["reward_status"] == 1
        assert snapshot[0]["card_name"] == "SVIP体验卡"

    def test_db_execution_evidence_content(
        self, mock_api_server: str, evidence_dir: Path
    ) -> None:
        db = MockDBClient()
        runner = _build_runner(mock_api_server, db, evidence_dir)
        _run_plan(runner, PLAN_API_DB, mock_api_server)

        meta = json.loads(
            (evidence_dir / PLAN_API_DB["tc_id"] / "step2_db_execution.json").read_text("utf-8")
        )
        assert meta["tc_id"] == "TC-DBAPI-001"
        assert meta["step_id"] == 2
        assert meta["step_type"] == "db"
        assert meta["phase"] == "verify"
        assert meta["row_count"] == 1
        assert meta["status"] == "pass"
        assert meta["assertions_passed"] == 3
