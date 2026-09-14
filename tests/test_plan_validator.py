"""Test — Plan Validator 幻觉检测测试.

验证 6 项规则:
  1. API endpoint 来自 Capability
  2. HTTP method 匹配
  3. config 完整
  4. assertion 来自 TC
  5. 未知 step type
  6. 步骤数量异常
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from execution.planner import ExecutionPlan, ExecutionStep
from verification.plan_validator import PlanValidator, ValidationResult


# ── Fixtures ──────────────────────────────────────────────────

def make_plan(steps: list[dict[str, Any]]) -> ExecutionPlan:
    """从 dict 列表构建 ExecutionPlan。"""
    plan_steps: list[ExecutionStep] = []
    for s in steps:
        plan_steps.append(ExecutionStep(
            step_id=s.get("step_id", 1),
            step_type=s.get("type", "api"),
            description=s.get("description", ""),
            action=s.get("config", {}),
            assertions=s.get("assertions", []),
            evidence_types=s.get("evidence_types", []),
        ))
    return ExecutionPlan(
        tc_id="TC-TEST-001",
        title="测试",
        steps=plan_steps,
    )


def make_capability(endpoints: dict[str, str]) -> MagicMock:
    """创建 mock capability，endpoints = {path: method}。"""
    cap = MagicMock()
    cap._endpoints = {}

    from knowledge.capability import APIEndpoint
    ep_list = []
    for path, method in endpoints.items():
        ep = APIEndpoint(endpoint=path, method=method)
        ep_list.append(ep)
        cap._endpoints[path] = ep

    cap.all.return_value = ep_list
    cap.get.side_effect = lambda p: cap._endpoints.get(p)
    cap.__len__ = lambda self: len(ep_list)
    return cap


CAPABILITY = make_capability({
    "/live/gift/send_gift": "POST",
    "/live/account/trade_wealth_detail": "POST",
    "/live/game/play_sign_in_status": "POST",
    "/live/facetime/check_in_detail": "POST",
    "/live/facetime/check_in": "POST",
})

TC_SIGNIN = {
    "id": "TC-HIGO-SIGNIN-001",
    "title": "用户每日签到领取奖励-基本流程",
    "steps": [
        {"step": 1, "action": "调用签到状态接口，查询用户今日是否可签到"},
        {"step": 2, "action": "调用签到详情接口，查看签到奖励信息"},
        {"step": 3, "action": "调用用户财富详情接口，记录签到前余额"},
        {"step": 4, "action": "调用签到接口，执行签到领取奖励"},
        {"step": 5, "action": "再次调用用户财富详情接口，验证余额增加"},
    ],
    "expected_results": [
        "签到状态接口返回 signed_today=false，表示今日尚未签到",
        "签到详情接口返回奖励信息，包含签到天数和奖励内容",
        "签到前用户财富值记录成功",
        "签到接口返回 ret=1，签到成功",
        "签到后用户财富值增加，增加量等于签到奖励数量",
    ],
}


# ── 规则 1: 未知 step type ────────────────────────────────────

class TestUnknownStepType:
    def test_valid_types_pass(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {"method": "POST", "path": "/live/gift/send_gift"}},
            {"step_id": 2, "type": "manual"},
        ])
        v = PlanValidator(capability=CAPABILITY)
        result = v.validate(plan)
        type_issues = [i for i in result.issues if i.rule == "unknown_step_type"]
        assert len(type_issues) == 0

    def test_unknown_type_caught(self):
        plan = make_plan([
            {"step_id": 1, "type": "graphql", "config": {}},
        ])
        v = PlanValidator()
        result = v.validate(plan)
        type_issues = [i for i in result.issues if i.rule == "unknown_step_type"]
        assert len(type_issues) == 1
        assert type_issues[0].severity == "error"
        assert "graphql" in type_issues[0].message


# ── 规则 2: config 完整性 ─────────────────────────────────────

class TestConfigCompleteness:
    def test_valid_api_config_passes(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {
                "method": "POST", "path": "/live/gift/send_gift",
                "headers": {"Content-Type": "application/json"},
                "body": {"goods_id": 519},
            }},
        ])
        v = PlanValidator(capability=CAPABILITY)
        result = v.validate(plan)
        config_issues = [i for i in result.issues if i.rule == "config_incomplete"]
        assert len(config_issues) == 0

    def test_missing_method_caught(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {"path": "/live/gift/send_gift"}},
        ])
        v = PlanValidator()
        result = v.validate(plan)
        config_issues = [i for i in result.issues if i.rule == "config_incomplete"]
        assert any("method" in i.message for i in config_issues)
        assert all(i.severity == "error" for i in config_issues if "method" in i.message)

    def test_missing_path_caught(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {"method": "POST"}},
        ])
        v = PlanValidator()
        result = v.validate(plan)
        config_issues = [i for i in result.issues if i.rule == "config_incomplete"]
        assert any("path" in i.message for i in config_issues)

    def test_invalid_method_caught(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {"method": "CONNECT", "path": "/x"}},
        ])
        v = PlanValidator()
        result = v.validate(plan)
        method_issues = [i for i in result.issues if i.rule == "invalid_method"]
        assert len(method_issues) == 1
        assert "CONNECT" in method_issues[0].message

    def test_path_not_starting_with_slash(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {"method": "POST", "path": "live/gift"}},
        ])
        v = PlanValidator()
        result = v.validate(plan)
        path_issues = [i for i in result.issues if i.rule == "invalid_path"]
        assert len(path_issues) == 1

    def test_db_missing_query(self):
        plan = make_plan([
            {"step_id": 1, "type": "db", "config": {}},
        ])
        v = PlanValidator()
        result = v.validate(plan)
        config_issues = [i for i in result.issues if i.rule == "config_incomplete"]
        assert any("query" in i.message for i in config_issues)

    def test_adb_missing_command(self):
        plan = make_plan([
            {"step_id": 1, "type": "adb", "config": {}},
        ])
        v = PlanValidator()
        result = v.validate(plan)
        config_issues = [i for i in result.issues if i.rule == "config_incomplete"]
        assert any("command" in i.message for i in config_issues)


# ── 规则 3: API endpoint 来自 Capability ──────────────────────

class TestEndpointInCapability:
    def test_known_endpoint_passes(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {
                "method": "POST", "path": "/live/gift/send_gift",
            }},
        ])
        v = PlanValidator(capability=CAPABILITY)
        result = v.validate(plan)
        ep_issues = [i for i in result.issues if i.rule == "unknown_endpoint"]
        assert len(ep_issues) == 0

    def test_unknown_endpoint_caught(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {
                "method": "POST", "path": "/live/nonexistent/hallucinated_api",
            }},
        ])
        v = PlanValidator(capability=CAPABILITY)
        result = v.validate(plan)
        ep_issues = [i for i in result.issues if i.rule == "unknown_endpoint"]
        assert len(ep_issues) == 1
        assert "/live/nonexistent/hallucinated_api" in ep_issues[0].message
        assert ep_issues[0].severity == "error"

    def test_endpoint_with_query_params_stripped(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {
                "method": "POST", "path": "/live/gift/send_gift?sign=abc123",
            }},
        ])
        v = PlanValidator(capability=CAPABILITY)
        result = v.validate(plan)
        ep_issues = [i for i in result.issues if i.rule == "unknown_endpoint"]
        assert len(ep_issues) == 0

    def test_no_capability_skips_check(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {
                "method": "POST", "path": "/totally/unknown",
            }},
        ])
        v = PlanValidator(capability=None)
        result = v.validate(plan)
        ep_issues = [i for i in result.issues if i.rule == "unknown_endpoint"]
        assert len(ep_issues) == 0


# ── 规则 4: HTTP method 匹配 ──────────────────────────────────

class TestMethodMatch:
    def test_matching_method_passes(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {
                "method": "POST", "path": "/live/gift/send_gift",
            }},
        ])
        v = PlanValidator(capability=CAPABILITY)
        result = v.validate(plan)
        method_issues = [i for i in result.issues if i.rule == "method_mismatch"]
        assert len(method_issues) == 0

    def test_wrong_method_caught(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {
                "method": "GET", "path": "/live/gift/send_gift",
            }},
        ])
        v = PlanValidator(capability=CAPABILITY)
        result = v.validate(plan)
        method_issues = [i for i in result.issues if i.rule == "method_mismatch"]
        assert len(method_issues) == 1
        assert "GET" in method_issues[0].detail["plan_method"]
        assert "POST" in method_issues[0].detail["capability_method"]

    def test_case_insensitive_match(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {
                "method": "post", "path": "/live/gift/send_gift",
            }},
        ])
        v = PlanValidator(capability=CAPABILITY)
        result = v.validate(plan)
        method_issues = [i for i in result.issues if i.rule == "method_mismatch"]
        assert len(method_issues) == 0


# ── 规则 5: assertion 来源 ────────────────────────────────────

class TestAssertionSources:
    def test_assertion_from_expected_results(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {"method": "POST", "path": "/x"},
             "assertions": [
                 {"type": "json_path", "path": "$.ret", "expected": 1},
             ]},
        ])
        v = PlanValidator()
        result = v.validate(plan, test_case=TC_SIGNIN)
        assert_issues = [i for i in result.issues if i.rule == "assertion_not_from_tc"]
        # "ret" is in expected_results ("签到接口返回 ret=1")
        assert len(assert_issues) == 0

    def test_hallucinated_assertion_caught(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {"method": "POST", "path": "/x"},
             "assertions": [
                 {"type": "json_path", "path": "$.data.hallucinated_field_xyz", "expected": "magic"},
             ]},
        ])
        v = PlanValidator()
        result = v.validate(plan, test_case=TC_SIGNIN)
        assert_issues = [i for i in result.issues if i.rule == "assertion_not_from_tc"]
        assert len(assert_issues) == 1
        assert "hallucinated_field_xyz" in assert_issues[0].message
        assert assert_issues[0].severity == "warning"

    def test_text_contains_from_expected(self):
        plan = make_plan([
            {"step_id": 1, "type": "adb", "config": {"command": "am start"},
             "assertions": [
                 {"type": "text_contains", "expected": "签到"},
             ]},
        ])
        v = PlanValidator()
        result = v.validate(plan, test_case=TC_SIGNIN)
        assert_issues = [i for i in result.issues if i.rule == "assertion_not_from_tc"]
        assert len(assert_issues) == 0

    def test_text_contains_not_in_expected(self):
        plan = make_plan([
            {"step_id": 1, "type": "adb", "config": {"command": "am start"},
             "assertions": [
                 {"type": "text_contains", "expected": "脑补的文本内容"},
             ]},
        ])
        v = PlanValidator()
        result = v.validate(plan, test_case=TC_SIGNIN)
        assert_issues = [i for i in result.issues if i.rule == "assertion_not_from_tc"]
        assert len(assert_issues) == 1

    def test_status_code_not_checked(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {"method": "POST", "path": "/x"},
             "assertions": [
                 {"type": "status_code", "expected": 200},
             ]},
        ])
        v = PlanValidator()
        result = v.validate(plan, test_case=TC_SIGNIN)
        assert_issues = [i for i in result.issues if i.rule == "assertion_not_from_tc"]
        assert len(assert_issues) == 0


# ── 规则 6: 步骤数量 ──────────────────────────────────────────

class TestStepCount:
    def test_exact_match_passes(self):
        plan = make_plan([
            {"step_id": i, "type": "manual", "config": {"instruction": "step"}}
            for i in range(1, 6)
        ])
        v = PlanValidator()
        result = v.validate(plan, test_case=TC_SIGNIN)
        count_issues = [i for i in result.issues if i.rule == "excess_steps"]
        assert len(count_issues) == 0

    def test_one_extra_step_passes(self):
        plan = make_plan([
            {"step_id": i, "type": "manual", "config": {"instruction": "step"}}
            for i in range(1, 7)
        ])
        v = PlanValidator(max_extra_steps=2)
        result = v.validate(plan, test_case=TC_SIGNIN)
        count_issues = [i for i in result.issues if i.rule == "excess_steps"]
        assert len(count_issues) == 0

    def test_too_many_steps_caught(self):
        plan = make_plan([
            {"step_id": i, "type": "manual", "config": {"instruction": "step"}}
            for i in range(1, 10)
        ])
        v = PlanValidator(max_extra_steps=2)
        result = v.validate(plan, test_case=TC_SIGNIN)
        count_issues = [i for i in result.issues if i.rule == "excess_steps"]
        assert len(count_issues) == 1
        assert count_issues[0].severity == "error"

    def test_no_tc_skips_count_check(self):
        plan = make_plan([
            {"step_id": i, "type": "manual", "config": {"instruction": "step"}}
            for i in range(1, 100)
        ])
        v = PlanValidator()
        result = v.validate(plan, test_case=None)
        count_issues = [i for i in result.issues if i.rule == "excess_steps"]
        assert len(count_issues) == 0


# ── 集成: 完整 Plan 验证 ──────────────────────────────────────

class TestFullValidation:
    def test_valid_plan_passes(self):
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {
                "method": "POST", "path": "/live/game/play_sign_in_status",
                "headers": {"Content-Type": "application/json"},
                "body": {"h_av": "5.97.0"},
            }, "assertions": [
                {"type": "json_path", "path": "$.data.signed_today", "expected": False},
                {"type": "json_path", "path": "$.data.eligible_status", "expected": 1},
            ]},
            {"step_id": 2, "type": "api", "config": {
                "method": "POST", "path": "/live/account/trade_wealth_detail",
                "headers": {"Content-Type": "application/json"},
                "body": {},
            }, "assertions": []},
            {"step_id": 3, "type": "api", "config": {
                "method": "POST", "path": "/live/facetime/check_in",
                "headers": {"Content-Type": "application/json"},
                "body": {},
            }, "assertions": [
                {"type": "json_path", "path": "$.ret", "expected": 1},
            ]},
        ])
        v = PlanValidator(capability=CAPABILITY, max_extra_steps=2)
        result = v.validate(plan, test_case={
            "steps": [{"step": 1}, {"step": 2}, {"step": 3}],
            "expected_results": [
                "签到状态接口返回 signed_today=false",
                "签到前用户财富值记录成功",
                "签到接口返回 ret=1，签到成功",
            ],
        })
        assert result.valid
        assert result.summary["errors"] == 0

    def test_hallucinated_plan_fails(self):
        """综合幻觉: 未知 endpoint + 错误 method + 脑补断言 + 过多步骤."""
        plan = make_plan([
            {"step_id": 1, "type": "api", "config": {
                "method": "GET", "path": "/live/game/play_sign_in_status",
            }, "assertions": [
                {"type": "json_path", "path": "$.data.hallucinated_xyz", "expected": "magic"},
            ]},
            {"step_id": 2, "type": "api", "config": {
                "method": "POST", "path": "/live/nonexistent/hallucinated_api",
            }, "assertions": [
                {"type": "json_path", "path": "$.data.another_hallucination", "expected": 42},
            ]},
        ])
        v = PlanValidator(capability=CAPABILITY, max_extra_steps=1)
        result = v.validate(plan, test_case=TC_SIGNIN)

        assert not result.valid
        assert result.summary["errors"] > 0

        rules = {i.rule for i in result.issues}
        assert "method_mismatch" in rules
        assert "unknown_endpoint" in rules
        assert "assertion_not_from_tc" in rules

    def test_validation_result_to_dict(self):
        plan = make_plan([
            {"step_id": 1, "type": "graphql", "config": {}},
        ])
        v = PlanValidator()
        result = v.validate(plan)
        d = result.to_dict()
        assert "valid" in d
        assert "issues" in d
        assert "summary" in d
        assert isinstance(d["issues"], list)
        assert isinstance(d["summary"], dict)
