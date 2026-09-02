"""Rule-based verifier — concrete assertion checks for execution outputs."""

from __future__ import annotations

import re
from typing import Any


class RuleVerifier:
    """对执行输出做规则级断言检查。"""

    @staticmethod
    def verify_status_code(actual: int, expected: int) -> bool:
        return actual == expected

    @staticmethod
    def verify_json_path(
        body: Any, json_path: str, expected: Any
    ) -> bool:
        value = RuleVerifier._extract_json_path(body, json_path)
        return value == expected

    @staticmethod
    def verify_text_contains(text: str, substring: str) -> bool:
        return substring in text

    @staticmethod
    def verify_regex(text: str, pattern: str) -> bool:
        return re.search(pattern, text) is not None

    @staticmethod
    def verify_count(
        actual: int, expected: int, operator: str = "=="
    ) -> bool:
        ops = {
            "==": lambda a, e: a == e,
            ">=": lambda a, e: a >= e,
            "<=": lambda a, e: a <= e,
            ">": lambda a, e: a > e,
            "<": lambda a, e: a < e,
            "!=": lambda a, e: a != e,
        }
        return ops.get(operator, lambda a, e: False)(actual, expected)

    @staticmethod
    def verify_db_rows(rows: list[dict[str, Any]], expected: Any) -> bool:
        if isinstance(expected, int):
            return len(rows) == expected
        if isinstance(expected, list) and expected:
            return len(rows) > 0
        return len(rows) > 0

    @staticmethod
    def _extract_json_path(data: Any, path: str) -> Any:
        if path.startswith("$."):
            path = path[2:]
        for part in path.split("."):
            if isinstance(data, dict):
                data = data.get(part)
            elif isinstance(data, list) and part.isdigit():
                idx = int(part)
                data = data[idx] if idx < len(data) else None
            else:
                return None
        return data

    @classmethod
    def check(cls, assertion: dict[str, Any], actual_output: Any) -> bool:
        """根据 assertion dict 中的 type 字段分派到具体检查方法。"""
        atype = assertion.get("type")
        expected = assertion.get("expected")

        if atype == "status_code":
            return cls.verify_status_code(actual_output, expected)
        if atype == "json_path":
            return cls.verify_json_path(
                actual_output, assertion.get("path", "$"), expected
            )
        if atype == "text_contains":
            return cls.verify_text_contains(
                str(actual_output), str(expected)
            )
        if atype == "regex":
            return cls.verify_regex(
                str(actual_output), assertion.get("pattern", "")
            )
        if atype == "count":
            return cls.verify_count(
                actual_output, expected, assertion.get("operator", "==")
            )
        if atype == "db_rows":
            return cls.verify_db_rows(actual_output, expected)
        return False
