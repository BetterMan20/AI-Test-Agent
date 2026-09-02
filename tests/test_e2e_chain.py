"""Smoke test — full E2E chain: API + DB + Android (ADB).

Verifies the complete flow:
  Step 1: API POST /api/grant-reward      → code == 0        (接口成功)
  Step 2: DB SELECT reward_status          → reward_status == 1  (业务成功)
  Step 3: ADB am start (打开App)           → output contains "Starting"
  Step 4: ADB input tap (点击领取)          → screenshot + logcat (UI证据)

All steps PASS → true E2E PASS.
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


# ── Mock ADB client ────────────────────────────────────────────

class MockADBClient:
    """Simulates adb shell/screenshot/logcat without a real device."""

    _MOCK_SHELL = {
        "am start": (
            "Starting: Intent { cmp=com.higo.app/.MainActivity }\n"
            "WARNING: not logged in\n"
        ),
        "input tap": "",
        "dumpsys window": "mCurrentFocus=Window{com.higo.app/com.higo.app.RewardActivity}",
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


def _build_runner(api_base_url: str, db_client: MockDBClient, evidence_dir: Path) -> ExecutionRunner:
    store = EvidenceStore(base_dir=str(evidence_dir))
    collector = EvidenceCollector(store)
    api_client = APIClient(base_url=api_base_url)
    adb_client = MockADBClient()
    return ExecutionRunner(
        api_client=api_client,
        db_client=db_client,
        adb_client=adb_client,
        evidence_collector=collector,
    )


def _run_plan(runner: ExecutionRunner, plan_data: dict, base_url: str) -> Any:
    plan = ExecutionPlanner.plan_from_dict(plan_data)
    env = EnvironmentConfig(api_base_url=base_url)
    ctx = ExecutionContext(environment=env, tc_id=plan.tc_id)
    return runner.run_plan(plan, ctx)


# ── Plan: full E2E (API → DB → ADB → Screenshot) ─────────────

PLAN_E2E = {
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
            "config": {
                "command": "am start -n com.higo.app/.MainActivity",
            },
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
            "config": {
                "command": "input tap 540 960",
            },
            "assertions": [],
            "evidence_types": ["screenshot", "logcat"],
        },
    ],
}


# ── Tests ─────────────────────────────────────────────────────


class TestE2EChain:
    """API + DB + Android 完整 E2E 验证链路。"""

    def test_full_e2e_pass(self, mock_api_server: str, evidence_dir: Path) -> None:
        """4 个步骤全部 PASS → E2E PASS。"""
        db = MockDBClient()
        runner = _build_runner(mock_api_server, db, evidence_dir)
        result = _run_plan(runner, PLAN_E2E, mock_api_server)

        assert result.status == "pass"
        assert len(result.step_results) == 4
        for i, sr in enumerate(result.step_results):
            assert sr.status == "pass", f"Step {i+1} failed: {sr.status}"

    def test_api_pass_db_pass_adb_fail(
        self, mock_api_server: str, evidence_dir: Path
    ) -> None:
        """API + DB 通过，但 ADB 打开 App 输出不含预期文本 → FAIL。"""
        bad_adb = MockADBClient()
        bad_adb._MOCK_SHELL = {"am start": "Error: activity not found"}
        db = MockDBClient()
        store = EvidenceStore(base_dir=str(evidence_dir))
        collector = EvidenceCollector(store)
        runner = ExecutionRunner(
            api_client=APIClient(base_url=mock_api_server),
            db_client=db,
            adb_client=bad_adb,
            evidence_collector=collector,
        )
        result = _run_plan(runner, PLAN_E2E, mock_api_server)

        assert result.status == "fail"
        assert result.step_results[0].status == "pass"   # API
        assert result.step_results[1].status == "pass"   # DB
        assert result.step_results[2].status == "fail"   # ADB am start
        assert result.step_results[2].assertions_failed == 2

    def test_all_evidence_files_created(
        self, mock_api_server: str, evidence_dir: Path
    ) -> None:
        """验证全部证据文件生成：API(4) + DB(3) + ADB(3+3) + screenshot(2) + logcat(1) = 13+。"""
        db = MockDBClient()
        runner = _build_runner(mock_api_server, db, evidence_dir)
        _run_plan(runner, PLAN_E2E, mock_api_server)

        tc_dir = evidence_dir / PLAN_E2E["tc_id"]
        expected = [
            # API step1
            "step1_request.json",
            "step1_response.json",
            "step1_headers.json",
            "step1_execution.json",
            # DB step2
            "step2_db_query.json",
            "step2_db_snapshot.json",
            "step2_db_execution.json",
            # ADB step3 (command/output/execution + screenshot)
            "step3_adb_command.json",
            "step3_adb_output.json",
            "step3_adb_execution.json",
            "step3_screenshot.png",
            # ADB step4 (command/output/execution + screenshot + logcat)
            "step4_adb_command.json",
            "step4_adb_output.json",
            "step4_adb_execution.json",
            "step4_screenshot.png",
            "step4_logcat.txt",
        ]
        for fname in expected:
            assert (tc_dir / fname).exists(), f"Missing: {fname}"

    def test_adb_command_evidence(
        self, mock_api_server: str, evidence_dir: Path
    ) -> None:
        db = MockDBClient()
        runner = _build_runner(mock_api_server, db, evidence_dir)
        _run_plan(runner, PLAN_E2E, mock_api_server)

        cmd = json.loads(
            (evidence_dir / PLAN_E2E["tc_id"] / "step3_adb_command.json").read_text("utf-8")
        )
        assert "am start" in cmd["command"]
        assert "com.higo.app" in cmd["command"]

    def test_adb_output_evidence(
        self, mock_api_server: str, evidence_dir: Path
    ) -> None:
        db = MockDBClient()
        runner = _build_runner(mock_api_server, db, evidence_dir)
        _run_plan(runner, PLAN_E2E, mock_api_server)

        out = json.loads(
            (evidence_dir / PLAN_E2E["tc_id"] / "step3_adb_output.json").read_text("utf-8")
        )
        assert "Starting" in out["output"]
        assert "com.higo.app" in out["output"]

    def test_adb_execution_evidence(
        self, mock_api_server: str, evidence_dir: Path
    ) -> None:
        db = MockDBClient()
        runner = _build_runner(mock_api_server, db, evidence_dir)
        _run_plan(runner, PLAN_E2E, mock_api_server)

        meta = json.loads(
            (evidence_dir / PLAN_E2E["tc_id"] / "step3_adb_execution.json").read_text("utf-8")
        )
        assert meta["tc_id"] == "TC-E2E-001"
        assert meta["step_id"] == 3
        assert meta["step_type"] == "adb"
        assert meta["status"] == "pass"
        assert meta["assertions_passed"] == 2

    def test_screenshot_evidence_is_png(
        self, mock_api_server: str, evidence_dir: Path
    ) -> None:
        db = MockDBClient()
        runner = _build_runner(mock_api_server, db, evidence_dir)
        _run_plan(runner, PLAN_E2E, mock_api_server)

        screenshot = evidence_dir / PLAN_E2E["tc_id"] / "step3_screenshot.png"
        assert screenshot.exists()
        assert screenshot.read_bytes()[:4] == b"\x89PNG"

    def test_logcat_evidence_content(
        self, mock_api_server: str, evidence_dir: Path
    ) -> None:
        db = MockDBClient()
        runner = _build_runner(mock_api_server, db, evidence_dir)
        _run_plan(runner, PLAN_E2E, mock_api_server)

        logcat_path = evidence_dir / PLAN_E2E["tc_id"] / "step4_logcat.txt"
        content = logcat_path.read_text("utf-8")
        assert "ActivityManager" in content
        assert "RewardService" in content
        assert "reward_status=1" in content

    def test_evidence_ref_count(
        self, mock_api_server: str, evidence_dir: Path
    ) -> None:
        """验证 TestCaseResult.evidence_refs 包含所有证据路径。"""
        db = MockDBClient()
        runner = _build_runner(mock_api_server, db, evidence_dir)
        result = _run_plan(runner, PLAN_E2E, mock_api_server)

        # step1: 4 API files
        # step2: 3 DB files
        # step3: 3 ADB files + 1 screenshot
        # step4: 3 ADB files + 1 screenshot + 1 logcat
        assert len(result.evidence_refs) == 16
