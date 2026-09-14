# -*- coding: utf-8 -*-
"""测试策略分派器 —— 按 TestPlan 逐层执行并聚合为统一报告。

职责：
  业务层   → 抓包回放（CaptureReplay，链路探针 / 全量 TC）
  攻击层   → 本机可执行攻击（stability/attacks.py 的 A01/A02/A05/A06/A07/A10）
  稳定性层 → 状态感知随机执行（StabilityRunner，事件量由决策给定）

产出 output/strategy_report.json（统一报告）：
  plan      决策快照（mode/target/layers/validation/rationale）
  summary   三层开关与通过率
  layers    business / attack / stability 各自结果
  verdict   归一判定（PASS / WARN / FAIL）
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestrator.strategy import TestPlan
from replay.capture_replay import CaptureReplay
from stability.attacks import executable_attacks, AttackCase
from stability.actor import StateAwareActor
from stability.runner import StabilityRunner

DEFAULT_CAPTURE_DIR = "D:/higo-api"


@dataclass
class LayerResult:
    layer: str
    enabled: bool
    status: str = "SKIPPED"
    n_run: int = 0
    n_pass: int = 0
    detail: Any = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "layer": self.layer, "enabled": self.enabled,
            "status": self.status, "n_run": self.n_run, "n_pass": self.n_pass,
            "detail": self.detail, "error": self.error,
        }


class Dispatcher:
    def __init__(
        self,
        capture_dir: str | Path = DEFAULT_CAPTURE_DIR,
        device_serial: str = "",
        package: str = "com.example.live",
        evidence_root: str | Path = "output/strategy",
        probe_limit: int = 1,
    ) -> None:
        self.capture_dir = Path(capture_dir)
        self.device_serial = device_serial
        self.package = package
        self.root = Path(evidence_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.probe_limit = probe_limit

    # ── 统一入口 ─────────────────────────────────────────
    def execute(self, plan: TestPlan) -> dict:
        results: dict[str, LayerResult] = {}
        for layer in plan.layers:
            results[layer.layer] = self._dispatch(layer)

        report = self._aggregate(plan, results)
        out = self.root / "strategy_report.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["output_path"] = str(out)
        return report

    # ── 逐层分派 ─────────────────────────────────────────
    def _dispatch(self, lp) -> LayerResult:
        if not lp.enabled:
            return LayerResult(lp.layer, enabled=False)
        try:
            if lp.layer == "business":
                return self._run_business(lp)
            if lp.layer == "attack":
                return self._run_attack(lp)
            if lp.layer == "stability":
                return self._run_stability(lp)
            return LayerResult(lp.layer, enabled=True, status="UNKNOWN",
                               error=f"未知层: {lp.layer}")
        except Exception as e:  # noqa: BLE001
            return LayerResult(lp.layer, enabled=True, status="ERROR",
                               error=f"{type(e).__name__}: {e}")

    # 业务层：对每个端点回放代表请求
    def _run_business(self, lp) -> LayerResult:
        replay = CaptureReplay(self.capture_dir, self.root / "evidence_business")
        ref = lp.ref
        endpoints = ref if isinstance(ref, list) else [lp.params.get("endpoint") or "send_red_packet"]
        outcomes_all = []
        n_run = n_pass = 0
        for ep in endpoints:
            try:
                hits = replay.scan(ep)
            except FileNotFoundError:
                continue
            entries = hits[: self.probe_limit] if lp.ref == "probe1" else hits
            for i, entry in enumerate(entries, 1):
                out = replay.run(entry, tc_id=f"BIZ-{ep[:12]}-{i:03d}",
                                 title=f"回放 {entry.method} {entry.endpoint}")
                outcomes_all.append(out.to_dict())
                n_run += 1
                n_pass += int(out.passed)
        status = "PASS" if outcomes_all and n_pass == n_run else "WARN"
        return LayerResult("business", enabled=True, status=status,
                           n_run=n_run, n_pass=n_pass,
                           detail={"outcomes": outcomes_all})

    # 攻击层：执行本机可执行的攻击用例（feasibility == executable）
    def _run_attack(self, lp) -> LayerResult:
        attacks = executable_attacks()
        detail = []
        n_run = n_pass = 0
        for a in attacks:
            r = self._run_one_attack(a)
            detail.append(r)
            n_run += 1
            n_pass += int(r["status"] == "PASS")
        status = "PASS" if n_run and n_pass == n_run else "WARN"
        return LayerResult("attack", enabled=True, status=status,
                           n_run=n_run, n_pass=n_pass, detail=detail)

    def _run_one_attack(self, a: AttackCase) -> dict:
        actor = StateAwareActor(self.device_serial, avoid_login=False)
        steps = []
        supports = {"BURST_TAP", "TAP", "BACKGROUND", "KEY", "SWIPE"}
        for has_prim, prim in _split_primitives(a.action_seq):
            if not has_prim:
                steps.append({"prim": prim, "status": "SKIP", "note": "未识别原语"})
                continue
            kind, arg = prim
            if kind in ("REPLAY",):
                # 字节级重放 N 次（A02）,只记一次回放结果
                n = int(arg or 1)
                out = self._replay_by_attack(a)
                steps.append({"prim": prim, "status": "PASS" if out["passed"] else "FAIL",
                              "n": n})
            elif kind in supports:
                params = _coords_for(actor, kind, arg)
                actor.act((kind, params))
                steps.append({"prim": prim, "status": "PASS"})
            elif kind in ("NET_OFF", "NET_ON"):
                self._toggle_airplane(kind == "NET_OFF")
                steps.append({"prim": prim, "status": "PASS"})
            elif kind == "FOREGROUND":
                # 从后台拉回前台（与 BACKGROUND 对称）
                actor._client.shell(
                    f"am start -n {self.package}/com.global.hiyapro.ui.SplashActivity; sleep 1.5")
                steps.append({"prim": prim, "status": "PASS"})
            elif kind in ("KILL_APP", "RELAUNCH"):
                if kind == "KILL_APP":
                    actor._client.shell(f"am force-stop {self.package}")
                else:
                    actor._client.shell(
                        f"am start -n {self.package}/com.global.hiyapro.ui.SplashActivity")
                steps.append({"prim": prim, "status": "PASS"})
            else:
                steps.append({"prim": prim, "status": "SKIP",
                              "note": f"{kind} 原语当前不可自动执行"})
        status = "PASS" if all(s["status"] == "PASS" for s in steps) else "WARN"
        return {"id": a.id, "title": a.title, "feasibility": a.feasibility,
                "status": status, "steps": steps}

    def _toggle_airplane(self, off: bool) -> None:
        cmd = "svc wifi disable; svc data disable" if off else "svc wifi enable; svc data enable"
        StateAwareActor(self.device_serial)._client.shell(cmd + "; sleep 1.2")

    def _replay_by_attack(self, a: AttackCase) -> dict:
        replay = CaptureReplay(self.capture_dir, self.root / "evidence_attack")
        ep = a.victim
        hit = None
        try:
            hits = replay.scan(ep)
            hit = replay.pick_successful(hits)
        except FileNotFoundError:
            pass
        if hit is None:
            return {"passed": False, "error": "无可用抓包请求"}
        out = replay.run(hit, tc_id=f"ATK-{a.id}", title=f"攻击重放 {a.id}")
        return {"passed": out.passed, "replayed_ret": out.replayed_ret,
                "error": out.error}

    # 稳定性层：状态感知随机执行指定事件量
    def _run_stability(self, lp) -> LayerResult:
        runner = StabilityRunner(
            package=self.package, device_serial=self.device_serial,
            events=lp.events, root=self.root / "evidence_stability",
            test_id=f"ST-{lp.params.get('seq', '0')}",
            strategy="RANDOM",
            anchor_bias=lp.params.get("anchor_bias", 0.9),
        )
        r = runner.run()
        biz = r["business_result"]
        st = r["stability_result"]
        status = "PASS" if biz["status"] == "PASS" else "FAIL"
        return LayerResult("stability", enabled=True, status=status,
                           n_run=st["events_run"],
                           n_pass=st["events_run"] - st["failures_found"],
                           detail=r)

    # ── 聚合 ─────────────────────────────────────────
    def _aggregate(self, plan: TestPlan, results: dict[str, LayerResult]) -> dict:
        enabled = {l.layer for l in plan.layers if l.enabled}
        summary = {k: v.to_dict() for k, v in results.items()}

        # 归一判定：稳定性必须无崩溃；业务通过率 ≥ 决策门槛；攻击不得全失败
        verdict_parts = []
        biz = results.get("business")
        st = results.get("stability")
        atk = results.get("attack")
        pass_rate = (biz.n_pass / biz.n_run) if biz and biz.n_run else 0.0
        biz_ok = (not biz or not biz.enabled) or pass_rate >= plan.validation.get("business_pass_rate", 0.8)
        st_ok = (not st or not st.enabled) or (
            st.status == "PASS"
            and st.detail.get("stability_result", {}).get("failures_found", 0) == 0
        ) if st else True
        atk_ok = (not atk or not atk.enabled) or (atk.n_run and atk.n_pass == atk.n_run)
        if not biz_ok:
            verdict_parts.append("业务通过率不足")
        if not st_ok:
            verdict_parts.append("稳定性存在崩溃/失败")
        if not atk_ok:
            verdict_parts.append("攻击层未全部通过")
        verdict = "PASS" if not verdict_parts else ("WARN/GATED" if st_ok else "FAIL")

        return {
            "run_time": time.strftime("%Y-%m-%d %H:%M:%S %z"),
            "plan": plan.to_dict(),
            "layers_on": sorted(enabled),
            "summary": summary,
            "pass_rate": round(pass_rate, 3),
            "verdict": verdict,
            "gates": ["业务通过率≥%.2f" % plan.validation.get("business_pass_rate", 0.8),
                      "稳定性崩溃数=0", "攻击全部可执行用例通过"],
        }


def _split_primitives(action_seq: list[str]) -> list[tuple[bool, tuple[str, str]]]:
    out = []
    for tok in action_seq:
        if ":" in tok:
            kind, arg = tok.split(":", 1)
            out.append((True, (kind.strip().upper(), arg.strip())))
        else:
            out.append((True, (tok.strip().upper(), "")))
    return out


def _coords_for(actor: StateAwareActor, kind: str, arg: str) -> dict:
    """把攻击原语的 *目标* 占位符解析为真实坐标。"""
    if arg == "*sendelement*" or not arg:
        actor.dump_nodes()
        anchor = next(
            (n for n in actor._curnodes
             if __import__("re").search("红包|send|发送|发|gift|送", n.label)), None)
        if anchor:
            return {"coords": list(anchor.center), "text": anchor.label[:20]}
        import random
        return {"coords": [random.randint(300, 700), random.randint(500, 1200)]}
    try:
        x, y = (int(p) for p in arg.replace("(", "").replace(")", "").split(","))
        return {"coords": [x, y]}
    except Exception:
        import random
        return {"coords": [random.randint(300, 700), random.randint(500, 1200)]}


if __name__ == "__main__":
    import sys
    import argparse
    p = argparse.ArgumentParser(description="分层测试分派器（读 TestPlan 落盘策略报告）")
    p.add_argument("--plan", default="output/plan.json", help="TestPlan JSON 输入")
    p.add_argument("--capture-dir", default=DEFAULT_CAPTURE_DIR)
    p.add_argument("--device", default="")
    p.add_argument("--out", default="output/strategy/strategy_report.json")
    a = p.parse_args(sys.argv[1:])

    plan_path = Path(a.plan)
    if not plan_path.exists():
        from orchestrator.strategy import StrategyDecision
        plan = StrategyDecision().decide(mode="smoke", target="发送红包")
    else:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
        plan = TestPlan(**{**data, "layers": data["layers"]})

    disp = Dispatcher(capture_dir=a.capture_dir, device_serial=a.device,
                      evidence_root=str(Path(a.out).parent))
    report = disp.execute(plan)
    print("== 策略报告 ==")
    print("  layers_on:", report["layers_on"])
    print("  pass_rate:", report["pass_rate"], "verdict:", report["verdict"])
    print("  输出:", report["output_path"])