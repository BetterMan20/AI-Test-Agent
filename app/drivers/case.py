# -*- coding: utf-8 -*-
"""指定用例执行驱动（strategy=case，运行指定文档级 TC）。"""
from __future__ import annotations

import json
from pathlib import Path

from core.config import loader
from engine import TestEngine


def run(project: str, env: str, case_id: str,
        tc_file: str | None = None, evidence_dir: str | None = None) -> int:
    env_cfg = loader.load_env(project, env)
    proj = loader.load_project(project)

    tc_path = Path(tc_file) if tc_file else proj.assets.get("tc_file", "output/test_cases.json")
    tc_path = Path(tc_path)
    if not tc_path.exists():
        raise FileNotFoundError(f"测试用例文件缺失: {tc_path}")

    evidence = Path(evidence_dir) if evidence_dir else Path("output/evidence") / f"{project}-case"
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

    data = json.loads(tc_path.read_text(encoding="utf-8"))
    cases = data if isinstance(data, list) else data.get("test_cases", data)
    target = next((c for c in cases if str(c.get("id") or c.get("tc_id")) == case_id), None)
    if target is None:
        raise ValueError(f"未找到用例 {case_id}（{tc_path} 内）")

    print(f"[{project}/{env}] 执行用例: {target.get('id')} - {target.get('title','')[:50]}", flush=True)
    result = engine.run_test_case(target)
    print(f"  结果: {result.status}", flush=True)
    engine.close()
    return 0 if str(result.status).upper() in ("PASS", "PASSED") else 1