"""Execution validator — post-execution result review and gate decision."""

from __future__ import annotations

from dataclasses import dataclass, field

from execution.result import ExecutionResult, StepResult, TestCaseResult


@dataclass
class StepValidation:
    """单步验证结果。"""

    step_id: int
    passed: bool
    assertions_total: int = 0
    assertions_passed: int = 0
    failures: list[str] = field(default_factory=list)


@dataclass
class TCValidation:
    """单条 TC 验证结果。"""

    tc_id: str
    status: str  # pass | fail
    step_validations: list[StepValidation] = field(default_factory=list)


@dataclass
class ExecutionValidation:
    """整批执行验证结果。"""

    status: str  # pass | conditional | block
    tc_validations: list[TCValidation] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)

    @property
    def total_passed(self) -> int:
        return sum(1 for v in self.tc_validations if v.status == "pass")

    @property
    def total_failed(self) -> int:
        return sum(1 for v in self.tc_validations if v.status == "fail")

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "summary": {
                "pass": self.total_passed,
                "fail": self.total_failed,
            },
            "findings": self.findings,
            "tc_validations": [
                {
                    "tc_id": v.tc_id,
                    "status": v.status,
                    "steps": [
                        {
                            "step_id": s.step_id,
                            "passed": s.passed,
                            "assertions_total": s.assertions_total,
                            "assertions_passed": s.assertions_passed,
                            "failures": s.failures,
                        }
                        for s in v.step_validations
                    ],
                }
                for v in self.tc_validations
            ],
        }


class ExecutionValidator:
    """从 ExecutionResult 汇总断言结果，给出 pass / conditional / block 判定。"""

    def validate_step(self, step_result: StepResult) -> StepValidation:
        total = step_result.assertions_passed + step_result.assertions_failed
        passed = (
            step_result.assertions_failed == 0
            and step_result.status != "error"
            and step_result.status != "skip"
        )
        return StepValidation(
            step_id=step_result.step_id,
            passed=passed,
            assertions_total=total,
            assertions_passed=step_result.assertions_passed,
            failures=(
                [step_result.error] if step_result.error else []
            ),
        )

    def validate_tc(self, tc_result: TestCaseResult) -> TCValidation:
        step_vals = [self.validate_step(sr) for sr in tc_result.step_results]
        all_pass = all(sv.passed for sv in step_vals)
        has_error = any(
            sr.status in ("error", "skip") for sr in tc_result.step_results
        )
        status = "fail" if (has_error or not all_pass) else "pass"
        if tc_result.status == "error":
            status = "fail"
        return TCValidation(
            tc_id=tc_result.tc_id,
            status=status,
            step_validations=step_vals,
        )

    def validate_execution(
        self, result: ExecutionResult
    ) -> ExecutionValidation:
        tc_vals = [self.validate_tc(r) for r in result.results]
        failed = sum(1 for v in tc_vals if v.status == "fail")
        passed = sum(1 for v in tc_vals if v.status == "pass")

        if failed == 0 and passed > 0:
            status = "pass"
        elif passed > 0:
            status = "conditional"
        else:
            status = "block"

        findings: list[str] = []
        for v in tc_vals:
            if v.status == "fail":
                findings.append(f"TC {v.tc_id} failed")
            for sv in v.step_validations:
                for failure in sv.failures:
                    findings.append(
                        f"TC {v.tc_id} Step {sv.step_id}: {failure}"
                    )

        return ExecutionValidation(
            status=status,
            tc_validations=tc_vals,
            findings=findings,
        )
