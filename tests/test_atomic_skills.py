# -*- coding: utf-8 -*-
"""原子化 Skill 端到端回归：element_locator / report_synth / env_guardian + efficiency 基线。

锁定契约：输入输出结构、风险分级、摊销计时、容错（adb噪声/缺目录）。
不依赖真机——env_guardian 用桩 ADBClient 验证编排逻辑。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from skills_py.element_locator import locate, _clean_xml
from skills_py.report_synth import synth
from core.efficiency import compare, record

_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" resource-id="" bounds="[0,0][1080,1920]">
    <node class="android.widget.LinearLayout" resource-id="com.example.live:id/gift_panel" text="" content-desc="" clickable="false" bounds="[0,300][1080,900]">
      <node class="android.widget.Button" resource-id="com.example.live:id/btn_send_gift" text="送礼物" content-desc="" clickable="true" bounds="[100,500][400,600]"/>
      <node class="android.widget.TextView" resource-id="" text="红包" content-desc="抢红包入口" clickable="true" bounds="[100,700][400,800]"/>
    </node>
  </node>
</hierarchy>"""


class ElementLocatorTest(unittest.TestCase):
    def test_locate_by_rid(self):
        r = locate(_XML, "send_gift")
        self.assertGreaterEqual(r["count"], 1)
        best = r["matches"][0]
        self.assertEqual(best["confidence"], "high")
        self.assertEqual(best["appium_locator"][0], "id")
        self.assertIn("com.example.live:id/btn_send_gift", best["appium_locator"][1])

    def test_locate_by_text_and_desc(self):
        r = locate(_XML, "红包")
        self.assertGreaterEqual(r["count"], 1)
        self.assertTrue(any(m["text"] == "红包" for m in r["matches"]))

    def test_xpath_uses_class_names(self):
        r = locate(_XML, "send_gift")
        self.assertIn("Button", r["matches"][0]["xpath"])

    def test_adb_noise_tolerance(self):
        noisy = "UI hierchary dumped to: /sdcard/x.xml\n" + _XML
        self.assertIn("<hierarchy", _clean_xml(noisy))
        r = locate(noisy, "send_gift")
        self.assertGreaterEqual(r["count"], 1)

    def test_no_match(self):
        self.assertEqual(locate(_XML, "nonexistent_xyz")["count"], 0)
        self.assertIn("error", locate("not-xml", "x"))


class ReportSynthTest(unittest.TestCase):
    def _write_result(self, td: Path, statuses) -> Path:
        tcs = []
        for i, (st, cap, rep) in enumerate(statuses, 1):
            tcs.append({"tc_id": f"TC-{i}", "title": "t", "status": st, "duration_ms": 100,
                        "steps": [{"step_id": 1, "type": "api", "status": st,
                                   "assertions_passed": 1, "assertions_failed": 0,
                                   "duration_ms": 10, "evidence_refs": [],
                                   "captured_ret": cap, "replayed_ret": rep}]})
        p = td / "execution_result.json"
        p.write_text(json.dumps({"run_time": "t", "endpoint_substring": "e",
                                  "summary": {"tc_batch": {}}, "tc_results": tcs,
                                  "api_replay": [], "ui_flow": []}, ensure_ascii=False), encoding="utf-8")
        return p

    def test_risk_grading(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            rj = self._write_result(td, [
                ("pass", 1, -11),    # 环境归因 → P1
                ("fail", 1, -500),   # 失败 → P0
                ("pass", 1, 1),      # 复现 → P2
            ])
            out = synth(rj, defect_dir=td / "no_defects")
            self.assertEqual(out["risk_dist"], {"P0": 1, "P1": 1, "P2": 1})
            self.assertEqual(out["total"], 3)
            html_txt = Path(out["html_path"]).read_text(encoding="utf-8")
            self.assertIn("P0", html_txt)
            # P0 排在最前（fail 在前）
            self.assertLess(html_txt.find("TC-2"), html_txt.find("TC-1"))

    def test_business_mismatch_is_p0(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            rj = self._write_result(td, [("pass", 1, -500)])  # 协议过但业务不符
            out = synth(rj, defect_dir=td / "no")
            self.assertEqual(out["risk_dist"]["P0"], 1)


class EnvGuardianTest(unittest.TestCase):
    def test_popup_detection_and_heal(self):
        from skills_py.env_guardian import Guardian
        g = Guardian("emu", "com.example.live")
        xml = ('<hierarchy><node class="android.widget.Button" text="知道了" '
               'content-desc="" resource-id="" clickable="true" bounds="[100,100][300,200]"/></hierarchy>')
        pop = g.detect_popup(xml)
        self.assertIsNotNone(pop)
        self.assertEqual(pop["kw"], "知道了")
        self.assertEqual(pop["center"], (200, 150))

    def test_no_popup(self):
        from skills_py.env_guardian import Guardian
        g = Guardian("emu", "com.example.live")
        self.assertIsNone(g.detect_popup("<hierarchy><node text='首页' clickable='false' bounds='[0,0][1,1]'/></hierarchy>"))


class EfficiencyTest(unittest.TestCase):
    def test_record_and_compare(self):
        with tempfile.TemporaryDirectory() as td:
            import core.efficiency as eff
            # 重定向输出目录到临时目录
            orig = eff._OUT_DIR
            eff._OUT_DIR = Path(td)
            try:
                record("element_locator", agent_seconds=1.5, items=5)
                record("element_locator", agent_seconds=2.0, items=5)
                c = compare("element_locator")
                self.assertEqual(c["runs"], 2)
                self.assertAlmostEqual(c["agent_median_s"], 1.75, places=2)
                self.assertIsNotNone(c["saving_pct"])  # 相对默认基线
            finally:
                eff._OUT_DIR = orig


if __name__ == "__main__":
    unittest.main()
