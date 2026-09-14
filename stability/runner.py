# -*- coding: utf-8 -*-
"""稳定性/随机执行编排器 —— 产出升级版 execution_result.json。

schema（对应「测试策略决策器」产物）：
  test_id / strategy(RANDOM|REPLAY|ATTACK) / protocol_result / business_result
  / stability_result / evidence / reproducible

转圈主循环：
  dump状态 → 状态感知选动作 → 下发 → 记录事件 → 周期 poll CrashMonitor
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any, Optional

from stability.actor import StateAwareActor
from stability.monitor import CrashMonitor
from stability.recorder import EventRecorder


class StabilityRunner:
    def __init__(
        self,
        package: str = "com.example.live",
        device_serial: str = "",
        events: int = 300,
        root: str | Path = "output/evidence_stability",
        test_id: str = "ST-001",
        strategy: str = "RANDOM",
        anchor_bias: float = 0.9,
        avoid_login: bool = True,
        poll_every: int = 40,
        seed: Optional[int] = None,
    ) -> None:
        if seed is not None:
            random.seed(seed)
        self.package = package
        self.events = events
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.test_id = test_id
        self.strategy = strategy
        self.anchor_bias = anchor_bias
        self.avoid_login = avoid_login
        self.poll_every = poll_every

        self._recorder = EventRecorder(self.root / "events.jsonl")
        self._monitor = CrashMonitor(package, device_serial, root)
        self._actor = StateAwareActor(
            device_serial, anchor_bias=anchor_bias, avoid_login=avoid_login,
        )

    def run(self) -> dict[str, Any]:
        failures: list[dict[str, Any]] = []
        t0 = time.time()
        for i in range(1, self.events + 1):
            action = self._actor.choose()
            kind, params = action
            try:
                self._actor.act(action)
                result = "ok"
            except Exception as e:  # noqa: BLE001
                result = "exception:" + type(e).__name__
            state = self._actor._curnodes and \
                ",".join(n.label[:8] for n in self._actor._curnodes[:3]) or "empty"
            self._recorder.record(kind, params, state=state, result=result)

            if i % self.poll_every == 0:
                tail = self._recorder.export_sequence(60)
                f = self._monitor.poll(i, tail)
                if f:
                    failures.append(f.to_dict())
                    # 命中崩溃：记录当前事件序列供 shrinking
                    self._recorder.record("CRASH", {"seq": i}, state=state,
                                          result="found", note=f.kind)

        duration = round(time.time() - t0, 2)
        self._recorder.close()

        report = self._build_result(failures, duration)
        out = self.root / "execution_result.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["output_path"] = str(out)
        return report

    def _build_result(self, failures: list[dict], duration: float) -> dict[str, Any]:
        # 稳定性结论：任一 crash/anr 视为稳定性失败
        any_fail = len(failures) > 0
        kinds = [f["kind"] for f in failures]
        stability = {
            "crash": any_fail and "crash" in kinds,
            "anr": "anr" in kinds,
            "force_close": "force_close" in kinds,
            "freeze": "freeze" in kinds,
            "failures": failures[:5],
            "events_run": self.events,
            "failures_found": len(failures),
            "first_failure_seq": failures[0]["seq"] if failures else None,
        }
        seq0 = stability["first_failure_seq"]
        report = {
            "test_id": self.test_id,
            "strategy": self.strategy,
            "protocol_result": {
                "status": "PASS",
                "http_status": None,
                "note": "随机/稳定性测试无单接口协议断言",
            },
            "business_result": {
                "status": "FAIL" if any_fail else "PASS",
                "ret": None,
                "reason": (failures[0]["kind"] if failures else "ok"),
            },
            "stability_result": stability,
            "evidence": {
                "events": str(self.root / "events.jsonl"),
                "logcat": str(self.root / f"crash_seq{seq0}.log") if seq0 else "",
                "screenshot": str(self._monitor.root / f"shot_seq{seq0}.png") if seq0 else "",
            },
            "reproducible": True,
            "duration_s": duration,
        }
        return report


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="HIGO 稳定性随机执行（状态感知随机 + Crash/ANR 监控）")
    p.add_argument("--package", default="com.example.live")
    p.add_argument("--events", type=int, default=300,
                   help="随机事件数（冒烟用小值；正式回归可到 100000）")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--strategy", default="RANDOM", choices=["RANDOM", "ATTACK", "REPLAY"])
    p.add_argument("--test-id", default="ST-001")
    p.add_argument("--anchor-bias", type=float, default=0.9)
    p.add_argument("--avoid-login", action="store_true", default=True)
    a = p.parse_args(argv)

    runner = StabilityRunner(
        package=a.package, events=a.events, seed=a.seed,
        strategy=a.strategy, test_id=a.test_id,
        anchor_bias=a.anchor_bias, avoid_login=a.avoid_login,
    )
    r = runner.run()
    print("== 稳定性执行 ==")
    print("  test_id=%s strategy=%s events=%d duration=%.1fs" % (
        r["test_id"], r["strategy"], r["stability_result"]["events_run"], r["duration_s"]))
    print("  稳定性: crash=%s anr=%s force_close=%s freeze=%s | 失败=%d" % (
        r["stability_result"]["crash"], r["stability_result"]["anr"],
        r["stability_result"]["force_close"], r["stability_result"]["freeze"],
        r["stability_result"]["failures_found"]))
    biz = r["business_result"]
    print("  业务结果: %s (reason=%s)" % (biz["status"], biz["reason"]))
    print("  输出:", r["output_path"])
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())