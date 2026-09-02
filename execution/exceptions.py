"""Execution domain exceptions."""

from __future__ import annotations


class ExecutionError(Exception):
    """Execution domain 基础异常。"""


class PlanningError(ExecutionError):
    """执行计划生成失败。"""


class StepExecutionError(ExecutionError):
    """单个步骤执行失败。"""

    def __init__(
        self, step_id: int, message: str, cause: Exception | None = None
    ):
        self.step_id = step_id
        self.cause = cause
        super().__init__(f"Step {step_id}: {message}")


class ToolError(ExecutionError):
    """工具层（API / DB / ADB）错误。"""

    def __init__(
        self, tool: str, message: str, cause: Exception | None = None
    ):
        self.tool = tool
        self.cause = cause
        super().__init__(f"[{tool}] {message}")


class VerificationError(ExecutionError):
    """结果验证失败。"""
