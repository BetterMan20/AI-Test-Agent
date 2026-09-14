# -*- coding: utf-8 -*-
"""core.config.loader — 统一配置/数据/凭证加载器。

职责边界（严格分离）：
  · 环境配置  → config/environments/<proj>-<env>.yaml   （API 地址 / 设备 / 头部模板）
  · 项目定义  → config/projects/<proj>.yaml              （能力清单 / 数据目录现 / cess资产）
  · 全局默认  → config/global.yaml                        （跨项目通用）
  · 测试数据  → testdata/<proj>/<name>.yaml               （业务数据；.auth 敏感样本 gitignore）
  · 敏感凭证  → .env（HIGO_ZYP / token / sign 等），只经本层注入，绝不出现在代码里。

本层是「代码不含任何项目/环境硬编码」的唯一出入通道。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]  # 项目根

# 敏感凭证（token/sign/mid）只从 .env 读取，本模块入口即加载（不覆盖已有环境变量）
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except Exception:
    pass


# ------------------------------------------------------------------ 结构模型
@dataclass
class EnvConfig:
    project: str
    env: str
    api_base_url: str
    api_timeout: int
    api_headers: dict[str, str]
    device_serial: str
    wake_commands: list[str]
    db: dict[str, Any]


@dataclass
class ProjectConfig:
    name: str
    display: str
    default_env: str
    testdata_dir: Path
    assets: dict[str, Any]
    capabilities: list[dict[str, str]]


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _s(v) -> str:
    return str(v) if v is not None else ""


# ------------------------------------------------------------------ 加载器
def load_env(project: str, env: str) -> EnvConfig:
    g = _load(ROOT / "config" / "global.yaml")
    e = _load(ROOT / "config" / "environments" / f"{project}-{env}.yaml")
    if not e:
        raise FileNotFoundError(
            f"环境配置缺失: config/environments/{project}-{env}.yaml")

    headers = dict((e.get("api", {}) or {}).get("headers", {}) or {})

    # 敏感头部从 .env 注入（绝不写进 yaml / 代码）
    zyp = os.getenv(f"{project.upper()}_ZYP") or os.getenv("ZYP")
    if zyp:
        headers["zyp"] = zyp
    xc = os.getenv(f"{project.upper()}_X_XC_AGENT") or os.getenv("X_XC_AGENT")
    if xc:
        headers["x-xc-agent"] = xc
    xc_agent = os.getenv("X_XC_AGENT")
    if xc_agent and "x-xc-agent" not in headers:
        headers["x-xc-agent"] = xc_agent

    api = e.get("api", {}) or {}
    dev = e.get("device", {}) or {}
    return EnvConfig(
        project=project,
        env=env,
        api_base_url=_s(api.get("base_url")),
        api_timeout=int(api.get("timeout",
                                (g.get("execution", {}) or {}).get("api_timeout", 60))),
        api_headers=headers,
        device_serial=_s(dev.get("serial")),
        wake_commands=list((dev.get("wake_commands") or [])),
        db=dict((e.get("db") or {})),
    )


def load_project(name: str) -> ProjectConfig:
    p = _load(ROOT / "config" / "projects" / f"{name}.yaml")
    if not p:
        raise FileNotFoundError(f"项目配置缺失: config/projects/{name}.yaml")
    return ProjectConfig(
        name=name,
        display=_s(p.get("display", name)),
        default_env=_s(p.get("default_env", "test")),
        testdata_dir=ROOT / _s(p.get("testdata_dir", f"testdata/{name}")),
        assets=dict(p.get("assets", {}) or {}),
        capabilities=list(p.get("capabilities", []) or []),
    )


def list_projects() -> list[str]:
    d = ROOT / "config" / "projects"
    return sorted(p.stem for p in d.glob("*.yaml")) if d.exists() else []


def load_testdata(project: str, name: str) -> dict:
    """加载 testdata/<proj>/<name>.yaml；如存在同名的 .auth 敏感样本则以它覆盖合并。"""
    proj = load_project(project)
    base = proj.testdata_dir / f"{name}.yaml"
    auth = proj.testdata_dir / f"{name}.auth.yaml"
    data = _load(base)
    if auth.exists():
        data.update(_load(auth))
    return data


def available_testdata(project: str) -> list[str]:
    proj = load_project(project)
    return sorted(p.stem.removesuffix(".auth") for p in proj.testdata_dir.glob("*.yaml")) \
        if proj.testdata_dir.exists() else []