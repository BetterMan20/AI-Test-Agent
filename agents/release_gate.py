"""
agents/release_gate.py

Release Gate
============

职责：

    根据 Quality Validation 的最终结果执行 Release Policy。

核心链路：

    Quality Validation
            ↓
       Release Gate
            ↓
    PASS / CONDITIONAL / BLOCK

Release Gate 不负责：
    - Requirement Analysis
    - Requirement Gap Detection
    - Test Design
    - Test Case Validation
    - Quality Recalculation
    - Coverage Recalculation

核心原则：

    Quality Validation = Judge
    Release Gate = Decision Policy
"""

from __future__ import annotations

from typing import Any, Dict, List


class ReleaseGate:

    AGENT_NAME = "release_gate"
    STAGE_NAME = "Release Gate"

    # =========================================================
    # Public API
    # =========================================================

    def run(
        self,
        quality_validation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        根据 Quality Validation 结果执行 Release Gate。
        """

        if not quality_validation:

            return self._block(
                code="QUALITY_VALIDATION_MISSING",
                reason=(
                    "Quality Validation result is missing."
                ),
            )

        quality_status = quality_validation.get(
            "quality_status"
        )

        summary = quality_validation.get(
            "summary",
            {},
        )

        p0_count = summary.get(
            "p0_count",
            0,
        )

        p1_count = summary.get(
            "p1_count",
            0,
        )

        # -----------------------------------------------------
        # 1. Quality BLOCK
        # -----------------------------------------------------

        if quality_status == "BLOCK":

            return self._build_result(
                gate="BLOCK",
                reasons=[
                    "Quality Validation status is BLOCK."
                ],
                quality_status=quality_status,
                p0_count=p0_count,
                p1_count=p1_count,
            )

        # -----------------------------------------------------
        # 2. Quality CONDITIONAL
        # -----------------------------------------------------

        if quality_status == "CONDITIONAL":

            return self._build_result(
                gate="CONDITIONAL",
                reasons=[
                    "Quality Validation status is CONDITIONAL."
                ],
                quality_status=quality_status,
                p0_count=p0_count,
                p1_count=p1_count,
            )

        # -----------------------------------------------------
        # 3. Quality PASS
        # -----------------------------------------------------

        if quality_status == "PASS":

            # 安全保护：
            # Quality Validation PASS 时理论上不能存在 P0。
            if p0_count > 0:

                return self._build_result(
                    gate="BLOCK",
                    reasons=[
                        (
                            "Quality Validation reports PASS "
                            "but contains P0 findings."
                        )
                    ],
                    quality_status=quality_status,
                    p0_count=p0_count,
                    p1_count=p1_count,
                )

            return self._build_result(
                gate="PASS",
                reasons=[
                    "Quality Validation passed."
                ],
                quality_status=quality_status,
                p0_count=p0_count,
                p1_count=p1_count,
            )

        # -----------------------------------------------------
        # 4. Unknown Status
        # -----------------------------------------------------

        return self._build_result(
            gate="BLOCK",
            reasons=[
                (
                    "Unknown Quality Validation status: "
                    f"{quality_status}"
                )
            ],
            quality_status=quality_status,
            p0_count=p0_count,
            p1_count=p1_count,
        )

    # =========================================================
    # Helpers
    # =========================================================

    @staticmethod
    def _block(
        code: str,
        reason: str,
    ) -> Dict[str, Any]:

        return {
            "schema_version": "1.0",
            "gate": "BLOCK",
            "reasons": [
                reason
            ],
            "policy": {
                "code": code,
            },
        }

    @staticmethod
    def _build_result(
        gate: str,
        reasons: List[str],
        quality_status: str,
        p0_count: int,
        p1_count: int,
    ) -> Dict[str, Any]:

        return {
            "schema_version": "1.0",
            "gate": gate,
            "reasons": reasons,

            "quality_snapshot": {
                "quality_status": quality_status,
                "p0_count": p0_count,
                "p1_count": p1_count,
            },

            "policy": {
                "deterministic": True,
                "uses_llm": False,
                "recalculates_quality": False,
                "recalculates_coverage": False,
                "final_release_decision": True,
            },
        }