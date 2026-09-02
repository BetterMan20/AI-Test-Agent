"""Execution result data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepResult:
    """单个执行步骤的结果。"""

    step_id: int
    step_type: str  # api | db | adb | manual
    status: str  # pass | fail | error | skip
    output: Any = None
    evidence_refs: list[str] = field(default_factory=list)
    assertions_passed: int = 0
    assertions_failed: int = 0
    error: str | None = None
    duration_ms: int = 0


@dataclass
class TestCaseResult:
    """单条 TC 的执行结果。"""

    tc_id: str
    title: str
    status: str  # pass | fail | error | skip
    step_results: list[StepResult] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    duration_ms: int = 0
    error: str | None = None

    @property
    def total_steps(self) -> int:
        return len(self.step_results)

    @property
    def passed_steps(self) -> int:
        return sum(1 for r in self.step_results if r.status == "pass")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tc_id": self.tc_id,
            "title": self.title,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "steps": [
                {
                    "step_id": s.step_id,
                    "type": s.step_type,
                    "status": s.status,
                    "evidence_refs": s.evidence_refs,
                    "assertions_passed": s.assertions_passed,
                    "assertions_failed": s.assertions_failed,
                    "error": s.error,
                    "duration_ms": s.duration_ms,
                }
                for s in self.step_results
            ],
        }


@dataclass
class ExecutionResult:
    """整批执行结果。"""

    results: list[TestCaseResult] = field(default_factory=list)
    duration_ms: int = 0

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == "pass")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == "fail")

    @property
    def errored(self) -> int:
        return sum(1 for r in self.results if r.status == "error")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == "skip")

    def to_dict(self) -> dict:
        return {
            "summary": {
                "total": self.total,
                "pass": self.passed,
                "fail": self.failed,
                "error": self.errored,
                "skip": self.skipped,
            },
            "duration_ms": self.duration_ms,
            "results": [
                {
                    "tc_id": r.tc_id,
                    "title": r.title,
                    "status": r.status,
                    "duration_ms": r.duration_ms,
                    "error": r.error,
                    "steps": [
                        {
                            "step_id": s.step_id,
                            "type": s.step_type,
                            "status": s.status,
                            "evidence_refs": s.evidence_refs,
                            "assertions_passed": s.assertions_passed,
                            "assertions_failed": s.assertions_failed,
                            "error": s.error,
                            "duration_ms": s.duration_ms,
                        }
                        for s in r.step_results
                    ],
                }
                for r in self.results
            ],
        }
