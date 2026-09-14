# -*- coding: utf-8 -*-
"""HIGO 抓包回放型能力（项目适配层内实现）。

对任意 HIGO 接口（送礼/进房等），复用 CaptureReplay 从抓包库选一条成功请求，
字节级原样回放（保留原始 body/sign/h_ts），断言“复现抓包时的业务码”，采集四件套证据。

路径以 path_substring 传入（来自 config/projects/higo.yaml 的 assets），本文件不含任何硬编码。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from core.config import loader
from replay.capture_replay import CaptureReplay


def replay_endpoint(project: str, env: str, path_substring: str,
                    action: str, evidence_dir: str | None = None) -> tuple[int, dict]:
    """回放指定接口的最新成功请求，写入 execution_result.json，返回 (rc, summary)。"""
    proj = loader.load_project(project)
    env_cfg = loader.load_env(project, env)
    cap_dir = Path(proj.assets.get("whistle_dir") or f"output/captures/{project}")
    if not cap_dir.exists():
        raise FileNotFoundError(f"抓包目录缺失: {cap_dir}")

    out_root = Path(evidence_dir) if evidence_dir else Path("output/evidence") / f"{project}-{action}"
    out_root.mkdir(parents=True, exist_ok=True)

    replay = CaptureReplay(capture_dir=cap_dir, evidence_root=str(out_root))
    entries = replay.scan(path_substring)
    if not entries:
        print(f"[{action}] 抓包库无该接口样本: {path_substring}")
        return 1, {"status": "BLOCKED", "reason": f"no capture for {path_substring}"}

    entry = replay.pick_successful(entries)
    print(f"[{action}] 回放样本: {entry.endpoint} (抓包 HTTP {entry.status_code})")

    outcome = replay.run(entry, tc_id=f"TC-{action.upper()}", title=action)
    summary = outcome.to_dict()

    # 结果持久化（与红包 E2E 保持同一形态）
    report = {
        "run_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "project": project, "env": env, "action": action,
        "evidence_root": str(out_root),
        "result": summary,
    }
    rep_path = out_root / "execution_result.json"
    rep_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{action}] ret: 抓包={summary['captured']['ret']} 回放={summary['replayed_ret']} "
          f"复现={summary['business_reproduced']} HTTP={summary['replayed']['status_code']}")
    print(f"✅ {action} 汇总已写入: {rep_path}")

    ok = bool(summary.get("passed"))
    return (0 if ok else 1, {"status": "PASS" if ok else "FAIL", "report": str(rep_path),
                             "evidence_root": str(out_root), "reproduced": summary.get("business_reproduced")})