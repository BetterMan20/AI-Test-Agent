"""TestEngine — 统一测试执行引擎.

两个入口汇聚到一个引擎:

  入口 A: Test Case (dict)  → plan_from_test_case()  → ExecutionPlan
  入口 B: Whistle Capture   → plan_from_capture()    → ExecutionPlan
                                                    ↓
                                              ExecutionRunner
                                                    ↓
                                           API / DB / ADB
                                                    ↓
                                         Assertion + Evidence
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from execution.context import ExecutionContext, EnvironmentConfig
from execution.planner import ExecutionPlan, ExecutionPlanner
from execution.result import ExecutionResult, TestCaseResult
from execution.runner import ExecutionRunner
from evidence.collector import EvidenceCollector
from evidence.store import EvidenceStore


class TestEngine:
    """统一测试执行引擎.

    用法:
        engine = TestEngine(api_base_url="https://api-chat-test.youyisia.com")

        # 入口 A: 从 Test Case 执行
        result = engine.run_test_case(tc_dict)

        # 入口 B: 从 Whistle 抓包执行
        result = engine.run_capture(captured_api)

        # 批量执行
        result = engine.run_captures_from_dir("D:/higo-api", keywords=["gift"])
    """

    def __init__(
        self,
        api_base_url: str = "",
        api_headers: dict[str, str] | None = None,
        api_timeout: int = 30,
        db_host: str = "",
        db_port: int = 3306,
        db_user: str = "",
        db_password: str = "",
        db_name: str = "",
        adb_device_serial: str = "",
        evidence_dir: str = "output/evidence",
        capability: Any | None = None,
        validate_plans: bool = True,
    ):
        self._env = EnvironmentConfig(
            api_base_url=api_base_url,
            api_headers=api_headers or {},
            api_timeout=api_timeout,
            db_host=db_host,
            db_port=db_port,
            db_user=db_user,
            db_password=db_password,
            db_name=db_name,
            adb_device_serial=adb_device_serial,
            evidence_dir=evidence_dir,
        )
        self._evidence_dir = Path(evidence_dir)
        self._evidence_dir.mkdir(parents=True, exist_ok=True)

        self._capability = capability
        self._validate_plans = validate_plans

        if validate_plans:
            from verification.plan_validator import PlanValidator
            self._validator = PlanValidator(capability=capability)
        else:
            self._validator = None

        self._store = EvidenceStore(base_dir=str(self._evidence_dir))
        self._collector = EvidenceCollector(self._store)

        self._api_client = self._build_api_client()
        self._db_client = self._build_db_client()
        self._adb_client = self._build_adb_client()

        self._runner = ExecutionRunner(
            api_client=self._api_client,
            db_client=self._db_client,
            adb_client=self._adb_client,
            evidence_collector=self._collector,
        )

    # ── 入口 A: Test Case ──────────────────────────────────

    def run_test_case(self, test_case: dict[str, Any]) -> TestCaseResult:
        """入口 A: 从文档级 TC 执行 (LLM 驱动转换 + Plan 验证)."""
        plan = ExecutionPlanner.plan_from_test_case(test_case, capability=self._capability)

        if self._validator is not None:
            vr = self._validator.validate(plan, test_case=test_case)
            if not vr.valid:
                return TestCaseResult(
                    tc_id=plan.tc_id,
                    title=plan.title,
                    status="error",
                    step_results=[],
                    evidence_refs=[],
                    duration_ms=0,
                    error="Plan validation failed: " + vr.to_dict().__str__(),
                )

        return self._execute_plan(plan)

    def run_test_case_file(self, tc_file: str | Path) -> TestCaseResult:
        """从 JSON 文件加载 TC 并执行."""
        data = json.loads(Path(tc_file).read_text(encoding="utf-8"))
        if isinstance(data, list):
            data = data[0]
        return self.run_test_case(data)

    def run_test_cases(self, test_cases: list[dict[str, Any]]) -> ExecutionResult:
        """批量执行多个 TC."""
        plans = [
            ExecutionPlanner.plan_from_test_case(tc, capability=self._capability)
            for tc in test_cases
        ]
        return self._execute_plans(plans)

    # ── 入口 B: Whistle Capture ───────────────────────────

    def run_capture(self, captured_api) -> TestCaseResult:
        """入口 B: 从 Whistle 抓包记录执行 (直接回放)."""
        plan = ExecutionPlanner.plan_from_capture(captured_api)

        if not self._env.api_base_url and hasattr(captured_api, "base_url"):
            self._env.api_base_url = captured_api.base_url
            self._api_client = self._build_api_client()
            self._runner = ExecutionRunner(
                api_client=self._api_client,
                db_client=self._db_client,
                adb_client=self._adb_client,
                evidence_collector=self._collector,
            )

        return self._execute_plan(plan)

    def run_captures_from_dir(
        self,
        capture_dir: str | Path,
        keywords: list[str] | None = None,
        max_count: int | None = None,
    ) -> ExecutionResult:
        """从目录批量解析抓包并执行."""
        from tools.whistle_parser import WhistleParser

        grouped = WhistleParser.find_endpoints(capture_dir, keywords=keywords)

        plans: list[ExecutionPlan] = []
        base_url = ""

        for endpoint, entries in grouped.items():
            cap = entries[0]
            if not base_url:
                base_url = cap.base_url
            plan = ExecutionPlanner.plan_from_capture(cap)
            plans.append(plan)

            if max_count and len(plans) >= max_count:
                break

        if base_url and not self._env.api_base_url:
            self._env.api_base_url = base_url
            self._api_client = self._build_api_client()
            self._runner = ExecutionRunner(
                api_client=self._api_client,
                db_client=self._db_client,
                adb_client=self._adb_client,
                evidence_collector=self._collector,
            )

        return self._execute_plans(plans)

    def run_capture_file(
        self,
        file_path: str | Path,
        keywords: list[str] | None = None,
    ) -> ExecutionResult:
        """从单个 Whistle 抓包文件执行所有 API."""
        from tools.whistle_parser import WhistleParser

        all_entries = WhistleParser.parse_file(file_path)

        entries = []
        for e in all_entries:
            if e.endpoint in WhistleParser._skip_endpoints():
                continue
            if keywords:
                ep_lower = e.endpoint.lower()
                if not any(kw.lower() in ep_lower for kw in keywords):
                    continue
            entries.append(e)

        plans = [ExecutionPlanner.plan_from_capture(e) for e in entries]

        if entries and not self._env.api_base_url:
            self._env.api_base_url = entries[0].base_url
            self._api_client = self._build_api_client()
            self._runner = ExecutionRunner(
                api_client=self._api_client,
                db_client=self._db_client,
                adb_client=self._adb_client,
                evidence_collector=self._collector,
            )

        return self._execute_plans(plans)

    # ── 入口 C: 手动构造 Plan ──────────────────────────────

    def run_plan(self, plan: ExecutionPlan) -> TestCaseResult:
        """入口 C: 直接传入 ExecutionPlan."""
        return self._execute_plan(plan)

    def run_plans(self, plans: list[ExecutionPlan]) -> ExecutionResult:
        """批量执行多个 ExecutionPlan."""
        return self._execute_plans(plans)

    # ── 核心执行 ──────────────────────────────────────────

    def _execute_plan(self, plan: ExecutionPlan) -> TestCaseResult:
        ctx = ExecutionContext(environment=self._env, tc_id=plan.tc_id)
        return self._runner.run_plan(plan, ctx)

    def _execute_plans(self, plans: list[ExecutionPlan]) -> ExecutionResult:
        import time

        results: list[TestCaseResult] = []
        total_start = time.time()
        for plan in plans:
            results.append(self._execute_plan(plan))
        return ExecutionResult(
            results=results,
            duration_ms=int((time.time() - total_start) * 1000),
        )

    # ── 报告 ──────────────────────────────────────────────

    def save_report(self, result: ExecutionResult | TestCaseResult, path: str | Path) -> Path:
        """保存 JSON 报告."""
        report_path = Path(path)
        report_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(result, TestCaseResult):
            data = result.to_dict()
        else:
            data = result.to_dict()

        report_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return report_path

    # ── 工具构建 ──────────────────────────────────────────

    def _build_api_client(self):
        if not self._env.api_base_url:
            return None
        from tools.api.client import APIClient

        return APIClient(
            base_url=self._env.api_base_url,
            default_headers=self._env.api_headers or None,
            timeout=self._env.api_timeout,
        )

    def _build_db_client(self):
        if not self._env.db_host:
            return None
        from tools.db.client import DBClient

        return DBClient(
            host=self._env.db_host,
            port=self._env.db_port,
            user=self._env.db_user,
            password=self._env.db_password,
            database=self._env.db_name,
        )

    def _build_adb_client(self):
        if not self._env.adb_device_serial and not self._adb_available():
            return None
        from tools.android.client import ADBClient

        return ADBClient(
            device_serial=self._env.adb_device_serial or None,
            timeout=30,
        )

    @staticmethod
    def _adb_available() -> bool:
        import shutil

        return shutil.which("adb") is not None

    def close(self) -> None:
        if self._api_client:
            self._api_client.close()
        if self._db_client:
            self._db_client.close()
