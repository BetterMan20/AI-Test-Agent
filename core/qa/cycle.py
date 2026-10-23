# -*- coding: utf-8 -*-
"""core.qa.cycle — 全景 QA 循环编排器（认识→建模→找风险→攻击→验证→回归→学习）。

目标：把「会生成测试用例的 AI」变成「会探索 App、并对每个业务跑完整 QA 循环、
让 LLM 拿到越来越完整的系统事实 + 越来越强的执行能力 + 越来越多的历史质量知识」的
AI QA 基础设施。

本编排器是项目无关的壳：
  · 每个阶段接一个阶段驱动（默认由 core 通用引擎实现，业务差异通过 QADriver 注入）；
  · 产出一个 CycleReport，逐阶段标注 wired(已接真实现件) / via(引擎) / pending(待接钩子)；
  · pending 即 LLM 增强三环：A=KB→LLM 系统事实、B=LLM 驱动攻击决策、C=学习闭环记忆。

分层约束：core 不含业务逻辑，具体「怎么探测/怎么执行」由 QADriver（项目适配层）提供。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from core.discovery.knowledge import AppKnowledgeBase
from core.attack.consistency import (
    load_model,
    check_consistency,
    build_attack_tests,
)


# ── 各阶段产物（轻量摘要，供报告展示） ─────────────────────────

@dataclass
class StageResult:
    stage: str                  # recognize/model/risk/attack/verify/regress/learn
    name: str
    wired: bool
    via: str
    artifact: dict = field(default_factory=dict)
    pending: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"stage": self.stage, "name": self.name, "wired": self.wired,
                "via": self.via, "artifact": self.artifact,
                "pending": self.pending}


# 一次状态观测：作为 攻击/验证/回归 的最小数据单元
# {label, status, server_time, open_at, observed_ui, ttl, phase, expected_ui, consistent, violations}
OBSERVATION = dict


# ── 业务驱动协议（由项目适配层实现） ──────────────────────────

class QADriver:
    """项目适配层需提供的接口；未实现的口径即该阶段 pending。"""

    def recognize_facts(self, ctx: "CycleContext") -> list[dict]:
        """认识：产出当前业务可观测的系统事实。默认空。"""
        return []

    def observe(self, ctx: "CycleContext") -> list[OBSERVATION]:
        """攻击/验证：拉取一次实时观测（由适配层决定读真机还是读证据）。"""
        return []

    def reachable_primitives(self, ctx: "CycleContext") -> list[dict]:
        """B: 当前业务真实可执行的原语清单（执行能力上限）。
        [{id, desc, precondition}]；LLM 决策只能从这些原语里编排。"""
        return []

    def execute(self, ctx: "CycleContext", primitives: list[str]) -> dict:
        """B: 按决策给出的原语序列真实执行，回读观测。
        返回 {executed: bool, reason: str, observations: list}；
        原语/设备不可达时诚实返回 executed=False，绝不伪造。"""
        return {"executed": False, "reason": "driver 未实现", "observations": []}

    def backfill(self, ctx: "CycleContext", observations: list[OBSERVATION]) -> list[str]:
        """学习：把观测回填到 App Knowledge Base，返回落库 key。"""
        return []


# ── 循环上下文：贯穿七阶段的累积事实 ──────────────────────────

class CycleContext:
    def __init__(self, project: str, env: str, domain: str, room: str, kb: AppKnowledgeBase):
        self.project = project
        self.env = env
        self.domain = domain
        self.room = room
        self.kb = kb
        self.kb_base = str(kb.base)
        self.model: dict = {}
        self.facts: list[dict] = []          # 系统事实（认识）
        self.system_facts: str = ""          # A: 渲染成 LLM 可注入的 KB 系统事实文本
        self.historical_memory: str = ""      # C: 渲染成 LLM 可注入的历史质量记忆文本
        self.model_ref: str = ""             # 模型来源路径
        self.risks: list[dict] = []          # 找风险
        self.attack_tests: list[dict] = []   # 攻击测试点
        self.attack_outcome: dict = {}       # 攻击执行结果
        self.verdicts: list[dict] = []       # 验证结论
        self.regression: dict = {}           # 回归结果
        self.learned: list[str] = []         # 学习回填 key
        self.historical: list[dict] = []     # 历史质量知识（含本次新增）


# ── 全景编排器 ──────────────────────────────────────────────

class QACycle:
    def __init__(self, project: str, env: str, *, domain: str = "red_packet_claim",
                 room: str = "14775", kb_base: str | Path = "output/app_kb",
                 driver: QADriver | None = None,
                 model_path: str | Path | None = None,
                 historical_path: str | Path | None = None,
                 use_llm_attack: bool = False,
                 use_llm_risk: bool = False,
                 real_fact_extraction: bool = False):
        self.project = project
        self.env = env
        self.domain = domain
        self.room = room
        self.kb = AppKnowledgeBase(base_dir=kb_base, app=project)
        self.driver = driver or QADriver()
        self.use_llm_attack = use_llm_attack   # B: LLM 驱动攻击决策开关
        self.use_llm_risk = use_llm_risk       # C: LLM 历史记忆反推风险开关
        self.real_fact_extraction = real_fact_extraction  # A: 真正把 system_facts 注入 fact_extraction
        # 模型：项目业务状态/攻击模型（如 projects/higo/attack/red_packet_claim.json）
        self.model_path = model_path or Path("projects") / project / "attack" / f"{domain}.json"
        self.historical_path = Path(historical_path or "knowledge/historical.yaml")
        self._stages: list[StageResult] = []

    # ── 阶段驱动别名 ──────────────────────────────────────────
    def _run(self, stage: str, name: str, fn: Callable[[], tuple[bool, str, dict, list[str]]]) -> StageResult:
        wired, via, artifact, pending = fn()
        r = StageResult(stage=stage, name=name, wired=wired, via=via,
                        artifact=artifact, pending=pending)
        self._stages.append(r)
        return r

    # ① 认识：把当前业务能观测到的系统事实汇总
    def recognize(self, ctx: CycleContext) -> StageResult:
        def fn():
            facts = list(self.driver.recognize_facts(ctx))
            ctx.facts = facts or ctx.facts
            # A: 渲染成 LLM 可注入的 system_facts 文本，供 fact_extraction/test_design 消费
            from core.qa.kb_facts import build_system_facts
            sf = build_system_facts(ctx.kb, domain=self.domain, room=self.room)
            ctx.system_facts = sf.block
            llm_extracted = []
            # A 真实消费：把 system_facts 注入 fact_extraction 的 LLM 抽取
            if self.real_fact_extraction:
                from agents.fact_extraction import FactExtraction
                brief = ("基于以下真机已探测系统事实，抽取红包领取业务的结构化事实：\n"
                         + sf.block)
                try:
                    got = FactExtraction().run(parsed=brief, kb_facts=sf.block)
                    llm_extracted = got.get("facts", []) if isinstance(got, dict) else []
                except Exception as e:
                    llm_extracted = []
                    sf = sf  # keep going, 抽取失败不打断循环
                    context = {"err": str(e)}
            artifact = {"fact_count": len(ctx.facts), "kb": ctx.kb_base,
                        "system_facts_nodes": sf.node_count,
                        "system_facts_observed_states": sf.observed_states,
                        "system_facts_block": sf.block[:240] + ("…" if len(sf.block) > 240 else ""),
                        "llm_extracted_facts": len(llm_extracted),
                        "llm_fact_samples": [f for f in llm_extracted[:5]]}
            pending = [] if self.real_fact_extraction else \
                ["A 待真实消费：传 real_fact_extraction=True 让 fact_extraction 真正调入 system_facts"]
            return bool(facts), "S0 discovery + capability" + (" +A真实抽取" if self.real_fact_extraction else ""), \
                artifact, pending
        return self._run("recognize", "认识", fn)

    # ② 建模：状态/业务模型（默认项目 attack/*.json；可升级 LLM 业务模型）
    def model(self, ctx: CycleContext) -> StageResult:
        def fn():
            p = Path(self.model_path)
            if p.exists():
                m = json.loads(p.read_text(encoding="utf-8"))
                ctx.model = m
                ctx.model_ref = str(p)
                pending = ["可选：用 requirement_analysis(LLM) 从需求/探索事实生成业务模型，"
                           "替代/补全手写 attack JSON"]
                artifact = {"state_model": {k: v.get("ui") for k, v in m.get("state_model", {}).items()},
                            "attack_paths": len(m.get("attack_paths", [])),
                            "source": str(p)}
                return True, str(p), artifact, pending
            artifact = {"error": f"模型缺失: {p}"}
            return False, "model-missing", artifact, []
        return self._run("model", "建模", fn)

    # ③ 找风险：模型攻击向量 + 历史 bug + (C) LLM 历史记忆反推
    def risk(self, ctx: CycleContext) -> StageResult:
        def fn():
            # C: 先把历史质量知识渲染成记忆块，供本阶段 LLM 与后续 design 注入
            from core.qa.historical_memory import (
                render_historical_memory, llm_augment_risks)
            ctx.historical_memory = render_historical_memory(ctx.historical, self.domain)

            risks: list[dict] = []
            for ap in ctx.model.get("attack_paths", []):
                risks.append({"id": ap.get("id"), "name": ap.get("name"),
                              "priority": ap.get("priority"), "condition": ap.get("condition"),
                              "expected_anomaly": ctx.model.get("known_anomaly", {}).get("actual_ui")})
            for h in ctx.historical:
                risks.append({"id": f"HIST-{h.get('id')}", "name": h.get("bug_brief", ""),
                              "source": "historical"})
            # C(LLM): 用历史记忆反推新增风险点；失败/未开启时保持规则兜底
            llm_risks: list[dict] = []
            if self.use_llm_risk:
                llm_risks = llm_augment_risks(
                    ctx.model, historical_memory=ctx.historical_memory,
                    existing_risks=risks, use_llm=True)
                risks += llm_risks
            ctx.risks = risks
            artifact = {"risks": len(ctx.risks), "risk": risks[:5],
                        "historical_memory_items": len(ctx.historical),
                        "llm_augmented": len(llm_risks),
                        "historical_memory_block": ctx.historical_memory[:240]}
            pending = ([] if self.use_llm_risk else
                       ["C 未开启：传 use_llm_risk=True 让 LLM 用历史记忆反推新风险点"])
            return bool(risks), f"{len(risks)} risks", artifact, pending
        return self._run("risk", "找风险", fn)

    # ④ 攻击：B 模式下先让 LLM 选路径/定判定边界，再由引擎构造攻击用例并观测验证
    def attack(self, ctx: CycleContext) -> StageResult:
        def fn():
            # B: LLM 决策层（失败自动回退全部可执行路径）
            decision = {"llm_used": False}
            if self.use_llm_attack:
                from core.attack.llm_advisor import decide_attack
                decision = decide_attack(
                    ctx.model,
                    system_facts=ctx.system_facts,
                    historical=ctx.historical,
                    observations=ctx.verdicts,
                    reachable_primitives=self.driver.reachable_primitives(ctx),
                    use_llm=True,
                )
            sel = set(decision.get("selected_paths", []))
            tests = build_attack_tests(ctx.model)
            # 按 LLM 选择过滤/排序；无选择时保留全部
            if sel:
                order = {pid: i for i, pid in enumerate(decision["selected_paths"])}
                chosen = [t for t in tests if t.trigger_id in sel]
                chosen.sort(key=lambda t: order.get(t.trigger_id, 10**9))
            else:
                chosen = tests
            ctx.attack_tests = [t.to_dict() for t in chosen]

            # B(执行闭环)：按决策给出的原语序列真实执行选中路径，回读观测
            exec_results = []
            for pid in decision.get("selected_paths", []):
                prims = (decision.get("per_path", {}).get(pid, {}) or {}).get("primitives", [])
                if not prims:
                    continue
                er = self.driver.execute(ctx, prims)
                er["path"] = pid
                exec_results.append(er)
                for o in er.get("observations", []):
                    ctx.verdicts.append(self._verify_one(ctx, o, label=f"exec:{pid}"))

            obs = self.driver.observe(ctx)
            for o in obs:
                ctx.verdicts.append(self._verify_one(ctx, o, label=o.get("label", "live")))
            # 判定边界：B 可让 LLM 对"无数值观测"给解释性标注，不改变确定性验证结果
            policy = decision.get("verdict_policy", {})
            npolicy = self.use_llm_attack and policy.get("trust_observed_ui_only")
            for v in ctx.verdicts:
                if npolicy and (v.get("phase") in ("UNKNOWN", "NO_LIVE_NUMBERS")) \
                        and not v.get("consistent"):
                    v["llm_deems"] = "无数值观测，按 LLM 策略待后续补充 status/server_time 再定"
            outcome = {"tests": len(ctx.attack_tests),
                       "live_observations": len(obs),
                       "llm_used": decision.get("llm_used"),
                       "llm_source": decision.get("source"),
                       "selected_paths": decision.get("selected_paths", []),
                       "focus_dimensions": decision.get("focus_dimensions", []),
                       "verdict_policy": policy,
                       "dismissed_paths": [p.get("id") for p in ctx.model.get("attack_paths", [])
                                           if sel and p.get("id") not in sel],
                       "execution": exec_results}
            ctx.attack_outcome = outcome
            pending = [] if self.use_llm_attack else ["B 未开启：传 use_llm_attack=True 让 LLM 选路径/定边界"]
            return True, "consistency attack-engine" + (" +LLM决策" if self.use_llm_attack else ""), \
                outcome, pending
        return self._run("attack", "攻击", fn)

    def _verify_one(self, ctx: CycleContext, o: OBSERVATION, label: str) -> dict:
        try:
            v = check_consistency(
                ctx.model, o.get("status"), o.get("server_time"), o.get("open_at"),
                o.get("observed_ui"), ttl=o.get("ttl"))
            base = v.to_dict()
        except Exception as e:  # 缺实时数字等
            base = {"consistent": None, "phase": "NO_LIVE_NUMBERS",
                    "expected_ui": None, "observed_ui": o.get("observed_ui"),
                    "time_agree": None, "violations": [str(e)],
                    "reason": "缺少 status/server_time/open_at 实时值，无法下判定"}
        base["label"] = label
        return base

    # ⑤ 验证：对每次观测判定一致性
    def verify(self, ctx: CycleContext) -> StageResult:
        def fn():
            n = len(ctx.verdicts)
            inconsistent = [v for v in ctx.verdicts if v.get("consistent") is False]
            artifact = {"verdicts": len(ctx.verdicts),
                        "inconsistent": len(inconsistent),
                        "detail": ctx.verdicts}
            return True, "check_consistency", artifact, []
        return self._run("verify", "验证", fn)

    # ⑥ 回归：对历史/攻击观测再跑一遍一致性，比对基线是否新增违例
    def regress(self, ctx: CycleContext) -> StageResult:
        def fn():
            base_bad = sum(1 for v in ctx.verdicts if v.get("consistent") is False)
            ctx.regression = {"relive_count": len(ctx.verdicts),
                              "regression_breaks": base_bad,
                              "note": "当前为一致性回归(relive 同批观测)；完整用例集回归走 batch_regression"}
            pending = ["全量 TC 回归接入 ExecutionPlanner + batch_regression"]
            return True, "consistency-regression", ctx.regression, pending
        return self._run("regress", "回归", fn)

    # ⑦ 学习：观测回填 KB + 追加历史知识
    def learn(self, ctx: CycleContext) -> StageResult:
        def fn():
            if ctx.verdicts:
                obs_payload = [{
                    "label": v.get("label"), "phase": v.get("phase"),
                    "observed_ui": v.get("observed_ui"),
                    "expected_ui": v.get("expected_ui"),
                    "consistent": v.get("consistent"),
                    "violations": v.get("violations"),
                    "business": {"status": ctx.model.get("state_model", {}).get(v.get("phase", ""), {}).get("status")},
                } for v in ctx.verdicts if v.get("phase") in ctx.model.get("state_model", {})]
                if obs_payload:
                    ctx.learned += self.driver.backfill(ctx, obs_payload)
            # 历史知识：把新违例 / 本次域结论追加进 historical
            newly = [v for v in ctx.verdicts if v.get("consistent") is False]
            for v in newly:
                self._append_historical(ctx, v)
            pending = ["C: 把 historical 检索结果作为记忆喂给下一轮 gap_detection/design"]
            return True, "kb backfill + historical append", \
                {"learned_keys": ctx.learned, "historical_total": len(ctx.historical)}, pending
        return self._run("learn", "学习", fn)

    def _append_historical(self, ctx: CycleContext, v: dict) -> None:
        # 按"根因类别+观测形态+房间"去重（不用 phase 推断值），避免同根因拆散/膨胀
        from core.qa.historical_memory import history_key, violation_category
        candidate = {
            "id": 0, "domain": self.domain,
            "bug_brief": f"{self.domain} 一致性违例: {v.get('violations')}",
            "semantics": v.get("phase"),
            "observed_ui": v.get("observed_ui"),
            "expected_ui": v.get("expected_ui"),
            "violations": v.get("violations"),
            "room": self.room,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        key = history_key(candidate)
        if any(history_key(e) == key for e in ctx.historical):
            return  # 同根因违例已在库，避免重复累积
        candidate["id"] = max([e.get("id", 0) for e in ctx.historical] or [0]) + 1
        candidate["violation_category"] = violation_category(candidate["violations"])
        ctx.historical.append(candidate)

    # ── 全景主入口 ──────────────────────────────────────────
    def run(self, *, backfill_evidence: str | Path | None = None) -> dict:
        ctx = CycleContext(self.project, self.env, self.domain, self.room, self.kb)
        ctx.historical = self._load_historical()
        # 认识
        self.recognize(ctx)
        self.model(ctx)
        self.risk(ctx)
        self.attack(ctx)
        self.verify(ctx)
        self.regress(ctx)
        self.learn(ctx)
        self._save_historical(ctx.historical)
        return {
            "domain": self.domain, "room": self.room,
            "model_ref": ctx.model_ref, "kb_base": ctx.kb_base,
            "stages": [s.to_dict() for s in self._stages],
            "history_summary": "六个阶段按序执行，认识→学习闭环打通",
            "kb_tree": ctx.kb.to_tree(),
        }

    def _load_historical(self) -> list[dict]:
        import yaml
        p = Path(self.historical_path)
        if not p.exists():
            return []
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8"))
            return d.get("items", []) if isinstance(d, dict) else []
        except Exception:
            return []

    def _save_historical(self, items: list[dict]) -> None:
        import yaml
        p = Path(self.historical_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump({"items": items}, allow_unicode=True,
                                    sort_keys=False), encoding="utf-8")


def run_qa_cycle(project: str, env: str, *, domain: str = "red_packet_claim",
                 room: str = "14775", driver: QADriver | None = None,
                 backfill_evidence: str | Path | None = None,
                 kb_base: str | Path = "output/app_kb",
                 use_llm_attack: bool = False,
                 use_llm_risk: bool = False,
                 real_fact_extraction: bool = False) -> dict:
    """便捷入口：跑一遍业务全景 QA 循环。"""
    cycle = QACycle(project, env, domain=domain, room=room,
                    driver=driver, kb_base=kb_base,
                    use_llm_attack=use_llm_attack,
                    use_llm_risk=use_llm_risk,
                    real_fact_extraction=real_fact_extraction)
    return cycle.run(backfill_evidence=backfill_evidence)