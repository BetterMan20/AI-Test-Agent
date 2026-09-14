# -*- coding: utf-8 -*-
"""抓包 API 回放驱动（strategy=api，即 S6 批量回归原语A）。"""
from __future__ import annotations

from pathlib import Path

from core.config import loader
from engine import TestEngine


def run(project: str, env: str, keyword: str | None = None,
        max_count: int = 0, evidence_dir: str | None = None, mode: str = "regression") -> int:
    env_cfg = loader.load_env(project, env)
    proj = loader.load_project(project)

    cap_dir = Path(proj.assets.get("whistle_dir") or f"output/captures/{project}")
    if not cap_dir.exists():
        raise FileNotFoundError(f"抓包目录缺失: {cap_dir}（在 config/projects/{project}.yaml 的 assets.whistle_dir 配置）")

    evidence = Path(evidence_dir) if evidence_dir else Path("output/evidence") / f"{project}-capture-replay"
    evidence.mkdir(parents=True, exist_ok=True)

    engine = TestEngine(
        api_base_url=env_cfg.api_base_url,
        api_headers=env_cfg.api_headers,
        api_timeout=env_cfg.api_timeout,
        evidence_dir=str(evidence),
        adb_device_serial=env_cfg.device_serial,
        capability=None,
        validate_plans=True,
    )

    keywords = [keyword] if keyword else None
    print(f"[{project}/{env}] 回放抓包库: {cap_dir}", flush=True)
    if keywords:
        print(f"  关键词过滤: {keywords}", flush=True)
    result = engine.run_captures_from_dir(cap_dir, keywords=keywords, max_count=max_count)

    cases = getattr(result, "results", []) or []
    passed = sum(1 for c in cases if str(getattr(c, "status", "")).upper() in ("PASS", "PASSED"))
    failed = len(cases) - passed
    print(f"\n✅ 回放完成: 端点={len(cases)} 通过={passed} 失败={failed}")

    engine.close()
    return 0 if failed == 0 else 1