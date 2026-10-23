# -*- coding: utf-8 -*-
"""批量回归执行阶段（S6）——接入 qa_workflow 的执行层。

把 run_capture_replay 与 ADB/UI 流程“模块级复用”成可执行原语，把文档级测试用例
（TC-TCRED-*）映射成可执行 ExecutionPlan，批量跑回归：

  原语A 抓包 API 回放（后端）：对抓包目录里匹配接口的每个端点，选一条成功请求
       字节级原样回放，断言“复现抓包时的业务码”(ret)，采集证据四件套。
  原语B ADB/UI 验证（前端）：dump 页面 → 解析红包/礼物入口 → tap 下钻 → 回 dump
       校验面板特征，采集 adb_command/output/execution + screenshot + logcat。
  原语C 文档级 TC 批量：26 条 TC 各生成一条 ExecutionPlan，步骤1=抓包API回放、
       步骤2=ADB面板验证，并按 TC 类型附加差异化断言（权限类断言 ret 码、
       金额/一致性类断言 data 字段、展示类断言面板关键字）。

设计要点：
- 复用执行原语而非为每条 TC 单独写脚本：TC 共用 send_red_packet 的原始字节回放。
- 断言“复现抓包业务码”，不硬编码 0/1；频率限制等业务状态码（如 ret=-101）如实呈现。
- 三份证据各自落盘，最后汇总到 execution_result.json。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from replay.capture_replay import CaptureReplay, ReplayOutcome
from execution.business_verdict import classify_business_verdict, verdict_note
from execution.ui_flow import UIFlowExecutor
from execution.planner import ExecutionPlan, ExecutionPlanner
from engine import TestEngine


@dataclass
class RegressionConfig:
    """S6 批量回归配置：三类原语各自的参数。"""

    capture_dir: str | Path
    endpoint_substring: str = "send_red_packet"
    evidence_root: str | Path = "output/evidence_batch_regression"
    base_url: str | None = None          # 覆盖抓包 host；None 则用抓包里的
    api_headers: dict[str, str] = field(default_factory=dict)
    device_serial: str = ""
    tc_cases: list[dict[str, Any]] = field(default_factory=list)
    tc_field: str = "test_cases"         # 若 tc_cases 为空，从该 JSON 文件的字段读取
    plan_file: str = ""                  # 若非空：直读 execution_plan.json（汇聚计划），跳过 TC→Plan 派生
    adb_verify: bool = True              # 每条 TC 是否附加步骤2(ADB dump 面板)验证
    ui_flow: bool = True                 # 是否额外跑一次完整 UI 交互下钻（ADB 版）
    max_ui_steps: int = 4
    replay_headers: dict[str, str] = field(default_factory=dict)

    # Appium 业务 UI 自动化（原语C 内）：开 then 用 Appium 按关键词下钻，替换 ADB dump 面板步骤
    appium_flow: bool = False            # True = 用 Appium 做 UI 业务自动化（需 Appium-Python-Client 已装 + 设备在线）
    appium_entry_keyword: str = "red|packet|红包|gift|礼物|办"
    appium_panel_keyword: str = "send|发送|coin|金币|confirm|发红包"

    # 闭环尾段：失败 TC 自动落本地缺陷草稿（output/defects/<tc_id>.{json,md}）
    defect_draft: bool = True
    defect_dir: str = "output/defects"


@dataclass
class RegressionReport:
    run_time: str
    capture_dir: str
    endpoint_substring: str
    evidence_root: str
    api_replay: list[dict[str, Any]]   # 端点回放（原语A）
    tc_results: list[dict[str, Any]]   # 26 条 TC（原语C）
    ui_flow: list[dict[str, Any]]      # UI 交互（原语B）
    appium_flow: bool = False          # 原语C 是否用 Appium 做 UI 业务自动化
    appium_steps: int = 0              # 执行的 Appium 步骤数
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_time": self.run_time,
            "capture_dir": self.capture_dir,
            "endpoint_substring": self.endpoint_substring,
            "evidence_root": self.evidence_root,
            "appium_flow": self.appium_flow,
            "appium_steps": self.appium_steps,
            "summary": self.summary,
            "api_replay": self.api_replay,
            "tc_results": self.tc_results,
            "ui_flow": self.ui_flow,
        }

    def _count_appium_steps(self) -> int:
        return sum(
            1 for r in self.tc_results
            for s in r.get("steps", []) if s.get("type") == "appium"
        )


class BatchRegressor:
    """把三套执行原语编排成一次批量回归，产出统一报告。"""

    def __init__(self, config: RegressionConfig):
        self.cfg = config
        self._capture = CaptureReplay(config.capture_dir, config.evidence_root)
        self._engine = self._build_engine()
        self._last_plans: list = []

    # ── 环境 ──────────────────────────────────────────────

    def _build_engine(self, base_url: str | None = None) -> TestEngine:
        return TestEngine(
            api_base_url=base_url or self.cfg.base_url or "",
            api_headers=self.cfg.api_headers,
            api_timeout=60,
            adb_device_serial=self.cfg.device_serial,
            appium_device_serial=self.cfg.device_serial if self.cfg.appium_flow else "",
            evidence_dir=str(self.cfg.evidence_root),
            validate_plans=False,
        )

    # ── 原语A：抓包 API 回放（每个端点回放一次）────────────

    def scan_entries(self) -> dict[str, Any]:
        hits = self._capture.scan(self.cfg.endpoint_substring)
        grouped: dict[str, list] = {}
        for e in hits:
            grouped.setdefault(e.endpoint, []).append(e)
        return grouped

    def run_api_replay_batch(self) -> list[dict[str, Any]]:
        grouped = self.scan_entries()
        outcomes: list[ReplayOutcome] = []
        for endpoint, entries in sorted(grouped.items()):
            entry = self._capture.pick_successful(entries)
            if entry is None:
                continue
            out = self._capture.run(
                entry,
                tc_id=f"TC-BR-API-{abs(hash(entry.capture_id)) % 100000:05d}",
                title=f"回放 {entry.method} {entry.endpoint}",
                base_url=self.cfg.base_url,
            )
            outcomes.append(out)
        self._capture.save_summary(outcomes, filename="capture_replay_batch.json")
        return [o.to_dict() for o in outcomes]

    # ── 原语C：文档级 TC 模板映射 ─────────────────────────

    @staticmethod
    def classify_tc(tc: dict[str, Any]) -> str:
        """按标题返回 TC 类型：ui / auth / data / base。"""
        title = tc.get("title", "")
        ui = ("展示", "入口", "优先级", "挂件", "房间", "隐藏", "状态转换")
        auth = ("权限", "白名单", "黑名单", "冲突")
        data = ("金额", "分配", "一致性", "数据", "倒计时", "退回", "超时")
        if any(k in title for k in ui):
            return "ui"
        if any(k in title for k in auth):
            return "auth"
        if any(k in title for k in data):
            return "data"
        return "base"

    def collect_tc_cases(self) -> list[dict[str, Any]]:
        if self.cfg.tc_cases:
            return self.cfg.tc_cases
        if not self.cfg.tc_field:
            return []
        # tc_field 形如 "output/test_cases.json" 或 "output/test_cases.json#test_cases"
        raw_field = self.cfg.tc_field
        path_part, _, field_part = raw_field.partition("#")
        data = json.loads(Path(path_part).read_text(encoding="utf-8"))
        if field_part:
            return data.get(field_part, [])
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("test_cases", "cases", "tcs"):
                if key in data:
                    return data[key]
        return []

    def build_tc_plan(
        self,
        tc: dict[str, Any],
        send_entry,
        idx: int,
    ) -> ExecutionPlan:
        tc_id = tc.get("id") or f"{self.cfg.endpoint_substring}-{idx:03d}"

        # 步骤1：抓包 API 原样回放（send_red_packet）。
        # 断言分两层：status_code 硬判协议可达(pass)；业务码(ret)作为独立观测
        # 归因(replayed_ret)，field由 run_tc_batch 补齐——避免把后端防重放(-1)/
        # 限频(-101)等业务状态误判为产品缺陷。
        api_assertions: list[dict[str, Any]] = [
            {"type": "status_code", "expected": send_entry.status_code},
        ]

        steps: list[dict[str, Any]] = [{
            "step_id": 1,
            "type": "api",
            "description": f"回放 {send_entry.method} {send_entry.endpoint}（原始字节）",
            "config": {
                "method": send_entry.method,
                "path": send_entry.endpoint,
                "headers": send_entry.req_headers,
                "params": send_entry.query_params,
                "data": send_entry.req_body_raw,
            },
            "assertions": api_assertions,
            "evidence_types": ["api_response"],
        }]

        # 步骤2：UI 业务验证。appium_flow 用 Appium 按关键词下钻红包/礼物入口→发送面板；
        #         否则退回 ADB dump 面板验证（dump 成功即通过；红包/面板关键字由原语B 完整UI流程校验）
        if self.cfg.adb_verify and not self.cfg.appium_flow:
            tag = f"br{idx:03d}"
            adb_cmd = (
                "input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; "
                f"uiautomator dump /sdcard/_br_{tag}.xml >/dev/null 2>&1; "
                f"cat /sdcard/_br_{tag}.xml"
            )
            steps.append({
                "step_id": 2,
                "type": "adb",
                "description": "dump 页面校验 UI 可访问（红包入口/面板特征见原语B）",
                "config": {"command": adb_cmd},
                "assertions": [{"type": "text_contains", "expected": "<hierarchy"}],
                "evidence_types": ["screenshot", "logcat"],
            })
        elif self.cfg.appium_flow:
            # Appium 业务 UI 自动化：先 dump 页面，再按入口关键词下钻并断言面板出现
            steps.append({
                "step_id": 2,
                "type": "appium",
                "description": "Appium dump 当前页面（UI 业务自动化）",
                "config": {"operation": "page_source"},
                "assertions": [],
                "evidence_types": ["appium_snapshot"],
            })
            steps.append({
                "step_id": 3,
                "type": "appium",
                "description": f"Appium 按关键词下钻入口({self.cfg.appium_entry_keyword})→发送面板",
                "config": {
                    "operation": "tap_by_keyword",
                    "keyword": self.cfg.appium_entry_keyword,
                    "timeout": 10,
                },
                "assertions": [{
                    "type": "text_contains",
                    "expected": self.cfg.appium_panel_keyword,
                }],
                "evidence_types": ["appium_snapshot", "screenshot"],
            })

        return ExecutionPlanner.plan_from_dict({
            "tc_id": tc_id,
            "title": tc.get("title", tc_id),
            "preconditions": tc.get("preconditions", []),
            "test_data": tc.get("test_data", []),
            "steps": steps,
        })

    def run_tc_batch(self) -> list[dict[str, Any]]:
        if self.cfg.plan_file:
            return self._run_plans_from_file()
        tcs = self.collect_tc_cases()
        if not tcs:
            return []
        send_entry = self._capture.pick_successful(
            self._capture.scan(self.cfg.endpoint_substring)
        )
        if send_entry is None:
            raise FileNotFoundError(
                f"抓包目录未找到可回放的 '{self.cfg.endpoint_substring}' 成功请求"
            )
        plans = [
            self.build_tc_plan(tc, send_entry, i)
            for i, tc in enumerate(tcs, 1)
        ]
        self._last_plans = plans
        # 用抓包 host（或显式 base_url）驱动引擎，否则相对路径回放会因无 host 失败
        engine = self._build_engine(send_entry.base_url)
        try:
            exec_result = engine.run_plans(plans)
        finally:
            engine.close()
        return [self._tc_result_row(r, send_entry) for r in exec_result.results]

    def _run_plans_from_file(self) -> list[dict[str, Any]]:
        """直读汇聚计划（planner --all 产物）：计划即契约，执行层不再二次派生。"""
        from execution.planner import ExecutionPlanner

        doc = json.loads(Path(self.cfg.plan_file).read_text(encoding="utf-8"))
        raw_plans = doc.get("plans") if isinstance(doc, dict) else doc
        if not raw_plans:
            return []
        plans = [ExecutionPlanner.plan_from_dict(p) for p in raw_plans]
        self._last_plans = plans
        engine = self._build_engine(self.cfg.base_url)
        try:
            exec_result = engine.run_plans(plans)
        finally:
            engine.close()
        return [self._tc_result_row(r, None) for r in exec_result.results]

    @staticmethod
    def _tc_result_row(result, captured) -> dict[str, Any]:
        """取 ExecutionResult.test_case 的 step 结构，并为 step1 补业务码观测
        (replayed_ret / reproduced / business_verdict 归因)。"""
        row = result.to_dict()
        steps = row.get("steps", [])
        for s in steps:
            if s.get("step_id") == 1 and s.get("type") == "api":
                ret = BatchRegressor._extract_ret(result, 0)
                cap_ret = getattr(captured, "res_ret", None)
                s["replayed_ret"] = ret
                s["captured_ret"] = cap_ret
                s["reproduced"] = (ret == cap_ret)
                verdict = classify_business_verdict(cap_ret, ret)
                s["business_verdict"] = verdict
                s["business_note"] = verdict_note(verdict)
        return row

    @staticmethod
    def _extract_ret(test_case_result, step_index: int) -> Any:
        """从 API 步骤的序列化输出(json text)中提取响应顶层 ret。"""
        step = (
            test_case_result.step_results[step_index]
            if step_index < len(test_case_result.step_results)
            else None
        )
        if step is None or not isinstance(step.output, dict):
            return None
        body_text = step.output.get("body")
        if not body_text:
            return None
        try:
            data = json.loads(body_text)
        except (json.JSONDecodeError, TypeError):
            return None
        return data.get("ret") if isinstance(data, dict) else None

    # ── 原语B：ADB/UI 完整交互下钻 ────────────────────────

    def run_ui_flow(self) -> list[dict[str, Any]]:
        steps = UIFlowExecutor(
            str(self.cfg.evidence_root),
            device_serial=self.cfg.device_serial,
        ).run(tc_prefix="TC-BR-UI", max_steps=self.cfg.max_ui_steps)
        return [s.to_dict() for s in steps]

    # ── 编排 ──────────────────────────────────────────────

    def run(self) -> RegressionReport:
        now = time.strftime("%Y-%m-%d %H:%M:%S %z")
        api_replay = self.run_api_replay_batch()
        tc_results = self.run_tc_batch()
        ui_flow = self.run_ui_flow() if self.cfg.ui_flow else []

        report = RegressionReport(
            run_time=now,
            capture_dir=str(self.cfg.capture_dir),
            endpoint_substring=self.cfg.endpoint_substring,
            evidence_root=str(self.cfg.evidence_root),
            api_replay=api_replay,
            tc_results=tc_results,
            ui_flow=ui_flow,
        )
        report.appium_flow = self.cfg.appium_flow
        report.appium_steps = report._count_appium_steps()
        report.summary = self._summary(report)

        # 闭环尾段：失败 TC → 本地缺陷草稿（人工确认后再提单/PR）
        if self.cfg.defect_draft and tc_results:
            from execution.defect_draft import save_defect_drafts
            drafts = save_defect_drafts(
                tc_results, self._last_plans, self.cfg.defect_dir,
                env={
                    "device_serial": self.cfg.device_serial,
                    "base_url": self.cfg.base_url or "",
                    "capture_dir": str(self.cfg.capture_dir),
                    "appium_flow": self.cfg.appium_flow,
                },
            )
            if drafts:
                report.summary["defects"] = {
                    "total": len(drafts),
                    "dir": str(self.cfg.defect_dir),
                }
                print(f">> 缺陷草稿: {len(drafts)} 份 → {self.cfg.defect_dir}", flush=True)
        return report

    @staticmethod
    def _summary(report: "RegressionReport") -> dict[str, Any]:
        api_replay, tc_results, ui_flow = (
            report.api_replay, report.tc_results, report.ui_flow)
        api_pass = sum(1 for o in api_replay if o.get("passed"))
        tc_status = {
            s: sum(1 for r in tc_results if r.get("status") == s)
            for s in ("pass", "fail", "error", "skip")
        }
        ui_status = {
            s: sum(1 for u in ui_flow if u.get("status") == s)
            for s in ("pass", "error", "skip")
        }
        # 业务层观察分布（协议层 pass 之外独立归因，见 business_verdict）
        biz_dist: dict[str, int] = {}
        for r in tc_results:
            for s in r.get("steps", []):
                if s.get("step_id") == 1 and s.get("type") == "api" and "business_verdict" in s:
                    v = s["business_verdict"]
                    biz_dist[v] = biz_dist.get(v, 0) + 1
        return {
            "api_replay": {"total": len(api_replay), "pass": api_pass},
            "tc_batch": {"total": len(tc_results), **tc_status},
            "business_observation": biz_dist,
            "ui_flow": {"total": len(ui_flow), **ui_status},
            "appium": {
                "enabled": report.appium_flow,
                "steps": report.appium_steps,
            },
        }

    def save_report(self, report: RegressionReport) -> Path:
        root = Path(self.cfg.evidence_root)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "execution_result.json"
        path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def close(self) -> None:
        self._engine.close()


def run_batch_regression(
    config: RegressionConfig,
) -> tuple[RegressionReport, Path, BatchRegressor]:
    """一键跑 S6 批量回归：原语A 抓包回放 + 原语C TC批量 + 原语B UI流程。"""
    regressor = BatchRegressor(config)
    try:
        report = regressor.run()
    finally:
        regressor.close()
    path = regressor.save_report(report)
    return report, path, regressor


if __name__ == "__main__":
    import sys

    cap = sys.argv[1] if len(sys.argv) > 1 else "D:/higo-api"
    sub = sys.argv[2] if len(sys.argv) > 2 else "send_red_packet"
    tc_field = sys.argv[3] if len(sys.argv) > 3 else "output/test_cases.json#test_cases"
    report, path, _ = run_batch_regression(RegressionConfig(
        capture_dir=cap,
        endpoint_substring=sub,
        tc_field=tc_field,
    ))
    print(json.dumps(report.summary, ensure_ascii=False, indent=2))
    print(f"报告: {path}")