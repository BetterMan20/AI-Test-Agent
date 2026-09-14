"""Plan Validator — 检测 LLM 生成的 ExecutionPlan 中的幻觉.

位置: ExecutionPlan → PlanValidator → ExecutionRunner

6 项检查:
  1. API endpoint 是否来自 Capability（防凭空捏造 API）
  2. HTTP method 是否与 Capability 中记录的一致
  3. config 字段是否完整（method/path/headers/body）
  4. assertion 是否来自 TC 的 expected_results（防凭空编造断言）
  5. 是否出现未知 step type
  6. 是否凭空增加 API 步骤（超出 TC steps 数量过多）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from execution.planner import ExecutionPlan, ExecutionStep


@dataclass
class ValidationIssue:
    """单条验证问题。"""

    rule: str
    severity: str  # error | warning
    step_id: int | None
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Plan 验证结果。"""

    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.valid

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [
                {
                    "rule": i.rule,
                    "severity": i.severity,
                    "step_id": i.step_id,
                    "message": i.message,
                    "detail": i.detail,
                }
                for i in self.issues
            ],
            "summary": self.summary,
        }


VALID_STEP_TYPES = {"api", "db", "adb", "manual"}


class PlanValidator:
    """检测 ExecutionPlan 中的 LLM 幻觉."""

    def __init__(
        self,
        capability: Any | None = None,
        max_extra_steps: int = 2,
    ):
        """
        Args:
            capability: APICapability 实例，用于验证 API endpoint
            max_extra_steps: 允许超出 TC steps 数量的最大值（如新增 db 验证步骤）
        """
        self._cap = capability
        self._max_extra = max_extra_steps

    def validate(
        self,
        plan: ExecutionPlan,
        test_case: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """验证 ExecutionPlan.

        Args:
            plan: 待验证的执行计划
            test_case: 原始 TC dict，用于验证 assertion 来源

        Returns:
            ValidationResult
        """
        issues: list[ValidationIssue] = []

        issues.extend(self._check_step_types(plan))
        issues.extend(self._check_config_completeness(plan))

        if self._cap is not None:
            issues.extend(self._check_endpoints_in_capability(plan))
            issues.extend(self._check_methods_match(plan))

        if test_case is not None:
            issues.extend(self._check_assertion_sources(plan, test_case))
            issues.extend(self._check_step_count(plan, test_case))

        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]

        return ValidationResult(
            valid=len(errors) == 0,
            issues=issues,
            summary={
                "errors": len(errors),
                "warnings": len(warnings),
                "total_checks": len(issues),
            },
        )

    # ── 规则 1: 未知 step type ──────────────────────────

    def _check_step_types(self, plan: ExecutionPlan) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for step in plan.steps:
            if step.step_type not in VALID_STEP_TYPES:
                issues.append(ValidationIssue(
                    rule="unknown_step_type",
                    severity="error",
                    step_id=step.step_id,
                    message=f"未知步骤类型: '{step.step_type}'",
                    detail={"valid_types": list(VALID_STEP_TYPES)},
                ))
        return issues

    # ── 规则 2: config 完整性 ───────────────────────────

    def _check_config_completeness(self, plan: ExecutionPlan) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for step in plan.steps:
            if step.step_type == "api":
                issues.extend(self._check_api_config(step))
            elif step.step_type == "db":
                issues.extend(self._check_db_config(step))
            elif step.step_type == "adb":
                issues.extend(self._check_adb_config(step))
        return issues

    @staticmethod
    def _check_api_config(step: ExecutionStep) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        config = step.action
        required = ["method", "path"]

        for field_name in required:
            if field_name not in config or not config[field_name]:
                issues.append(ValidationIssue(
                    rule="config_incomplete",
                    severity="error",
                    step_id=step.step_id,
                    message=f"API 步骤缺少必要字段: '{field_name}'",
                    detail={"missing": field_name},
                ))

        if "method" in config:
            method = config["method"]
            valid_methods = {"GET", "POST", "PUT", "PATCH", "DELETE"}
            if method.upper() not in valid_methods:
                issues.append(ValidationIssue(
                    rule="invalid_method",
                    severity="error",
                    step_id=step.step_id,
                    message=f"无效 HTTP method: '{method}'",
                    detail={"valid": list(valid_methods)},
                ))

        if "path" in config:
            path = config["path"]
            if not path.startswith("/"):
                issues.append(ValidationIssue(
                    rule="invalid_path",
                    severity="error",
                    step_id=step.step_id,
                    message=f"API path 不以 / 开头: '{path}'",
                ))

        if "headers" not in config:
            issues.append(ValidationIssue(
                rule="config_incomplete",
                severity="warning",
                step_id=step.step_id,
                message="API 步骤缺少 headers（将使用默认值）",
            ))

        if "body" not in config:
            issues.append(ValidationIssue(
                rule="config_incomplete",
                severity="warning",
                step_id=step.step_id,
                message="API 步骤缺少 body（将使用空 body）",
            ))

        return issues

    @staticmethod
    def _check_db_config(step: ExecutionStep) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        config = step.action

        if "query" not in config or not config["query"]:
            issues.append(ValidationIssue(
                rule="config_incomplete",
                severity="error",
                step_id=step.step_id,
                message="DB 步骤缺少 query",
                detail={"missing": "query"},
            ))

        if "phase" not in config:
            issues.append(ValidationIssue(
                rule="config_incomplete",
                severity="warning",
                step_id=step.step_id,
                message="DB 步骤缺少 phase（默认 verify）",
            ))

        return issues

    @staticmethod
    def _check_adb_config(step: ExecutionStep) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        config = step.action

        if "command" not in config or not config["command"]:
            issues.append(ValidationIssue(
                rule="config_incomplete",
                severity="error",
                step_id=step.step_id,
                message="ADB 步骤缺少 command",
                detail={"missing": "command"},
            ))

        return issues

    # ── 规则 3: API endpoint 来自 Capability ──────────────

    def _check_endpoints_in_capability(self, plan: ExecutionPlan) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if self._cap is None or len(self._cap) == 0:
            return issues

        known = {ep.endpoint for ep in self._cap.all()}

        for step in plan.steps:
            if step.step_type != "api":
                continue
            path = step.action.get("path", "")
            endpoint = path.split("?")[0]

            if endpoint not in known:
                issues.append(ValidationIssue(
                    rule="unknown_endpoint",
                    severity="error",
                    step_id=step.step_id,
                    message=f"API endpoint 不在 Capability 中: '{endpoint}'",
                    detail={
                        "endpoint": endpoint,
                        "known_count": len(known),
                    },
                ))

        return issues

    # ── 规则 4: HTTP method 匹配 ──────────────────────────

    def _check_methods_match(self, plan: ExecutionPlan) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if self._cap is None:
            return issues

        for step in plan.steps:
            if step.step_type != "api":
                continue
            path = step.action.get("path", "")
            endpoint = path.split("?")[0]

            cap_ep = self._cap.get(endpoint)
            if cap_ep is None:
                continue

            plan_method = step.action.get("method", "").upper()
            cap_method = cap_ep.method.upper()

            if plan_method != cap_method:
                issues.append(ValidationIssue(
                    rule="method_mismatch",
                    severity="error",
                    step_id=step.step_id,
                    message=f"HTTP method 不匹配: Plan={plan_method}, Capability={cap_method}",
                    detail={
                        "endpoint": endpoint,
                        "plan_method": plan_method,
                        "capability_method": cap_method,
                    },
                ))

        return issues

    # ── 规则 5: assertion 来源 ───────────────────────────

    def _check_assertion_sources(
        self, plan: ExecutionPlan, test_case: dict[str, Any]
    ) -> list[ValidationIssue]:
        """检查断言是否来自 TC 的 expected_results."""
        issues: list[ValidationIssue] = []

        expected_results = test_case.get("expected_results", [])
        if not expected_results:
            return issues

        expected_text = " ".join(expected_results).lower()
        expected_keywords = self._extract_keywords(expected_results)

        for step in plan.steps:
            if not step.assertions:
                continue

            for assertion in step.assertions:
                atype = assertion.get("type", "")
                path = assertion.get("path", "")
                expected = assertion.get("expected", "")

                if atype == "json_path":
                    field_name = path.rsplit(".", 1)[-1].replace("$", "").strip()
                    if field_name and field_name.lower() not in expected_keywords:
                        matched = self._fuzzy_match(field_name, expected_text)
                        if not matched:
                            issues.append(ValidationIssue(
                                rule="assertion_not_from_tc",
                                severity="warning",
                                step_id=step.step_id,
                                message=f"断言字段 '{field_name}' 未在 TC expected_results 中找到对应",
                                detail={
                                    "field": field_name,
                                    "json_path": path,
                                    "expected_results": expected_results,
                                },
                            ))

                elif atype == "text_contains":
                    if isinstance(expected, str) and expected.lower() not in expected_text:
                        issues.append(ValidationIssue(
                            rule="assertion_not_from_tc",
                            severity="warning",
                            step_id=step.step_id,
                            message=f"text_contains 值 '{expected}' 未在 expected_results 中找到",
                            detail={"expected": expected},
                        ))

                elif atype == "status_code":
                    pass

        return issues

    # ── 规则 6: 步骤数量 ──────────────────────────────────

    def _check_step_count(
        self, plan: ExecutionPlan, test_case: dict[str, Any]
    ) -> list[ValidationIssue]:
        """检查是否凭空增加过多步骤."""
        issues: list[ValidationIssue] = []

        tc_steps = test_case.get("steps", [])
        tc_count = len(tc_steps)
        plan_count = len(plan.steps)

        if plan_count > tc_count + self._max_extra:
            issues.append(ValidationIssue(
                rule="excess_steps",
                severity="error",
                step_id=None,
                message=f"步骤数量异常: TC={tc_count}, Plan={plan_count}, "
                        f"超出 {plan_count - tc_count} 步（允许 {self._max_extra}）",
                detail={
                    "tc_steps": tc_count,
                    "plan_steps": plan_count,
                    "excess": plan_count - tc_count,
                    "allowed_excess": self._max_extra,
                },
            ))

        return issues

    # ── 工具方法 ──────────────────────────────────────────

    @staticmethod
    def _extract_keywords(expected_results: list[str]) -> set[str]:
        """从 expected_results 提取关键词集合。"""
        keywords: set[str] = set()
        for result in expected_results:
            for word in result.lower().replace("'", " ").replace("-", " ").split():
                if len(word) > 1:
                    keywords.add(word)
        return keywords

    @staticmethod
    def _fuzzy_match(field_name: str, text: str) -> bool:
        """模糊匹配字段名是否在文本中出现。"""
        fn = field_name.lower()
        if fn in text:
            return True
        if len(fn) > 4 and fn[:4] in text:
            return True
        return False
