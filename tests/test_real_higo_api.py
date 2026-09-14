"""测试——Whistle解析器 + 基于捕获的计划生成。

测试Whistle解析器能否正确解析Higo API捕获文件，以及plan_from_capture()能否生成有效的执行计划。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from execution.planner import ExecutionPlan, ExecutionPlanner
from tools.whistle_parser import (
    CapturedAPI,
    WhistleParser,
)


HIGO_API_DIR = Path(r"D:\higo-api")

_HAS_HIGO_DATA = HIGO_API_DIR.exists() and any(HIGO_API_DIR.glob("*.txt"))

skip_no_data = pytest.mark.skipif(
    not _HAS_HIGO_DATA,
    reason="No .txt capture files in D:/higo-api",
)


@pytest.fixture()
def first_capture_file():
    """找到第一个非心跳的抓包文件。"""
    if not HIGO_API_DIR.exists():
        pytest.skip(f"Higo API directory not found: {HIGO_API_DIR}")
    for tf in sorted(HIGO_API_DIR.glob("*.txt")):
        entries = WhistleParser.parse_file(tf)
        for e in entries:
            if e.endpoint not in WhistleParser.__dict__.get("SKIP_ENDPOINTS", set()):
                return e
    pytest.skip("No non-heartbeat captures found")


@pytest.fixture()
def wealth_capture():
    """找到 trade_wealth_detail 抓包记录。"""
    if not HIGO_API_DIR.exists():
        pytest.skip(f"Higo API directory not found: {HIGO_API_DIR}")
    grouped = WhistleParser.find_endpoints(HIGO_API_DIR)
    if "/live/account/trade_wealth_detail" not in grouped:
        pytest.skip("trade_wealth_detail capture not found")
    return grouped["/live/account/trade_wealth_detail"][0]


@pytest.fixture()
def checkin_capture():
    """找到 check_in_detail 抓包记录。"""
    if not HIGO_API_DIR.exists():
        pytest.skip(f"Higo API directory not found: {HIGO_API_DIR}")
    grouped = WhistleParser.find_endpoints(HIGO_API_DIR)
    if "/live/facetime/check_in_detail" not in grouped:
        pytest.skip("check_in_detail capture not found")
    return grouped["/live/facetime/check_in_detail"][0]


class TestWhistleParser:
    """Whistle 抓包解析器测试。"""

    def test_parse_single_file(self):
        """解析单个文件返回 CapturedAPI 列表。"""
        if not _HAS_HIGO_DATA:
            pytest.skip("No .txt capture files in D:/higo-api")
        first_file = sorted(HIGO_API_DIR.glob("*.txt"))[0]
        entries = WhistleParser.parse_file(first_file)
        assert isinstance(entries, list)
        assert len(entries) > 0
        assert all(isinstance(e, CapturedAPI) for e in entries)

    def test_entry_has_url(self, first_capture_file):
        """每条记录有 URL。"""
        assert first_capture_file.url.startswith("https://")

    def test_entry_has_method(self, first_capture_file):
        """每条记录有 HTTP method。"""
        assert first_capture_file.method in ("GET", "POST", "PUT", "PATCH", "DELETE")

    def test_entry_has_status_code(self, first_capture_file):
        """每条记录有状态码。"""
        assert first_capture_file.status_code > 0

    def test_entry_has_headers(self, first_capture_file):
        """每条记录有请求头。"""
        assert "host" in first_capture_file.req_headers

    def test_entry_has_body(self, first_capture_file):
        """每条记录有请求 body。"""
        assert first_capture_file.req_body is not None

    def test_base_url_extraction(self, wealth_capture):
        """base_url 正确提取。"""
        assert wealth_capture.base_url == "https://api-chat-test.youyisia.com"

    def test_endpoint_extraction(self, wealth_capture):
        """endpoint 正确提取。"""
        assert wealth_capture.endpoint == "/live/account/trade_wealth_detail"

    def test_path_with_query(self, wealth_capture):
        """path_with_query 包含 sign 参数。"""
        assert "sign=" in wealth_capture.path_with_query

    def test_response_body_parsed(self, wealth_capture):
        """响应 body 被解析为 dict。"""
        assert isinstance(wealth_capture.res_body, dict)

    def test_find_endpoints_groups(self):
        """find_endpoints 按 endpoint 分组。"""
        if not _HAS_HIGO_DATA:
            pytest.skip("No .txt capture files in D:/higo-api")
        grouped = WhistleParser.find_endpoints(HIGO_API_DIR)
        assert len(grouped) > 0
        for endpoint, entries in grouped.items():
            assert all(e.endpoint == endpoint for e in entries)

    def test_find_with_keywords(self):
        """关键词过滤。"""
        if not _HAS_HIGO_DATA:
            pytest.skip("No .txt capture files in D:/higo-api")
        grouped = WhistleParser.find_endpoints(
            HIGO_API_DIR, keywords=["gift", "wealth", "sign_in"]
        )
        assert len(grouped) > 0
        assert all(
            "gift" in ep or "wealth" in ep or "sign_in" in ep
            for ep in grouped
        )


class TestPlanFromCapture:
    """plan_from_capture() 测试。"""

    def test_returns_execution_plan(self, wealth_capture):
        """plan_from_capture 返回 ExecutionPlan。"""
        plan = ExecutionPlanner.plan_from_capture(wealth_capture)
        assert isinstance(plan, ExecutionPlan)

    def test_tc_id_generated(self, wealth_capture):
        """生成的 TC ID 以 TC-CAP- 开头。"""
        plan = ExecutionPlanner.plan_from_capture(wealth_capture)
        assert plan.tc_id.startswith("TC-CAP-")

    def test_title_contains_endpoint(self, wealth_capture):
        """Title 包含 endpoint。"""
        plan = ExecutionPlanner.plan_from_capture(wealth_capture)
        assert "trade_wealth_detail" in plan.title

    def test_step_type_is_api(self, wealth_capture):
        """步骤类型为 api。"""
        plan = ExecutionPlanner.plan_from_capture(wealth_capture)
        assert len(plan.steps) == 1
        assert plan.steps[0].step_type == "api"

    def test_config_has_method(self, wealth_capture):
        """config 包含 method。"""
        plan = ExecutionPlanner.plan_from_capture(wealth_capture)
        assert plan.steps[0].action["method"] == wealth_capture.method

    def test_config_has_path(self, wealth_capture):
        """config 包含 path（带 sign）。"""
        plan = ExecutionPlanner.plan_from_capture(wealth_capture)
        assert "sign=" in plan.steps[0].action["path"]

    def test_config_has_headers(self, wealth_capture):
        """config 包含 headers。"""
        plan = ExecutionPlanner.plan_from_capture(wealth_capture)
        assert "host" in plan.steps[0].action["headers"]

    def test_config_has_body(self, wealth_capture):
        """config 包含 body 且是 dict。"""
        plan = ExecutionPlanner.plan_from_capture(wealth_capture)
        assert isinstance(plan.steps[0].action["body"], dict)

    def test_assertions_contain_status_code(self, wealth_capture):
        """断言包含 status_code。"""
        plan = ExecutionPlanner.plan_from_capture(wealth_capture)
        assertions = plan.steps[0].assertions
        assert any(a["type"] == "status_code" for a in assertions)

    def test_assertions_contain_ret_check(self, wealth_capture):
        """如果响应有 ret 字段，断言包含 json_path $.ret。"""
        plan = ExecutionPlanner.plan_from_capture(wealth_capture)
        assertions = plan.steps[0].assertions
        ret_assertions = [a for a in assertions if a.get("path") == "$.ret"]
        assert len(ret_assertions) > 0

    def test_evidence_types(self, wealth_capture):
        """evidence_types 包含 api_response。"""
        plan = ExecutionPlanner.plan_from_capture(wealth_capture)
        assert "api_response" in plan.steps[0].evidence_types
