"""Execution runner — dispatches steps to tools and collects results."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

# 支持 `python execution/runner.py`（脚本方式）与 `python -m execution.runner`（模块方式）
# 两种调用：脚本方式下 sys.path 只有 execution/，这里把项目根补进去才能 import execution.*
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from execution.context import ExecutionContext
from execution.exceptions import ToolError
from execution.planner import ExecutionPlan, ExecutionStep
from execution.result import ExecutionResult, StepResult, TestCaseResult
from verification.rule_verifier import RuleVerifier


class ExecutionRunner:
    """顺序执行 ExecutionPlan 中的步骤，采集证据并验证断言。"""

    def __init__(
        self,
        api_client: Any | None = None,
        db_client: Any | None = None,
        adb_client: Any | None = None,
        appium_client: Any | None = None,
        evidence_collector: Any | None = None,
        verifier: type[RuleVerifier] = RuleVerifier,
    ):
        self._tools: dict[str, Any | None] = {
            "api": api_client,
            "db": db_client,
            "adb": adb_client,
            "appium": appium_client,
        }
        self._evidence = evidence_collector
        self._verifier = verifier
        self._appium_session = False

    def run_plan(
        self, plan: ExecutionPlan, context: ExecutionContext
    ) -> TestCaseResult:
        step_results: list[StepResult] = []
        for step in plan.steps:
            result = self._run_step(step, context)
            step_results.append(result)
            context.add_step_result(result)
            if result.status == "error":
                break

        has_fail = any(r.status == "fail" for r in step_results)
        has_error = any(r.status == "error" for r in step_results)
        incomplete = len(step_results) < len(plan.steps)
        if has_error or incomplete:
            status = "error"
        elif has_fail:
            status = "fail"
        else:
            status = "pass"

        all_evidence = [ref for r in step_results for ref in r.evidence_refs]
        return TestCaseResult(
            tc_id=plan.tc_id,
            title=plan.title,
            status=status,
            step_results=step_results,
            evidence_refs=all_evidence,
            duration_ms=sum(r.duration_ms for r in step_results),
        )

    def run_all(
        self,
        plans: list[ExecutionPlan],
        context_factory: Any | None = None,
    ) -> ExecutionResult:
        results: list[TestCaseResult] = []
        total_start = time.time()
        for plan in plans:
            ctx = (
                context_factory(plan.tc_id)
                if context_factory
                else ExecutionContext(
                    environment=None,  # type: ignore[arg-type]
                    tc_id=plan.tc_id,
                )
            )
            results.append(self.run_plan(plan, ctx))
        return ExecutionResult(
            results=results,
            duration_ms=int((time.time() - total_start) * 1000),
        )

    def _run_step(
        self, step: ExecutionStep, context: ExecutionContext
    ) -> StepResult:
        start = time.time()

        if step.step_type == "manual":
            return StepResult(
                step_id=step.step_id,
                step_type=step.step_type,
                status="skip",
                duration_ms=int((time.time() - start) * 1000),
            )

        try:
            output = self._dispatch(step, context)
            passed, failed = self._verify(step, output)
            status = "pass" if failed == 0 else "fail"
            duration_ms = int((time.time() - start) * 1000)
            execution_meta = {
                "duration_ms": duration_ms,
                "status": status,
                "assertions_passed": passed,
                "assertions_failed": failed,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            evidence_refs = self._collect_evidence(
                step, output, context, execution_meta
            )
            return StepResult(
                step_id=step.step_id,
                step_type=step.step_type,
                status=status,
                output=self._serialize_output(output),
                evidence_refs=evidence_refs,
                assertions_passed=passed,
                assertions_failed=failed,
                duration_ms=duration_ms,
            )
        except ToolError as e:
            return StepResult(
                step_id=step.step_id,
                step_type=step.step_type,
                status="error",
                error=str(e),
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return StepResult(
                step_id=step.step_id,
                step_type=step.step_type,
                status="error",
                error=str(e),
                duration_ms=int((time.time() - start) * 1000),
            )

    def _dispatch(
        self, step: ExecutionStep, context: ExecutionContext
    ) -> Any:
        tool = self._tools.get(step.step_type)
        if tool is None:
            raise ToolError(
                step.step_type,
                f"No tool configured for step type: {step.step_type}",
            )
        action = self._resolve_action(step.action, context)

        if step.step_type == "api":
            return tool.request(
                method=action.get("method", "GET"),
                path=action.get("path", ""),
                headers=action.get("headers"),
                json=action.get("body"),
                data=action.get("data"),
                params=action.get("params"),
            )

        if step.step_type == "db":
            query = action.get("query", "")
            params = action.get("params")
            if action.get("phase") == "verify":
                return tool.query(query, params)
            return tool.execute(query, params)

        if step.step_type == "adb":
            return tool.shell(action.get("command", ""))

        if step.step_type == "appium":
            return self._dispatch_appium(tool, action)

        return None

    def _dispatch_appium(self, ctl: Any, action: dict[str, Any]) -> Any:
        """分派 Appium UI 业务操作，统一返回操作后的 page_source（供 text_contains 断言）。

        支持 operation:
          session_start / session_close / page_source / tap / input_text
          find / find_text / find_desc / tap_point / swipe / back
        """
        op = action.get("operation", "page_source")
        timeout = float(action.get("timeout", 10))

        if op == "session_start":
            ctl.start_server()
            ctl.start_session(app_activity=action.get("app_activity"))
            self._appium_session = True
            return "session_started"

        if op == "session_close":
            ctl.close_session()
            self._appium_session = False
            return "session_closed"

        # 其余 UI 操作：确保会话就绪
        self._ensure_appium(ctl)

        if op == "page_source":
            return ctl.page_source()
        if op == "tap":
            ctl.tap(action.get("target", ""), timeout)
        elif op == "tap_by_keyword":
            ctl.tap_by_keyword(action.get("keyword", ""), timeout)
        elif op == "input_text":
            ctl.input_text(action.get("target", ""), action.get("text", ""))
        elif op == "find":
            ctl.find(action.get("target", ""), timeout)
        elif op == "find_text":
            ctl.find_text(action.get("text", ""), timeout)
        elif op == "find_desc":
            ctl.find_desc(action.get("desc", ""), timeout)
        elif op == "tap_point":
            ctl.tap_point(float(action.get("x", 0)), float(action.get("y", 0)))
        elif op == "swipe":
            s = action.get("swipe") or [0, 0, 0, 0, 300]
            ctl.swipe(*[float(v) for v in s[:5]])
        elif op == "back":
            ctl.back()
        else:
            raise ToolError("appium", f"Unknown appium operation: {op}")

        # 操作后回吐页面快照，断言 / 证据都依赖它
        try:
            return ctl.page_source()
        except Exception:
            return ""

    def _ensure_appium(self, ctl: Any) -> None:
        """首次用到 UI 操作时懒启动 server + session。"""
        if self._appium_session:
            return
        ctl.start_server()
        ctl.start_session()
        self._appium_session = True

    def _resolve_action(
        self, action: dict[str, Any], context: ExecutionContext
    ) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for key, value in action.items():
            if isinstance(value, str):
                resolved[key] = context.resolve(value)
            elif isinstance(value, dict):
                resolved[key] = self._resolve_action(value, context)
            elif isinstance(value, list):
                resolved[key] = [
                    context.resolve(v) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                resolved[key] = value
        return resolved

    def _collect_evidence(
        self,
        step: ExecutionStep,
        output: Any,
        context: ExecutionContext,
        execution_meta: dict[str, Any] | None = None,
    ) -> list[str]:
        if self._evidence is None:
            return []
        refs: list[str] = []

        # ADB steps: always collect command + output + execution evidence
        if step.step_type == "adb" and output is not None:
            try:
                evidences = self._evidence.collect_adb_evidence(
                    step.action, output, context.tc_id, step.step_id,
                    execution_meta,
                )
                refs.extend(ev.path for ev in evidences)
            except Exception:
                pass

        for etype in step.evidence_types:
            try:
                if etype == "screenshot" and self._tools.get("adb"):
                    ev = self._evidence.collect_screenshot(
                        self._tools["adb"], context.tc_id, step.step_id
                    )
                    refs.append(ev.path)
                elif etype == "api_response" and step.step_type == "api" and output is not None:
                    evidences = self._evidence.collect_api_evidence(
                        step.action, output, context.tc_id, step.step_id,
                        execution_meta,
                    )
                    refs.extend(ev.path for ev in evidences)
                elif etype == "db_snapshot" and step.step_type == "db" and output is not None:
                    evidences = self._evidence.collect_db_evidence(
                        step.action, output, context.tc_id, step.step_id,
                        execution_meta,
                    )
                    refs.extend(ev.path for ev in evidences)
                elif etype == "logcat" and self._tools.get("adb"):
                    ev = self._evidence.collect_logcat(
                        self._tools["adb"], context.tc_id, step.step_id
                    )
                    refs.append(ev.path)
                elif etype == "appium_snapshot" and step.step_type == "appium" and output is not None:
                    evidences = self._evidence.collect_appium_evidence(
                        step.action, output, context.tc_id, step.step_id,
                        execution_meta,
                    )
                    refs.extend(ev.path for ev in evidences)
            except Exception:
                pass
        return refs

    def close(self) -> None:
        """释放 Appium 会话/服务（若已由本引擎启动）。"""
        ctl = self._tools.get("appium")
        if ctl is None:
            return
        if self._appium_session:
            try:
                ctl.close_session()
            except Exception:
                pass
            self._appium_session = False

    def _verify(
        self, step: ExecutionStep, output: Any
    ) -> tuple[int, int]:
        passed = 0
        failed = 0
        for assertion in step.assertions:
            actual = self._extract_output(output, assertion)
            if self._verifier.check(assertion, actual):
                passed += 1
            else:
                failed += 1
        return passed, failed

    @staticmethod
    def _extract_output(output: Any, assertion: dict[str, Any]) -> Any:
        atype = assertion.get("type")
        if atype == "status_code" and hasattr(output, "status_code"):
            return output.status_code
        if atype == "json_path":
            if hasattr(output, "json"):
                try:
                    return output.json()
                except Exception:
                    return None
            if isinstance(output, (list, dict)):
                return output
        if atype == "text_contains":
            if hasattr(output, "text"):
                return output.text
            if isinstance(output, (list, dict)):
                return json.dumps(output, ensure_ascii=False)
            return str(output) if output is not None else ""
        if atype == "db_rows":
            return output if isinstance(output, list) else []
        if atype == "count":
            return len(output) if isinstance(output, (list, dict)) else 0
        return output

    @staticmethod
    def _serialize_output(output: Any) -> Any:
        if hasattr(output, "status_code"):
            return {
                "status_code": output.status_code,
                "body": output.text[:2000] if hasattr(output, "text") else None,
            }
        if isinstance(output, str):
            return output[:2000]
        return output


if __name__ == "__main__":
    """CLI 入口：真正执行 API/DB/ADB 步骤并采证+验证，打印可读汇总。

    本文件是执行库类；直接运行它时，复用 S6 批量回归(retry 用的同一套
    ExecutionRunner + 客户端 + 证据采集)来产出可见结果，避免静默退出。

    用法:
        python execution/runner.py [capture_dir] [endpoint_substring] [device_serial]
    默认: D:/higo-api  send_red_packet  (evidence输出: output/evidence_batch_regression)
    """
    import argparse
    import shutil
    import subprocess
    from execution.batch_regression import RegressionConfig, run_batch_regression

    def _abs(p: str, base: str = _PROJECT_ROOT) -> str:
        """把相对路径锚定到项目根，避免依赖运行时工作目录(cwd)。"""
        q = os.path.realpath(os.path.join(base, p)) if not os.path.isabs(p) else os.path.realpath(p)
        return q

    def _resolve_device(serial: str) -> tuple[str, bool, bool]:
        """解析设备：给了 serial 直接用；否则查 adb——恰好一台用它，
        零台或多台则禁用 ADB/UI 步骤(仍跑 API/DB)，并附提示。返回 (serial, adb_verify, ui_flow)。"""
        if serial:
            return serial, True, True
        try:
            if shutil.which("adb") is None:
                return "", False, False
            out = subprocess.run(["adb", "devices"], capture_output=True, text=True,
                                 timeout=15).stdout or ""
            serials = [ln.split()[0] for ln in out.splitlines()[1:]
                       if ln.strip() and "device" in ln.split()[-1]]
            if len(serials) == 1:
                return serials[0], True, True
            if len(serials) > 1:
                print("!! 检测到多台 ADB 设备，未自动选择。请指定 device_serial 以启用 ADB/UI 步骤：")
                for s in serials:
                    print("    adb -s", s)
                return "", False, False
            return "", False, False
        except Exception:
            return "", False, False

    _ap = argparse.ArgumentParser(description="执行 ExecutionPlan 的 API/DB/ADB/Appium 步骤，采证+验证")
    _ap.add_argument("capture_dir", nargs="?", default=_abs("D:/higo-api"))
    _ap.add_argument("endpoint_substring", nargs="?", default="send_red_packet")
    _ap.add_argument("device_serial", nargs="?", default="")
    _ap.add_argument("--tc-field", default=f"{_abs('output/test_cases.json')}#test_cases")
    _ap.add_argument("--plan-file", default="",
                     help="直读汇聚计划 execution_plan.json（planner --all 产物），跳过 TC→Plan 派生")
    _ap.add_argument("--evidence-root", default=_abs("output/evidence_batch_regression"))
    _ap.add_argument("--appium", dest="appium", action="store_true",
                     help="用 Appium 做 UI 业务自动化（替换 ADB dump 面板步骤），按关键词下钻红包/礼物入口→发送面板")
    _ap.add_argument("--appium-panel-kw", default=None,
                     help="覆盖 Appium 面板断言关键词（默认 send|发送|coin|金币|confirm|发红包）")
    _args = _ap.parse_args()

    _serial, _adb_verify, _ui_flow = _resolve_device(_args.device_serial)
    if _args.device_serial and _args.device_serial != _serial:
        _serial = _args.device_serial
    _adb_verify = bool(_serial)
    _ui_flow = bool(_serial)
    print(f">> 设备解析: serial={_serial or '(无，ADB/UI 步骤已禁用)'} "
          f"adb_verify={_adb_verify} ui_flow={_ui_flow} appium={_args.appium}", flush=True)

    _report, _path, _ = run_batch_regression(RegressionConfig(
        capture_dir=_args.capture_dir,
        endpoint_substring=_args.endpoint_substring,
        tc_field=_args.tc_field,
        plan_file=_args.plan_file,
        device_serial=_serial,
        evidence_root=_args.evidence_root,
        adb_verify=_adb_verify,
        ui_flow=_ui_flow,
        appium_flow=_args.appium,
        **({"appium_panel_keyword": _args.appium_panel_kw}
           if _args.appium_panel_kw else {}),
    ))
    print("\n========== S6 批量回归 汇总 ==========", flush=True)
    print(json.dumps(_report.summary, ensure_ascii=False, indent=2))
    print(f"报告: {_path}", flush=True)

    # 最后一公里：聚合原始数据 → 人读 HTML + 机读 Release Gate + 人工核查清单
    from execution.report import aggregate_report, GATE_NO_GO
    _agg = aggregate_report(_path)
    _g = _agg["gate"]["gate"]
    print(f"\n===== Release Gate: {_g} =====", flush=True)
    for _r in _agg["gate"]["reasons"]:
        print("  -", _r, flush=True)
    if _agg["defects"]:
        print(f"缺陷草稿 {len(_agg['defects'])} 份（待人工确认）→ output/defects/", flush=True)
    print("\n人工核查清单:", flush=True)
    for _i, _c in enumerate(_agg["checklist"], 1):
        print(f"  {_i}. {_c}", flush=True)
    print(f"\n人读报告: {_agg['html']}", flush=True)
    print(f"机读决策: {_agg['gate_json']}", flush=True)
    raise SystemExit(1 if _g == GATE_NO_GO else 0)
