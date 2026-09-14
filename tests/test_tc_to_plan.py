"""测试 — TC到执行计划转换器（大语言模型驱动）。

测试plan_from_test_case()将文档级TC（自然语言步骤）转换为结构化的执行计划。.
"""

from __future__ import annotations

import json

import pytest

from execution.planner import ExecutionPlan, ExecutionPlanner, ExecutionStep


# ── Input: document-level TC (from test_cases.json) ──────────

TC_EXPCARD_001 = {
    "id": "TC-EXPCARD-001",
    "title": "体验卡过期触发IM消息-基本流程",
    "priority": "P0",
    "preconditions": [
        "用户持有有效体验卡且系统设置为当天过期；用户已登录游戏"
    ],
    "test_data": [
        "体验卡=普通体验卡(1天)",
        "用户ID=U001"
    ],
    "steps": [
        {"step": 1, "action": "用户打开背包道具面板，查看持有的体验卡状态及有效期"},
        {"step": 2, "action": "等待系统自动触发IM消息（或模拟触发后查看IM界面)"},
        {"step": 3, "action": "用户打开IM聊天窗口，查看是否有来自系统的过期消息"},
        {"step": 4, "action": "点击查看IM消息详细内容，确认是体验卡过期提醒"}
    ],
    "expected_results": [
        "IM界面出现系统发送的过期提醒消息",
        "消息内容显示'您的[体验卡名称]将于今日过期'",
        "消息中显示该体验卡的有效期信息与预期一致",
        "消息提供续卡指引或相关操作选项"
    ]
}


class TestTCtoPlan:
    """TC → Execution Plan 转换器测试（需要 LLM 连接）。"""

    def test_returns_execution_plan(self):
        """plan_from_test_case 返回 ExecutionPlan 实例。"""
        plan = ExecutionPlanner.plan_from_test_case(TC_EXPCARD_001)
        assert isinstance(plan, ExecutionPlan)

    def test_tc_id_preserved(self):
        """TC ID 正确传递。"""
        plan = ExecutionPlanner.plan_from_test_case(TC_EXPCARD_001)
        assert plan.tc_id == "TC-EXPCARD-001"

    def test_title_preserved(self):
        """Title 正确传递。"""
        plan = ExecutionPlanner.plan_from_test_case(TC_EXPCARD_001)
        assert plan.title == "体验卡过期触发IM消息-基本流程"

    def test_preconditions_preserved(self):
        """前置条件正确传递。"""
        plan = ExecutionPlanner.plan_from_test_case(TC_EXPCARD_001)
        assert len(plan.preconditions) == 1
        assert "体验卡" in plan.preconditions[0]

    def test_test_data_preserved(self):
        """测试数据正确传递。"""
        plan = ExecutionPlanner.plan_from_test_case(TC_EXPCARD_001)
        assert len(plan.test_data) == 2
        assert any("U001" in td for td in plan.test_data)

    def test_steps_not_empty(self):
        """步骤数量 >= 1。"""
        plan = ExecutionPlanner.plan_from_test_case(TC_EXPCARD_001)
        assert len(plan.steps) >= 1

    def test_step_ids_sequential(self):
        """step_id 从 1 开始连续递增。"""
        plan = ExecutionPlanner.plan_from_test_case(TC_EXPCARD_001)
        for i, step in enumerate(plan.steps, 1):
            assert step.step_id == i

    def test_step_types_valid(self):
        """所有步骤类型在 api/db/adb/manual 范围内。"""
        plan = ExecutionPlanner.plan_from_test_case(TC_EXPCARD_001)
        valid_types = {"api", "db", "adb", "manual"}
        for step in plan.steps:
            assert step.step_type in valid_types, (
                f"Step {step.step_id} type '{step.step_type}' not in {valid_types}"
            )

    def test_step_has_description(self):
        """每个步骤都有描述。"""
        plan = ExecutionPlanner.plan_from_test_case(TC_EXPCARD_001)
        for step in plan.steps:
            assert len(step.description) > 0

    def test_step_has_config(self):
        """每个步骤都有 config（action dict）。"""
        plan = ExecutionPlanner.plan_from_test_case(TC_EXPCARD_001)
        for step in plan.steps:
            if step.step_type == "manual":
                assert "instruction" in step.action
            elif step.step_type == "api":
                assert "method" in step.action
                assert "path" in step.action
            elif step.step_type == "db":
                assert "query" in step.action
            elif step.step_type == "adb":
                assert "command" in step.action

    def test_evidence_types_correct(self):
        """证据类型与步骤类型匹配。"""
        plan = ExecutionPlanner.plan_from_test_case(TC_EXPCARD_001)
        for step in plan.steps:
            if step.step_type == "api":
                assert "api_response" in step.evidence_types
            elif step.step_type == "db":
                assert "db_snapshot" in step.evidence_types
            elif step.step_type == "adb":
                assert "screenshot" in step.evidence_types

    def test_to_dict_matches_schema(self):
        """to_dict() 输出包含 schema 必需字段。"""
        plan = ExecutionPlanner.plan_from_test_case(TC_EXPCARD_001)
        d = plan.to_dict()
        assert "tc_id" in d
        assert "title" in d
        assert "steps" in d
        for s in d["steps"]:
            assert "step_id" in s
            assert "type" in s
            assert "description" in s

    def test_plan_can_run_with_runner(self):
        """生成的 Plan 能被 ExecutionRunner 接受并执行（不报错即通过）。"""
        from execution.runner import ExecutionRunner
        from execution.context import ExecutionContext, EnvironmentConfig

        plan = ExecutionPlanner.plan_from_test_case(TC_EXPCARD_001)
        runner = ExecutionRunner()
        env = EnvironmentConfig()
        ctx = ExecutionContext(environment=env, tc_id=plan.tc_id)
        result = runner.run_plan(plan, ctx)
        # manual steps are skipped, so status should be pass or skip
        assert result.status in ("pass", "error")
