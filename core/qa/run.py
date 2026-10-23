# -*- coding: utf-8 -*-
"""全景 QA 循环 CLI —— 探索型 AI 测试 Agent 统一入口。

用法:
  python -m core.qa.run --project higo --domain red_packet_claim --room 14775
  python -m core.qa.run --project higo --domain red_packet_claim --room 14775 \
      --live --device emulator-5554          # 真机（前端 overlay 观测 / B 现场执行）
  python -m core.qa.run --project higo --use-llm-attack --use-llm-risk  # LLM 三环增强
  python -m core.qa.run --project higo --real-fact-extraction           # A 真抽取
  python -m core.qa.run --project higo --backfill-evidence \
      output/evidence/higo-repro-bug          # 学习：回填历史复现证据进 KB

流程：认识(S0/KB) → 建模 → 找风险 → 攻击 → 验证 → 回归 → 学习；
产出一个 CycleReport，逐阶段 wired/via/pending，LLM 开关默认全关（确定性）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.qa.cycle import QACycle

OUT_REPORT = Path("output") / "qa"
OUT_REPORT.mkdir(parents=True, exist_ok=True)


def _build_driver(project: str, live: bool, device: str):
    """按项目加载适配层驱动；未实现的诚实返回空驱动（阶段 pending）。"""
    try:
        if project == "higo":
            from projects.higo.adapters.qa_driver import build_driver
            return build_driver(live=live, serial=device or None)
    except Exception as e:  # noqa: BLE001
        print("!! 加载项目驱动失败，回退通用驱动:", e)
    from core.qa.cycle import QADriver
    return QADriver()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="全景 QA 循环（探索型 AI 测试 Agent 入口）")
    p.add_argument("--project", default="higo", help="项目适配名")
    p.add_argument("--env", default="test")
    p.add_argument("--domain", default="red_packet_claim", help="业务域（对应 attack/<domain>.json 与 KB 子树）")
    p.add_argument("--room", default="14775", help="房间/业务实例 id")
    p.add_argument("--kb-base", default="output/app_kb", help="App Knowledge Base 根目录")
    p.add_argument("--model", default=None, help="业务状态/攻击模型 JSON 路径（默认 projects/<project>/attack/<domain>.json）")
    p.add_argument("--historical", default=None, help="历史质量知识 yaml 路径（默认 knowledge/historical.yaml）")

    p.add_argument("--live", action="store_true", help="真机模式（前端 overlay 观测 / B 现场执行）")
    p.add_argument("--device", default="", help="真机 serial（--live 时用）")

    p.add_argument("--use-llm-attack", action="store_true", help="B：LLM 驱动攻击决策 + 可达原语编排")
    p.add_argument("--use-llm-risk", action="store_true", help="C：LLM 历史记忆反推新风险")
    p.add_argument("--real-fact-extraction", action="store_true", help="A：真把 KB system_facts 注入 fact_extraction")

    p.add_argument("--backfill-evidence", default=None,
                   help="学习阶段额外回填的历史证据目录（如 output/evidence/higo-repro-bug）")
    p.add_argument("--out", default=str(OUT_REPORT / "cycle_report.json"))

    a = p.parse_args(argv)

    driver = _build_driver(a.project, a.live, a.device)
    print("== 启动全景 QA 循环 ==")
    print("  project=%s domain=%s room=%s live=%s" % (a.project, a.domain, a.room, a.live))
    print("  LLM开关: attack(B)=%s risk(C)=%s factA=%s" % (
        a.use_llm_attack, a.use_llm_risk, a.real_fact_extraction))

    report = QACycle(
        a.project, a.env, domain=a.domain, room=a.room,
        driver=driver, kb_base=a.kb_base,
        model_path=a.model, historical_path=a.historical,
        use_llm_attack=a.use_llm_attack,
        use_llm_risk=a.use_llm_risk,
        real_fact_extraction=a.real_fact_extraction,
    ).run(backfill_evidence=a.backfill_evidence)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== QA 循环报告 ==")
    for s in report["stages"]:
        pend = (" · " + "; ".join(s["pending"])) if s["pending"] else ""
        print("  [%s] %-8s wired=%-5s via=%-32s%s" % (
            "●" if s["wired"] else "○", s["name"], s["wired"], s["via"], pend))
    print("  输出:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())