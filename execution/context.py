"""Execution context and environment configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from execution.result import StepResult


@dataclass
class EnvironmentConfig:
    """测试环境配置。"""

    api_base_url: str = ""
    api_headers: dict[str, str] = field(default_factory=dict)
    api_timeout: int = 30

    db_host: str = ""
    db_port: int = 3306
    db_user: str = ""
    db_password: str = ""
    db_name: str = ""

    adb_device_serial: str = ""
    evidence_dir: str = "output/evidence"


class ExecutionContext:
    """单条 TC 执行期间的共享状态。"""

    def __init__(self, environment: EnvironmentConfig, tc_id: str):
        self.environment = environment
        self.tc_id = tc_id
        self._variables: dict[str, Any] = {}
        self._step_results: list[StepResult] = []

    def set_var(self, key: str, value: Any) -> None:
        self._variables[key] = value

    def get_var(self, key: str, default: Any = None) -> Any:
        return self._variables.get(key, default)

    def resolve(self, text: str) -> str:
        """将 ${var} 占位符替换为已存储的变量值。"""
        for key, value in self._variables.items():
            text = text.replace(f"${{{key}}}", str(value))
        return text

    def add_step_result(self, result: StepResult) -> None:
        self._step_results.append(result)

    @property
    def step_results(self) -> list[StepResult]:
        return list(self._step_results)
