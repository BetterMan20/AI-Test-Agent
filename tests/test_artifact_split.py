# -*- coding: utf-8 -*-
"""产物拆分闭环回归测试：

意图层(test_design.json 回填) → 汇聚计划(execution_plan.json) → 直读执行 → 失败缺陷草稿。

全部用确定性路径（--no-llm / manual 步骤 / 假结果行），不依赖 LLM、设备与网络。
"""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from workflow.case_intent import build_case_intents, merge_case_intents
from execution.planner import ExecutionPlanner, ExecutionPlan, _main_plan_all
from execution.defect_draft import build_defect_draft, render_defect_md, save_defect_drafts
from execution.batch_regression import BatchRegressor, RegressionConfig


DESIGN = {
    "test_model": {"test_objects": [], "state_dimensions": [],
                   "condition_dimensions": [], "business_flows": [], "risk_points": []},
    "test_scenarios": [],
    "test_points": [{
        "id": "TP-RED-001", "title": "红包入口", "objective": "验证入口展示逻辑",
        "priority": "P0", "test_method": ["scenario_testing"],
        "scenario_refs": ["SC001"], "source_facts": ["F005"],
        "related_risks": ["RP001"], "design_basis": "需求 3.1",
    }],
    "blocked_points": [],
}

CASES = {
    "test_cases": [{
        "id": "TC-TCRED-001", "title": "公开房间红包入口显示", "priority": "P0",
        "test_point_id": "TP-RED-001", "scenario_ref": "SC001",
        "source_facts": ["F005", "F008"], "related_gaps": [],
        "preconditions": ["用户已登录"],
        "test_data": ["房间类型=公开"],
        "steps": [{"step": 1, "action": "进入房间"}, {"step": 2, "action": "查看红包入口"}],
        "expected_results": ["入口显示在礼物面板右下角"],
    }],
    "blocked_cases": [],
}


class CaseIntentTest(unittest.TestCase):
    def test_merge_intents_into_design(self):
        merged = merge_case_intents(DESIGN, CASES)
        intents = merged["case_intents"]
        self.assertEqual(len(intents), 1)
        it = intents[0]
        self.assertEqual(it["id"], "TC-TCRED-001")
        self.assertEqual(it["objective"], "验证入口展示逻辑")     # 回填自 test_point
        self.assertEqual(it["related_risks"], ["RP001"])          # 回填自 test_point
        self.assertEqual(it["source_facts"], ["F005", "F008"])
        self.assertEqual(it["expected_results"], ["入口显示在礼物面板右下角"])
        # case 级覆盖统计
        self.assertEqual(merged["coverage"]["case_count"], 1)
        self.assertEqual(merged["coverage"]["covered_test_points"], ["TP-RED-001"])
        # 原 S3 段不被破坏
        self.assertEqual(len(merged["test_points"]), 1)


class PlanSetTest(unittest.TestCase):
    def test_traceability_carried_from_tc(self):
        plan = ExecutionPlanner().plan(CASES["test_cases"][0], None)
        d = plan.to_dict()
        tr = d["traceability"]
        self.assertEqual(tr["test_point_id"], "TP-RED-001")
        self.assertEqual(tr["scenario_ref"], "SC001")
        self.assertEqual(tr["source_facts"], ["F005", "F008"])

    def test_plan_all_writes_consolidated_file(self):
        tmp = tempfile.mkdtemp(prefix="planset_")
        tc_file = Path(tmp) / "tcs.json"
        tc_file.write_text(json.dumps(CASES, ensure_ascii=False), encoding="utf-8")
        out = Path(tmp) / "execution_plan.json"
        args = types.SimpleNamespace(
            tc_file=str(tc_file), out=str(out), no_llm=True, capability_dir="__none__")
        rc = _main_plan_all(args, ExecutionPlanner())
        self.assertEqual(rc, 0)

        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(doc["meta"]["count"], 1)
        self.assertEqual(doc["meta"]["mode"], "plan(确定性)")
        plan = doc["plans"][0]
        self.assertEqual(plan["tc_id"], "TC-TCRED-001")
        self.assertEqual(plan["traceability"]["test_point_id"], "TP-RED-001")
        self.assertTrue(plan["steps"])


class PlanFileRunTest(unittest.TestCase):
    def test_run_plans_from_file(self):
        """直读汇聚计划执行：计划即输入契约，不再二次派生。"""
        tmp = tempfile.mkdtemp(prefix="planrun_")
        plan_doc = {
            "meta": {"generated_at": "t", "source": "x", "count": 1, "mode": "test"},
            "plans": [{
                "tc_id": "TC-TCRED-001", "title": "入口显示",
                "steps": [{"step_id": 1, "type": "manual",
                           "description": "人工查看入口",
                           "config": {"instruction": "人工查看入口"},
                           "assertions": [], "evidence_types": []}],
                "preconditions": [], "test_data": [],
                "traceability": {"test_point_id": "TP-RED-001"},
            }],
        }
        plan_file = Path(tmp) / "execution_plan.json"
        plan_file.write_text(json.dumps(plan_doc, ensure_ascii=False), encoding="utf-8")

        reg = BatchRegressor(RegressionConfig(
            capture_dir=tmp, evidence_root=str(Path(tmp) / "ev"),
            plan_file=str(plan_file), defect_draft=False,
        ))
        try:
            rows = reg.run_tc_batch()
        finally:
            reg.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tc_id"], "TC-TCRED-001")
        self.assertIn(rows[0]["status"], ("pass", "skip"))
        self.assertEqual(len(reg._last_plans), 1)


class DefectDraftTest(unittest.TestCase):
    def _fail_row(self):
        return {
            "tc_id": "TC-TCRED-001", "title": "公开房间红包入口显示",
            "status": "fail", "duration_ms": 120, "error": None,
            "steps": [
                {"step_id": 1, "type": "appium", "status": "fail",
                 "evidence_refs": ["ev/step1_appium_page_source.xml"],
                 "assertions_passed": 0, "assertions_failed": 1,
                 "error": "断言未满足: 红包已开启", "duration_ms": 100},
                {"step_id": 2, "type": "manual", "status": "skip",
                 "evidence_refs": [], "assertions_passed": 0,
                 "assertions_failed": 0, "error": None, "duration_ms": 0},
            ],
            "evidence_refs": ["ev/step1_appium_page_source.xml"],
        }

    def test_draft_content_and_files(self):
        plan = ExecutionPlanner.plan_from_dict({
            "tc_id": "TC-TCRED-001", "title": "公开房间红包入口显示",
            "traceability": {"test_point_id": "TP-RED-001", "scenario_ref": "SC001",
                             "source_facts": ["F005"]},
            "steps": [
                {"step_id": 1, "type": "appium", "description": "点击红包入口",
                 "config": {"operation": "tap", "target": "tv_red_packet_status_overlay"},
                 "assertions": [{"type": "text_contains", "expected": "红包已开启"}],
                 "evidence_types": ["appium_snapshot"]},
                {"step_id": 2, "type": "manual", "description": "人工复核",
                 "config": {"instruction": "人工复核"}, "assertions": [], "evidence_types": []},
            ],
        })
        tmp = tempfile.mkdtemp(prefix="defect_")
        written = save_defect_drafts([self._fail_row()], [plan], tmp,
                                     env={"device_serial": "emulator-5554"})
        self.assertEqual(len(written), 1)
        draft = json.loads(Path(written[0]).read_text(encoding="utf-8"))
        self.assertTrue(draft["draft"])
        self.assertEqual(draft["status"], "fail")
        self.assertIn("疑似产品缺陷", draft["severity_hint"])
        self.assertEqual(draft["summary"]["failed_step_count"], 1)
        self.assertEqual(draft["traceability"]["test_point_id"], "TP-RED-001")
        self.assertIn("点击红包入口", draft["repro_steps"][0])
        self.assertEqual(draft["environment"]["device_serial"], "emulator-5554")

        md = Path(written[0]).with_suffix(".md").read_text(encoding="utf-8")
        self.assertIn("## 复现步骤", md)
        self.assertIn("## 失败步骤（期望 vs 实际）", md)
        self.assertIn("step1_appium_page_source.xml", md)

    def test_pass_rows_produce_no_draft(self):
        tmp = tempfile.mkdtemp(prefix="defect_pass_")
        row = self._fail_row()
        row["status"] = "pass"
        self.assertEqual(save_defect_drafts([row], [], tmp), [])


if __name__ == "__main__":
    unittest.main()
