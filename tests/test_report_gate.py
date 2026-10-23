# -*- coding: utf-8 -*-
"""报告聚合入口（最后一公里）回归测试：Release Gate 三态决策 + 缺陷注入渲染。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from execution.report import (
    GATE_GO, GATE_GO_WITH_WARNINGS, GATE_NO_GO, aggregate_report, decide_gate, _load_defects,
)


def _result(tc_pass=26, tc_fail=0, tc_error=0, biz=None) -> dict:
    biz = biz or {}
    steps = []
    verdicts = list(biz.items())
    tc_results = []
    i = 0
    for v, n in verdicts:
        for _ in range(n):
            i += 1
            tc_results.append({
                "tc_id": f"TC-{i:03d}", "title": "x", "status": "pass",
                "duration_ms": 1,
                "steps": [{"step_id": 1, "type": "api", "status": "pass",
                           "assertions_passed": 1, "assertions_failed": 0,
                           "duration_ms": 1, "evidence_refs": [],
                           "captured_ret": 1, "replayed_ret": {"reproduced": 1, "auth_expired": -11, "anti_replay": -1}.get(v, -1),
                           "business_verdict": v}],
            })
    # 补齐 pass 数
    while len(tc_results) < tc_pass:
        tc_results.append({"tc_id": f"TC-X{len(tc_results)}", "title": "x", "status": "pass",
                           "duration_ms": 1, "steps": []})
    return {
        "run_time": "t", "endpoint_substring": "ep", "capture_dir": "c",
        "summary": {"tc_batch": {"total": tc_pass + tc_fail + tc_error,
                                 "pass": tc_pass, "fail": tc_fail, "error": tc_error, "skip": 0},
                    "api_replay": {"total": 0, "pass": 0}, "ui_flow": {"total": 0, "pass": 0}},
        "api_replay": [], "tc_results": tc_results, "ui_flow": [],
    }


class GateDecisionTest(unittest.TestCase):
    def test_go_when_all_reproduced(self):
        g = decide_gate(_result(biz={"reproduced": 3}), [])
        self.assertEqual(g["gate"], GATE_GO)

    def test_go_with_warnings_on_env_only_not_reproduced(self):
        g = decide_gate(_result(biz={"auth_expired": 2, "anti_replay": 1}), [])
        self.assertEqual(g["gate"], GATE_GO_WITH_WARNINGS)
        self.assertIn("环境归因", g["reasons"][0])

    def test_no_go_on_fail(self):
        g = decide_gate(_result(tc_pass=25, tc_fail=1, biz={"reproduced": 1}), [])
        self.assertEqual(g["gate"], GATE_NO_GO)

    def test_no_go_on_open_defects(self):
        d = [{"defect_id": "DRAFT-TC-1", "tc_id": "TC-1", "status": "fail",
              "severity_hint": "x", "title": "t", "summary": {"failed_step_count": 1},
              "evidence_refs": []}]
        g = decide_gate(_result(biz={"reproduced": 1}), d)
        self.assertEqual(g["gate"], GATE_NO_GO)
        self.assertIn("缺陷草稿", g["reasons"][0])

    def test_business_mismatch_flagged_in_warning(self):
        g = decide_gate(_result(biz={"business_mismatch": 1}), [])
        self.assertEqual(g["gate"], GATE_GO_WITH_WARNINGS)
        self.assertIn("人工排查", g["reasons"][0])


class AggregateTest(unittest.TestCase):
    def test_writes_gate_json_and_html_with_defects(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            rjson = td / "execution_result.json"
            rjson.write_text(json.dumps(_result(biz={"auth_expired": 2}), ensure_ascii=False), encoding="utf-8")
            ddir = td / "defects"
            ddir.mkdir()
            (ddir / "TC-9.json").write_text(json.dumps({
                "defect_id": "DRAFT-TC-9", "tc_id": "TC-9", "status": "fail",
                "severity_hint": "疑似产品缺陷", "title": "x",
                "summary": {"failed_step_count": 1}, "evidence_refs": ["a.png"]}), encoding="utf-8")
            out = aggregate_report(rjson, defect_dir=ddir)
            # NO_GO（有未决缺陷）
            self.assertEqual(out["gate"]["gate"], GATE_NO_GO)
            gate_file = Path(out["gate_json"])
            self.assertTrue(gate_file.exists())
            self.assertEqual(json.loads(gate_file.read_text(encoding="utf-8"))["gate"], GATE_NO_GO)
            html_txt = Path(out["html"]).read_text(encoding="utf-8")
            self.assertIn("Release Gate：NO_GO", html_txt)
            self.assertIn("缺陷草稿（1", html_txt)
            self.assertIn("DRAFT-TC-9", html_txt)
            self.assertTrue(out["checklist"])

    def test_load_defects_missing_dir(self):
        self.assertEqual(_load_defects(Path("nonexistent_dir_xyz")), [])


if __name__ == "__main__":
    unittest.main()
