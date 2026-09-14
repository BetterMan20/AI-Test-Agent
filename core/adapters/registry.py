# -*- coding: utf-8 -*-
"""core.adapters.registry — 项目适配器的动态发现与加载。

Core 不 import 任何具体项目模块；这里按「项目配置里声明的模块路径」动态 import，
并按约定取每个适配器包暴露的 `Adapter` 类。换项目只改配置，不改本层与 app。
"""
from __future__ import annotations

import importlib
from typing import Any

from core.config import loader
from core.adapters.base import TTestAdapter


def _module_name(project: str) -> str:
    proj = loader.load_project(project)
    return str(proj.assets.get("adapter_module") or f"projects.{project}.adapters")


def adapter_class(project: str):
    """动态 import 项目适配器包，返回其暴露的 Adapter 类。"""
    mod = importlib.import_module(f"{_module_name(project)}.base")
    cls = getattr(mod, "Adapter", None)
    if cls is None:
        raise ImportError(f"适配器 {_module_name(project)}/base.py 未暴露 Adapter 类")
    return cls


def list_actions(project: str) -> list[str]:
    """返回该项目适配器声明的业务动作清单。"""
    cls = adapter_class(project)
    return list(getattr(cls, "actions", []) or [])


def load_adapter(project: str, env: str | None = None,
                 evidence_dir: str = "", params: dict | None = None) -> TTestAdapter:
    """加载项目适配器实例（注入环境配置 + 证据目录 + 参数）。"""
    proj = loader.load_project(project)
    env_cfg = loader.load_env(project, env or proj.default_env)
    cls = adapter_class(project)
    return cls(project=project, env_cfg=env_cfg,
               evidence_dir=evidence_dir, params=params)