# -*- coding: utf-8 -*-
"""抓包回放（Capture Replay）固化模块。

把 D:\higo-api 的 whistle 抓包可视化出来：按目标接口路径扫描 → 选出真实成功请求 →
字节级原样回放（保留原始 body/sign/h_ts，sign 按原始字节计算）→ 采集规范四件套证据 →
断言“复现抓包时的业务码”。

核心理念：
- 原样回放：sign 通常按 h_ts+token+body 的原始字节计算，任何重排都会导致 sign 失配。
  因此回放一律使用 CapturedAPI.req_body_raw（原始字符串）通过 data= 发送，
  而不是用解析后的 dict 重序列化。
- 成功码不硬编码：不同接口 success ret 不同（本接口 ret=1 表示成功），
  用 CapturedAPI.is_success 做保守启发式，并断言“复现抓包时的业务码”。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Callable

from tools.api.client import APIClient
from tools.whistle_parser import CapturedAPI, WhistleParser
from evidence.collector import EvidenceCollector
from evidence.store import EvidenceStore


@dataclass
class ReplayOutcome:
    """一次回放的结果。"""

    tc_id: str
    entry: CapturedAPI
    status_code: int | None
    body: Any
    passed: bool
    captured_ret: Any
    replayed_ret: Any
    reproduced: bool
    evidence: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tc_id": self.tc_id,
            "endpoint": self.entry.endpoint,
            "replayed": {
                "method": self.entry.method,
                "url": self.entry.path_with_query,
                "status_code": self.status_code,
            },
            "captured": {
                "status_code": self.entry.status_code,
                "ret": self.captured_ret,
                "data_status": self.entry.res_data_status,
                "success": self.entry.is_success,
            },
            "replayed_ret": self.replayed_ret,
            "business_reproduced": self.reproduced,
            "passed": self.passed,
            "evidence": self.evidence,
            "error": self.error,
        }


class CaptureReplay:
    """从 whistle 抓包目录扫描、选择并回放指定接口。"""

    def __init__(
        self,
        capture_dir: str | Path,
        evidence_root: str | Path | None = None,
    ):
        self.capture_dir = Path(capture_dir)
        evidence_root = evidence_root or Path.cwd() / "output" / "evidence_capture_replay"
        self._store = EvidenceStore(base_dir=str(evidence_root))
        self._collector = EvidenceCollector(self._store)

    def scan(
        self,
        path_substring: str,
        keyword: str | None = None,
        overwrite_domain: str | None = None,
    ) -> list[CapturedAPI]:
        """扫描抓包目录里包含 path_substring 的接口调用，按时间正序。"""
        _kw = [path_substring]
        if keyword:
            _kw.append(keyword)
        grouped = WhistleParser.find_endpoints(self.capture_dir, keywords=_kw)
        hits: list[CapturedAPI] = []
        for ep, entries in grouped.items():
            if path_substring.lower() not in ep.lower():
                continue
            hits.extend(entries)
        hits.sort(key=lambda e: e.timestamp or 0)
        return hits

    @staticmethod
    def pick_successful(
        entries: Iterable[CapturedAPI],
        predicate: Callable[[CapturedAPI], bool] | None = None,
        prefer_success: bool = True,
    ) -> CapturedAPI | None:
        """选一条适合回放的请求：默认优先成功、失败中选时间最新（便于归因），最后取时间最新。"""
        entries = list(entries)
        if not entries:
            return None
        if predicate is None:
            predicate = lambda e: e.is_success
        if prefer_success:
            ok = [e for e in entries if predicate(e)]
            if ok:
                return ok[-1]  # 最新一条成功请求
        return entries[-1]  # 无成功则取最新，诚实复现当前行为

    def run(
        self,
        entry: CapturedAPI,
        tc_id: str,
        title: str,
        base_url: str | None = None,
        include_meta: bool = True,
    ) -> ReplayOutcome:
        """字节级原样回放一条抓包请求，采集证据并断言“复现抓包业务码”。"""
        url_base = base_url or entry.base_url
        client = APIClient(base_url=url_base, timeout=60)

        request_config = {
            "method": entry.method,
            "path": entry.path_with_query,
            "headers": entry.req_headers,
            "params": entry.query_params,
            "body": entry.req_body_raw or entry.req_body,  # 证据里记录原始 body
        }

        started = time.perf_counter()
        error = None
        resp = None
        try:
            # data= 原始字符串：sign 按原始 body 字节计算，缺一不可
            resp = client.request(
                method=entry.method,
                path=entry.endpoint,
                headers=entry.req_headers,
                data=entry.req_body_raw,
                params=entry.query_params,
            )
        except Exception as e:  # noqa: BLE001
            error = f"{type(e).__name__}: {e}"
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            client.close()

        # 收集证据（即便请求异常也落盘，便于排查）
        meta = {
            "duration_ms": duration_ms,
            "status": "error" if error else str(getattr(resp, "status_code", "")),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        }
        legacy_status = {
            "status_code": getattr(resp, "status_code", None) if resp else None,
            "has_error": bool(error),
        }
        meta.update(legacy_status)
        evidence = self._collector.collect_api_evidence(
            request_config=request_config,
            response=resp if resp is not None else type("R", (), {"status_code": None, "text": "", "headers": {}, "json": lambda: None}),
            tc_id=tc_id,
            step_id=1,
            execution_meta=meta,
        )
        ev_paths = [e.path for e in evidence]

        # 业务码复现判定（不硬编码成功码）
        replayed_ret = None
        body_val: Any = None
        if resp is not None:
            try:
                body_val = resp.json()
            except Exception:
                body_val = resp.text
            if isinstance(body_val, dict):
                replayed_ret = body_val.get("ret")
        reproduced = (
            resp is not None
            and error is None
            and replayed_ret == entry.res_ret
        )
        passed = reproduced and resp is not None and resp.status_code < 400

        return ReplayOutcome(
            tc_id=tc_id,
            entry=entry,
            status_code=getattr(resp, "status_code", None) if resp else None,
            body=body_val,
            passed=passed,
            captured_ret=entry.res_ret,
            replayed_ret=replayed_ret,
            reproduced=reproduced,
            evidence=ev_paths,
            error=error,
        )

    def save_summary(self, outcomes: list[ReplayOutcome], filename: str = "capture_replay_result.json") -> Path:
        path = self._store.base_dir / filename
        Path(path).write_text(
            json.dumps(
                {
                    "capture_dir": str(self.capture_dir),
                    "run_time": time.strftime("%Y-%m-%d %H:%M:%S %z"),
                    "outcomes": [o.to_dict() for o in outcomes],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path


def run_capture_replay(
    capture_dir: str | Path,
    path_substring: str,
    evidence_root: str | Path | None = None,
    base_url: str | None = None,
    tc_prefix: str = "TC-CAP",
    predicate: Callable[[CapturedAPI], bool] | None = None,
    prefer_success: bool = True,
) -> tuple[list[ReplayOutcome], Path, list[CapturedAPI]]:
    """一键跑通：扫描 → 选请求 → 回放全部候选（或只回放选中的一条）。

    默认会回放【所有匹配的候选请求】以观察行为变化；用 prefer_success / predicate 控制。
    """
    replay = CaptureReplay(capture_dir, evidence_root)
    hits = replay.scan(path_substring)
    if not hits:
        raise FileNotFoundError(f"抓包目录中未找到包含 '{path_substring}' 的请求")

    targets = [replay.pick_successful(hits, predicate, prefer_success)]
    outcomes = []
    for i, entry in enumerate(targets, 1):
        tc_id = f"{tc_prefix}-{i:03d}"
        out = replay.run(
            entry,
            tc_id=tc_id,
            title=f"回放 {entry.method} {entry.endpoint}",
            base_url=base_url,
        )
        outcomes.append(out)
    summary = replay.save_summary(outcomes)
    return outcomes, summary, hits


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if len(args) < 2:
        print("用法: python -m replay.capture_replay <capture_dir> <path_substring> [evidence_root] [base_url]")
        sys.exit(1)
    cap_dir, sub = args[0], args[1]
    ev_root = args[2] if len(args) > 2 else None
    base = args[3] if len(args) > 3 else None
    outcomes, summary, hits = run_capture_replay(cap_dir, sub, ev_root, base)
    print(f"扫描命中 {len(hits)} 条，已回放 {len(outcomes)} 条，汇总: {summary}")