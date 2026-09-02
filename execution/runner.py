"""Execution runner — dispatches steps to tools and collects results."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

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
        evidence_collector: Any | None = None,
        verifier: type[RuleVerifier] = RuleVerifier,
    ):
        self._tools: dict[str, Any | None] = {
            "api": api_client,
            "db": db_client,
            "adb": adb_client,
        }
        self._evidence = evidence_collector
        self._verifier = verifier

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

        return None

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
            except Exception:
                pass
        return refs

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
