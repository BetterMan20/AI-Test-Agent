# -*- coding: utf-8 -*-
"""S4 用例意图回填：把 test_cases 的意图视图合并进 test_design.json。

产物分层契约（用户决策）：
- test_design.json  = 意图层单一可信源：测试模型/场景/测试点/风险/覆盖 + 用例意图
- execution_plan.json = 执行层产物：执行器/参数/断言/证据（由 planner 汇聚生成）

本模块只做确定性合并，不调用 LLM；保证「意图 → 计划 → 执行」可追溯链路的源头稳定。
"""
from __future__ import annotations

from typing import Any


def build_case_intents(test_cases: dict[str, Any],
                       test_design: dict[str, Any]) -> list[dict[str, Any]]:
    """从 test_cases 提取意图视图，按 test_point 回填 objective/related_risks。"""
    points = {
        p.get("id", ""): p for p in test_design.get("test_points", [])
    }
    intents: list[dict[str, Any]] = []
    for tc in test_cases.get("test_cases", []):
        pid = tc.get("test_point_id", "")
        point = points.get(pid, {})
        intents.append({
            "id": tc.get("id", ""),
            "title": tc.get("title", ""),
            "priority": tc.get("priority") or point.get("priority", ""),
            "test_point_id": pid,
            "scenario_ref": tc.get("scenario_ref", ""),
            "objective": point.get("objective", ""),
            "related_risks": point.get("related_risks", []),
            "source_facts": tc.get("source_facts", []),
            "related_gaps": tc.get("related_gaps", []),
            "expected_results": tc.get("expected_results", []),
        })
    return intents


def merge_case_intents(test_design: dict[str, Any],
                       test_cases: dict[str, Any]) -> dict[str, Any]:
    """把 case_intents 段并入 test_design，并补 case 级覆盖统计。"""
    intents = build_case_intents(test_cases, test_design)
    merged = dict(test_design)
    merged["case_intents"] = intents

    cov = dict(merged.get("coverage") or {})
    cov["covered_test_points"] = sorted({
        i["test_point_id"] for i in intents if i.get("test_point_id")
    })
    cov["case_count"] = len(intents)
    merged["coverage"] = cov
    return merged
