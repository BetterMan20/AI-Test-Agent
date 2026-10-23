# -*- coding: utf-8 -*-
"""业务码归因分类 + 报告两层呈现的回归测试。

背景：S6 报告曾出现「TC 全部 pass 但业务对比全部失败」的矛盾呈现——
协议层(status_code 硬断言)与业务层(ret 观察)混为一谈，且 ret=-11(凭证失效)
被误并入「防重放/限频」。本测试锁定归因分类与渲染修正。
"""
import os
import sys
import unittest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from execution.business_verdict import (
    ENV_VERDICTS, classify_business_verdict, verdict_note,
)
from execution.report_html import _render


class ClassifyTest(unittest.TestCase):
    def test_reproduced(self):
        self.assertEqual(classify_business_verdict(1, 1), "reproduced")
        self.assertEqual(classify_business_verdict(0, 0), "reproduced")

    def test_env_verdicts_not_product_defects(self):
        self.assertEqual(classify_business_verdict(1, -11), "auth_expired")
        self.assertEqual(classify_business_verdict(1, -1), "anti_replay")
        self.assertEqual(classify_business_verdict(1, -101), "rate_limited")
        self.assertEqual(ENV_VERDICTS, {"auth_expired", "anti_replay", "rate_limited"})

    def test_business_mismatch_and_no_response(self):
        self.assertEqual(classify_business_verdict(1, -500), "business_mismatch")
        self.assertEqual(classify_business_verdict(1, None), "no_response")

    def test_note_mentions_root_cause(self):
        self.assertIn("凭证失效", verdict_note("auth_expired"))
        self.assertIn("防重放", verdict_note("anti_replay"))


def _fixture() -> dict:
    """模拟本轮真实分布：26 条协议层全 pass，业务层 9 凭证失效 + 17 防重放。"""
    def tc(i: int, replayed: int) -> dict:
        return {
            "tc_id": f"TC-{i:03d}", "title": "发红包", "status": "pass",
            "duration_ms": 100,
            "steps": [{
                "step_id": 1, "type": "api", "status": "pass",
                "assertions_passed": 1, "assertions_failed": 0,
                "duration_ms": 50, "evidence_refs": [],
                "captured_ret": 1, "replayed_ret": replayed, "reproduced": False,
            }],
        }
    return {
        "run_time": "2026-09-23 12:00:00", "endpoint_substring": "send_red_packet",
        "capture_dir": "D:/higo-api",
        "summary": {
            "api_replay": {"total": 1, "pass": 0},
            "tc_batch": {"total": 26, "pass": 26, "fail": 0, "error": 0, "skip": 0},
            "ui_flow": {"total": 3, "pass": 2, "skip": 1},
        },
        "api_replay": [{
            "tc_id": "TC-BR-API-1", "endpoint": "/live/room/send_red_packet",
            "replayed": {"status_code": 200},
            "captured": {"ret": 1, "success": True},
            "replayed_ret": -11, "business_reproduced": False,
        }],
        "tc_results": [tc(i, -11 if i <= 9 else -1) for i in range(1, 27)],
        "ui_flow": [],
    }


class ReportRenderTest(unittest.TestCase):
    def test_two_layer_conclusion_and_verdicts(self):
        out = _render(_fixture())
        # 两层语义并列呈现，不再是「全部通过」一句话
        self.assertIn("协议层", out)
        self.assertIn("业务层", out)
        self.assertIn("0/26", out)  # 业务复现卡
        # 归因标签与分布
        self.assertIn("凭证失效", out)
        self.assertIn("防重放", out)
        self.assertIn("凭证失效 9", out)
        self.assertIn("防重放 17", out)
        # -11 不再被误标为防重放/限频
        self.assertIn("Authorization code error", out)

    def test_business_mismatch_renders_bad_pill(self):
        fx = _fixture()
        fx["tc_results"][0]["steps"][0]["replayed_ret"] = -500
        out = _render(fx)
        self.assertIn("业务不符", out)


if __name__ == "__main__":
    unittest.main()
