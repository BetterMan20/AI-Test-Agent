# -*- coding: utf-8 -*-
"""随机稳定性驱动（strategy=random，状态感知随机事件 + Crash/ANR 监控）。"""
from __future__ import annotations

from pathlib import Path

from core.config import loader
from stability.runner import StabilityRunner


def run(project: str, env: str, events: int = 100000,
        evidence_dir: str | None = None) -> int:
    env_cfg = loader.load_env(project, env)
    proj = loader.load_project(project)

    device_serial = env_cfg.device_serial
    package = str(proj.assets.get("app_package") or "com.example.live")

    root = Path(evidence_dir) if evidence_dir else Path("output/evidence") / f"{project}-stability"
    root.mkdir(parents=True, exist_ok=True)

    runner = StabilityRunner(
        package=package,
        device_serial=device_serial,
        events=int(events),
        root=str(root),
        test_id=f"{project.upper()}-ST-{env.upper()}",
        strategy="RANDOM",
    )

    print(f"[{project}/{env}] 随机稳定性: package={package} device={device_serial} "
          f"events={events}", flush=True)
    result = runner.run()
    print(f"\n✅ 稳定性运行完成: {getattr(result, 'summary', result)}")
    return 0