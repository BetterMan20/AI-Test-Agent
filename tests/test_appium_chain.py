# -*- coding: utf-8 -*-
"""appium 步骤类型 · 混合编排链路回归测试。

验证：含 api + appium + db 的 ExecutionPlan 能通过 PlanValidator，
并由 ExecutionRunner 按步骤类型分发到 AppiumController，采集 3 件套证据。
用 FakeAppium 替身，不依赖真机/Appium 服务。
"""
import os
import sys
import unittest
import tempfile

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from execution.context import ExecutionContext, EnvironmentConfig
from execution.planner import ExecutionPlanner
from evidence.collector import EvidenceCollector
from evidence.store import EvidenceStore
from verification.plan_validator import PlanValidator
from execution.runner import ExecutionRunner


class FakeAppium:
    """AppiumController 替身：记录调用 + 返回预设 page_source。"""

    def __init__(self):
        self.calls = []

    def start_server(self):
        self.calls.append("start_server")

    def start_session(self, app_activity=None):
        self.calls.append(f"start_session:{app_activity}")

    def close_session(self):
        self.calls.append("close_session")

    def tap(self, target, timeout=10):
        self.calls.append(f"tap:{target}")

    def tap_by_keyword(self, keyword, timeout=10):
        self.calls.append(f"tap_by_keyword:{keyword}")
        return True

    def input_text(self, target, text):
        self.calls.append(f"input_text:{target}={text}")

    def find(self, rid, timeout=10):
        self.calls.append(f"find:{rid}")

    def find_text(self, text, timeout=10):
        self.calls.append(f"find_text:{text}")

    def find_desc(self, desc, timeout=10):
        self.calls.append(f"find_desc:{desc}")

    def tap_point(self, x, y):
        self.calls.append(f"tap_point:{x},{y}")

    def swipe(self, *args):
        self.calls.append(f"swipe:{list(args)}")

    def back(self):
        self.calls.append("back")

    def page_source(self):
        return "<hierarchy><node text='红包界面已开启' /></hierarchy>"


class _FakeApi:
    class _Resp:
        status_code = 200
        text = "{}"
        headers = {}

        def json(self):
            return {}

    def request(self, **kwargs):
        return self._Resp()

    def close(self):
        pass


class _FakeDb:
    def query(self, query, params=None):
        return [{"status": "ok"}]

    def execute(self, query, params=None):
        return []

    def close(self):
        pass


class AppiumChainTest(unittest.TestCase):
    def _build_plan(self):
        return ExecutionPlanner.plan_from_dict({
            "tc_id": "TC-APPIUM-001",
            "title": "混合编排：API → Appium → DB",
            "steps": [
                {"step_id": 1, "type": "api", "description": "ping",
                 "config": {"method": "GET", "path": "/ping"},
                 "assertions": [{"type": "status_code", "expected": 200}],
                 "evidence_types": ["api_response"]},
                {"step_id": 2, "type": "appium", "description": "打开红包入口",
                 "config": {"operation": "tap",
                            "target": "tv_red_packet_status_overlay"},
                 "assertions": [{"type": "text_contains", "expected": "红包界面已开启"}],
                 "evidence_types": ["appium_snapshot", "screenshot"]},
                {"step_id": 3, "type": "appium", "description": "页面快照",
                 "config": {"operation": "page_source"},
                 "assertions": [],
                 "evidence_types": ["appium_snapshot"]},
                {"step_id": 4, "type": "db", "description": "DB 校验",
                 "config": {"phase": "verify", "query": "SELECT 1"},
                 "assertions": [{"type": "db_rows", "expected": "ok"}],
                 "evidence_types": ["db_snapshot"]},
            ],
        })

    def test_validator_accepts_appium(self):
        plan = self._build_plan()
        vr = PlanValidator().validate(plan)
        self.assertTrue(vr.valid, msg=[i.message for i in vr.issues])

    def test_hybrid_chain_runs_and_collects_evidence(self):
        plan = self._build_plan()
        tmp = tempfile.mkdtemp(prefix="appium_test_")
        collector = EvidenceCollector(EvidenceStore(base_dir=tmp))
        fake = FakeAppium()
        runner = ExecutionRunner(
            api_client=_FakeApi(),
            db_client=_FakeDb(),
            appium_client=fake,
            evidence_collector=collector,
        )
        ctx = ExecutionContext(environment=EnvironmentConfig(), tc_id=plan.tc_id)
        result = runner.run_plan(plan, ctx)
        runner.close()

        self.assertEqual(result.status, "pass")
        self.assertTrue(any("start_session" in c for c in fake.calls))
        self.assertTrue(any(c.startswith("tap:tv_red_packet_status_overlay") for c in fake.calls))
        # appium 证据三件套已落盘
        suffixes = {"_appium_action.json", "_appium_page_source.xml", "_appium_execution.json"}
        paths = {str(p) for p in result.evidence_refs}
        self.assertTrue(any(s.endswith(suf) for s in paths for suf in suffixes))

    def test_tap_by_keyword_dispatch_and_assert(self):
        """tap_by_keyword 操作能分派并基于回吐的 page_source 断言面板关键词。"""
        plan = ExecutionPlanner.plan_from_dict({
            "tc_id": "TC-KW-001", "title": "关键词下钻", "steps": [
                {"step_id": 1, "type": "appium", "description": "下钻",
                 "config": {"operation": "tap_by_keyword",
                            "keyword": "red|红包"},
                 "assertions": [{"type": "text_contains", "expected": "红包界面已开启"}],
                 "evidence_types": ["appium_snapshot"]},
            ],
        })
        tmp = tempfile.mkdtemp(prefix="appium_kw_")
        collector = EvidenceCollector(EvidenceStore(base_dir=tmp))
        fake = FakeAppium()
        runner = ExecutionRunner(appium_client=fake, evidence_collector=collector)
        ctx = ExecutionContext(environment=EnvironmentConfig(), tc_id=plan.tc_id)
        result = runner.run_plan(plan, ctx)
        runner.close()

        self.assertEqual(result.status, "pass")
        self.assertTrue(any("tap_by_keyword:red|红包" in c for c in fake.calls))

    def test_batch_plan_emits_appium_steps_when_enabled(self):
        """appium_flow=True 时，批量回归的 build_tc_plan 应产出 appium 步骤并替换 ADB dump。"""
        from execution.batch_regression import BatchRegressor, RegressionConfig
        import types

        send_entry = types.SimpleNamespace(
            method="POST", endpoint="/v1/red_packet/send", status_code=200,
            req_headers={"h": "1"}, query_params={}, req_body_raw=b"{}", res_ret=0,
        )
        reg = BatchRegressor(RegressionConfig(
            capture_dir="D:/higo-api", device_serial="emulator-5554",
            appium_flow=True, tc_cases=[],
        ))
        plan = reg.build_tc_plan(
            {"id": "TC-RP-001", "title": "发红包", "preconditions": [], "test_data": [],
             "steps": [{"action": "发红包"}, {"action": "看面板"}]},
            send_entry, 1,
        )
        types_in_plan = {s.step_type for s in plan.steps}
        self.assertIn("appium", types_in_plan)
        self.assertNotIn("adb", types_in_plan)
        # 至少一条 tap_by_keyword
        self.assertTrue(any(
            s.step_type == "appium" and s.action.get("operation") == "tap_by_keyword"
            for s in plan.steps))


if __name__ == "__main__":
    unittest.main()