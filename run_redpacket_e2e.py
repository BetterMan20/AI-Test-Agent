# -*- coding: utf-8 -*-
"""HIGO 发红包 E2E —— 已迁移到「通用引擎 + 项目适配器」模型，本文件仅为兼容旧入口的转发层。

真正实现见 projects/higo/adapters/（HigoAdapter），Core 与 app 只经适配器执行业务动作。
推荐新入口（无 HIGO 依赖）：
    python -m app run --project higo --env test --action send_red_packet
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.adapters import registry  # noqa: E402


if __name__ == "__main__":
    project = sys.argv[1] if len(sys.argv) > 1 else "higo"
    env = sys.argv[2] if len(sys.argv) > 2 else "test"
    adapter = registry.load_adapter(project, env=env)
    res = adapter.execute_action("send_red_packet")
    print(f"\n[转发层] send_red_packet -> {res.status}" + (f" ({res.error})" if res.error else ""))
    raise SystemExit(0 if res.ok else 1)