"""
agents/quality_review.py

Quality Review
==============

职责：
    对整个 QA Workflow 进行最终质量审判。

核心链路：

Requirement
    ↓
Facts
    ↓
Analysis
    ↓
Gap
    ↓
Test Design
    ↓
Test Points
    ↓
Test Cases
    ↓
Validator Evidence

Quality Validation 判断：

    这条证据链是否完整、合理、可追溯。

核心原则：

    Evidence Based
    No Assumption
    No Generation
    No Repair

Quality Validation 不：
    - 生成 Test Case
    - 修改 Test Design
    - 修改 Validator Result
    - 重新验证 Test Case
    - 重新计算 Test Point Coverage
    - 重新做 Gap Detection
"""

from __future__ import annotations

from typing import Any, Dict, List, Set


class QualityReview:
    """
    Workflow 最终质量审判器。

    确定性 Agent。
    不调用 LLM。
    """

    AGENT_NAME = "quality_review"
    STAGE_NAME = "Quality Review"

    # =========================================================
    # Public API
    # =========================================================

    def run(
        self,
        requirement_fact: Dict[str, Any],
        requirement_analysis: Dict[str, Any],
        requirement_gap: Dict[str, Any],
        test_design: Dict[str, Any],
        test_cases: Dict[str, Any],
        validation_result: Dict[str, Any],
    ) -> Dict[str, Any]:

        findings: List[Dict[str, Any]] = []

        # -----------------------------------------------------
        # 1. Input Completeness
        # -----------------------------------------------------

        completeness = self._check_input_completeness(
            requirement_fact,
            requirement_analysis,
            requirement_gap,
            test_design,
            test_cases,
            validation_result,
        )

        self._add_finding(
            findings,
            completeness,
            "INPUT",
        )

        # -----------------------------------------------------
        # 2. Facts -> Analysis
        # -----------------------------------------------------

        fact_analysis = self._check_fact_analysis(
            requirement_fact,
            requirement_analysis,
        )

        self._add_finding(
            findings,
            fact_analysis,
            "FACT_ANALYSIS",
        )

        # -----------------------------------------------------
        # 3. Analysis -> Gap
        # -----------------------------------------------------

        analysis_gap = self._check_analysis_gap(
            requirement_analysis,
            requirement_gap,
        )

        self._add_finding(
            findings,
            analysis_gap,
            "ANALYSIS_GAP",
        )

        # -----------------------------------------------------
        # 4. Gap -> Test Design
        # -----------------------------------------------------

        gap_design = self._check_gap_design(
            requirement_gap,
            test_design,
        )

        self._add_finding(
            findings,
            gap_design,
            "GAP_DESIGN",
        )

        # -----------------------------------------------------
        # 5. Test Design -> Test Cases
        #
        # 不重新计算 Coverage。
        #
        # 直接读取 Validator Evidence。
        # -----------------------------------------------------

        design_cases = self._check_design_cases(
            test_design,
            test_cases,
            validation_result,
        )

        self._add_finding(
            findings,
            design_cases,
            "DESIGN_CASE",
        )

        # -----------------------------------------------------
        # 6. Requirement Completeness
        # -----------------------------------------------------

        requirement_completeness = (
            self._check_requirement_completeness(
                requirement_fact,
                requirement_analysis,
            )
        )

        self._add_finding(
            findings,
            requirement_completeness,
            "REQUIREMENT_COMPLETENESS",
        )

        # -----------------------------------------------------
        # 7. End-to-End Traceability
        # -----------------------------------------------------

        traceability = self._check_traceability(
            requirement_fact,
            requirement_analysis,
            requirement_gap,
            test_design,
            test_cases,
            validation_result,
        )

        self._add_finding(
            findings,
            traceability,
            "TRACEABILITY",
        )

        # -----------------------------------------------------
        # 8. Validator Evidence
        # -----------------------------------------------------

        validator = self._consume_validator_result(
            validation_result
        )

        self._add_finding(
            findings,
            validator,
            "VALIDATOR",
        )

        # -----------------------------------------------------
        # 9. Final Judgment
        # -----------------------------------------------------

        p0_count = sum(
            1
            for item in findings
            if item.get("severity") == "P0"
        )

        p1_count = sum(
            1
            for item in findings
            if item.get("severity") == "P1"
        )

        if p0_count > 0:

            quality_status = "BLOCK"

        elif p1_count > 0:

            quality_status = "CONDITIONAL"

        else:

            quality_status = "PASS"

        closed_loop = (
            quality_status == "PASS"
        )

        return {
            "schema_version": "1.0",
            "quality_status": quality_status,
            "closed_loop": closed_loop,

            "completeness": {
                "facts": bool(requirement_fact),
                "analysis": bool(requirement_analysis),
                "gaps": bool(requirement_gap),
                "test_design": bool(test_design),
                "test_cases": bool(test_cases),
                "validation": bool(validation_result),
            },

            "traceability": {
                "facts_to_analysis": fact_analysis,
                "analysis_to_gap": analysis_gap,
                "gap_to_test_design": gap_design,
                "test_design_to_test_cases": design_cases,
                "end_to_end": traceability,
            },

            "requirement_completeness":
                requirement_completeness,

            "validator_evidence": validator,

            "findings": findings,

            "summary": {
                "p0_count": p0_count,
                "p1_count": p1_count,
                "total_findings": len(findings),
            },

            "quality_scope": {
                "deterministic": True,
                "uses_llm": False,
                "final_judge": True,
                "generates_test_cases": False,
                "modifies_test_cases": False,
                "revalidates_test_cases": False,
                "recalculates_test_point_coverage": False,
            },
        }

    # =========================================================
    # Input
    # =========================================================

    def _check_input_completeness(
        self,
        facts: Dict[str, Any],
        analysis: Dict[str, Any],
        gaps: Dict[str, Any],
        design: Dict[str, Any],
        cases: Dict[str, Any],
        validation: Dict[str, Any],
    ) -> Dict[str, Any]:

        missing = []

        inputs = {
            "requirement_fact": facts,
            "requirement_analysis": analysis,
            "requirement_gap": gaps,
            "test_design": design,
            "test_cases": cases,
            "validation_result": validation,
        }

        for name, value in inputs.items():

            if not value:
                missing.append(name)

        if missing:

            return self._fail(
                "WORKFLOW_INPUT_INCOMPLETE",
                "Required workflow evidence is missing.",
                "P0",
                missing=missing,
            )

        return self._pass()

    # =========================================================
    # Facts -> Analysis
    # =========================================================

    def _check_fact_analysis(
        self,
        facts: Dict[str, Any],
        analysis: Dict[str, Any],
    ) -> Dict[str, Any]:

        if not facts or not analysis:

            return self._fail(
                "FACT_ANALYSIS_INCOMPLETE",
                "Facts or Analysis is missing.",
                "P0",
            )

        fact_ids = self._collect_ids(
            self._extract_list(
                facts,
                ["facts", "requirement_facts"],
            )
        )

        if not fact_ids:

            return self._fail(
                "FACTS_NO_IDS",
                "Facts do not contain any IDs. "
                "Traceability cannot be established.",
                "P1",
            )

        referenced = self._extract_reference_ids(
            analysis,
            [
                "fact_ids",
                "source_fact_ids",
                "fact_refs",
            ],
        )

        unknown = referenced - fact_ids

        if unknown:

            return self._fail(
                "ANALYSIS_UNKNOWN_FACT",
                "Analysis references unknown Facts.",
                "P1",
                unknown_facts=sorted(unknown),
            )

        if not referenced:

            return self._fail(
                "ANALYSIS_NO_FACT_TRACEABILITY",
                "Analysis does not reference any Fact IDs. "
                "Traceability from Facts to Analysis is missing.",
                "P1",
                fact_count=len(fact_ids),
            )

        return self._pass(
            fact_count=len(fact_ids),
            referenced_count=len(referenced),
        )

    # =========================================================
    # Analysis -> Gap
    # =========================================================

    def _check_analysis_gap(
        self,
        analysis: Dict[str, Any],
        gaps: Dict[str, Any],
    ) -> Dict[str, Any]:

        if not analysis:

            return self._fail(
                "ANALYSIS_MISSING",
                "Requirement Analysis is missing.",
                "P0",
            )

        if not gaps:

            return self._fail(
                "GAP_MISSING",
                "Requirement Gap output is missing.",
                "P0",
            )

        gap_list = self._extract_list(
            gaps,
            ["gaps", "requirement_gaps"],
        )

        if gap_list is None:

            return self._fail(
                "GAP_STRUCTURE_INVALID",
                "Gap output does not contain a valid gaps list.",
                "P0",
            )

        return self._pass(
            gap_count=len(gap_list),
        )

    # =========================================================
    # Gap -> Design
    # =========================================================

    def _check_gap_design(
        self,
        gaps: Dict[str, Any],
        design: Dict[str, Any],
    ) -> Dict[str, Any]:

        if not design:

            return self._fail(
                "TEST_DESIGN_MISSING",
                "Test Design is missing.",
                "P0",
            )

        gap_list = self._extract_list(
            gaps,
            ["gaps", "requirement_gaps"],
        ) or []

        points = self._extract_test_points(
            design
        )

        if not gap_list:

            return self._pass(
                gap_count=0,
                test_point_count=len(points),
            )

        gap_ids = self._collect_ids(
            gap_list
        )

        if not gap_ids:

            return self._fail(
                "GAPS_NO_IDS",
                "Gaps do not contain any IDs. "
                "Traceability cannot be established.",
                "P1",
            )

        referenced_gap_ids: Set[str] = set()

        for point in points:

            referenced_gap_ids.update(
                self._extract_reference_ids(
                    point,
                    [
                        "gap_id",
                        "gap_ids",
                        "source_gap",
                        "source_gap_ids",
                        "requirement_gap_refs",
                    ],
                )
            )

        if not referenced_gap_ids:

            return self._fail(
                "DESIGN_NO_GAP_TRACEABILITY",
                "Test Design does not reference any Gap IDs. "
                "Traceability from Gap to Test Design is missing.",
                "P1",
                gap_count=len(gap_list),
                test_point_count=len(points),
            )

        uncovered = (
            gap_ids - referenced_gap_ids
        )

        if uncovered:

            return self._fail(
                "GAP_NOT_TRACEABLE_TO_DESIGN",
                "Some Requirement Gaps are not traceable to Test Design.",
                "P1",
                uncovered_gaps=sorted(uncovered),
            )

        return self._pass(
            gap_count=len(gap_list),
            test_point_count=len(points),
            explicit_gap_traceability=True,
        )

    # =========================================================
    # Design -> Cases
    # =========================================================

    def _check_design_cases(
        self,
        design: Dict[str, Any],
        cases: Dict[str, Any],
        validation: Dict[str, Any],
    ) -> Dict[str, Any]:

        points = self._extract_test_points(
            design
        )

        case_list = self._extract_test_cases(
            cases
        )

        if not points:

            return self._fail(
                "NO_TEST_POINTS",
                "Test Design contains no Test Points.",
                "P0",
            )

        if not case_list:

            return self._fail(
                "NO_TEST_CASES",
                "No Test Cases were generated.",
                "P0",
            )

        # -----------------------------------------------------
        # 关键：
        # 不重新计算 Coverage。
        # -----------------------------------------------------

        coverage = validation.get(
            "coverage",
            {},
        )

        if coverage.get(
            "coverage_gap"
        ) is True:

            return self._fail(
                "TEST_POINT_COVERAGE_GAP",
                "Validator reports uncovered Test Points.",
                "P0",
                uncovered_test_points=coverage.get(
                    "uncovered_test_points",
                    [],
                ),
            )

        return self._pass(
            test_point_count=len(points),
            test_case_count=len(case_list),
            validator_coverage_consumed=True,
        )

    # =========================================================
    # Requirement Completeness
    # =========================================================

    def _check_requirement_completeness(
        self,
        facts: Dict[str, Any],
        analysis: Dict[str, Any],
    ) -> Dict[str, Any]:

        if not facts or not analysis:

            return self._fail(
                "REQUIREMENT_EVIDENCE_MISSING",
                "Cannot assess requirement completeness.",
                "P0",
            )

        missing_categories = []

        modules = analysis.get(
            "modules",
            [],
        )

        # 只有 Analysis 明确给出对应字段时才检查。
        # 不进行业务脑补。

        category_fields = [
            "business_rules",
            "state_rules",
            "data_rules",
            "time_rules",
            "source_rules",
            "constraints",
        ]

        for module in modules:

            if not isinstance(module, dict):
                continue

            for field in category_fields:

                if field not in module:
                    continue

                value = module.get(field)

                if value is None:

                    missing_categories.append(
                        field
                    )

        if missing_categories:

            return self._fail(
                "REQUIREMENT_CATEGORY_INCOMPLETE",
                "Requirement Analysis contains incomplete rule categories.",
                "P1",
                categories=sorted(
                    set(missing_categories)
                ),
            )

        return self._pass()

    # =========================================================
    # Traceability
    # =========================================================

    def _check_traceability(
        self,
        facts: Dict[str, Any],
        analysis: Dict[str, Any],
        gaps: Dict[str, Any],
        design: Dict[str, Any],
        cases: Dict[str, Any],
        validation: Dict[str, Any],
    ) -> Dict[str, Any]:

        chain = {
            "facts": bool(facts),
            "analysis": bool(analysis),
            "gaps": bool(gaps),
            "test_design": bool(design),
            "test_cases": bool(cases),
            "validation": bool(validation),
        }

        broken = [
            key
            for key, value in chain.items()
            if not value
        ]

        if broken:

            return self._fail(
                "TRACEABILITY_CHAIN_BROKEN",
                "End-to-end QA evidence chain is incomplete.",
                "P0",
                broken_stages=broken,
            )

        return self._pass(
            chain=chain
        )

    # =========================================================
    # Validator Evidence
    # =========================================================

    def _consume_validator_result(
        self,
        validation: Dict[str, Any],
    ) -> Dict[str, Any]:

        status = validation.get(
            "validation_status"
        )

        coverage = validation.get(
            "coverage",
            {},
        )

        p0_count = validation.get(
            "summary",
            {},
        ).get(
            "p0_count",
            0,
        )

        if status == "FAIL":

            return self._fail(
                "TEST_CASE_VALIDATION_FAILED",
                "Test Case Validator reported failures.",
                "P1"
                if not coverage.get("coverage_gap")
                else "P0",
                validation_status=status,
                validator_p0_count=p0_count,
            )

        if coverage.get(
            "coverage_gap"
        ):

            return self._fail(
                "TEST_POINT_COVERAGE_GAP",
                "Validator reports uncovered Test Points.",
                "P0",
                uncovered_test_points=coverage.get(
                    "uncovered_test_points",
                    [],
                ),
            )

        return self._pass(
            validation_status=status,
            coverage_consumed=True,
        )

    # =========================================================
    # Helpers
    # =========================================================

    @staticmethod
    def _extract_list(
        data: Dict[str, Any],
        keys: List[str],
    ) -> List[Any] | None:

        if not isinstance(data, dict):
            return None

        for key in keys:

            value = data.get(key)

            if isinstance(value, list):
                return value

        return None

    @staticmethod
    def _extract_test_points(
        design: Dict[str, Any],
    ) -> List[Dict[str, Any]]:

        direct = design.get(
            "test_points"
        )

        if isinstance(direct, list):
            return [
                x for x in direct
                if isinstance(x, dict)
            ]

        result = []

        for module in design.get(
            "modules",
            [],
        ):

            if not isinstance(module, dict):
                continue

            points = module.get(
                "test_points",
                [],
            )

            if isinstance(points, list):
                result.extend(
                    x for x in points
                    if isinstance(x, dict)
                )

        return result

    @staticmethod
    def _extract_test_cases(
        cases: Dict[str, Any],
    ) -> List[Dict[str, Any]]:

        for key in (
            "test_cases",
            "cases",
        ):

            value = cases.get(key)

            if isinstance(value, list):
                return [
                    x for x in value
                    if isinstance(x, dict)
                ]

        return []

    @staticmethod
    def _collect_ids(
        items: List[Any] | None,
    ) -> Set[str]:

        result = set()

        for item in items or []:

            if not isinstance(item, dict):
                continue

            value = (
                item.get("id")
                or item.get("fact_id")
                or item.get("gap_id")
                or item.get("test_point_id")
            )

            if value:
                result.add(str(value))

        return result

    @staticmethod
    def _extract_reference_ids(
        data: Dict[str, Any],
        keys: List[str],
    ) -> Set[str]:

        result = set()

        for key in keys:

            value = data.get(key)

            if isinstance(value, list):

                for item in value:

                    if isinstance(item, dict):

                        item_id = (
                            item.get("id")
                            or item.get("gap_id")
                            or item.get("fact_id")
                        )

                        if item_id:
                            result.add(
                                str(item_id)
                            )

                    elif item:
                        result.add(str(item))

            elif value:

                result.add(str(value))

        return result

    @staticmethod
    def _pass(
        **details: Any,
    ) -> Dict[str, Any]:

        return {
            "status": "PASS",
            "details": details,
        }

    @staticmethod
    def _fail(
        code: str,
        message: str,
        severity: str,
        **details: Any,
    ) -> Dict[str, Any]:

        return {
            "status": "FAIL",
            "code": code,
            "severity": severity,
            "message": message,
            "details": details,
        }

    @staticmethod
    def _add_finding(
        findings: List[Dict[str, Any]],
        result: Dict[str, Any],
        category: str,
    ) -> None:

        if result.get("status") != "FAIL":
            return

        findings.append(
            {
                "category": category,
                "code": result.get("code"),
                "severity": result.get(
                    "severity",
                    "P1",
                ),
                "message": result.get(
                    "message"
                ),
                "details": result.get(
                    "details",
                    {},
                ),
            }
        )
