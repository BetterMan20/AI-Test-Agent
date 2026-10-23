# -*- coding: utf-8 -*-
"""通用房间容量加载引擎（批量账户 → 登录 → 进房 → 占麦位）。

Core 层只做编排（并发、补麦位、证据落盘），不含项目语义：
登录 / 进房 / 麦位操作全部由项目适配器注入回调。
项目适配器示例见 projects/a/adapters/mic_fill.py。

适配器回调契约：
  login_fn(phone)          -> cred | None    # None=登录失败；cred 为 dict 且含 uid
  enter_fn(cred)           -> (enter_code, sync_code)
  mic_list_fn(cred)        -> list[dict]     # [{mic_num, mic_user_id}, ...]
  mic_up_fn(cred, seat)    -> int            # 业务码，0=成功

用法（A 项目，房间 1096 灌 500 人并占满麦位）：
  python -m projects.a.adapters.mic_fill --count 500 --threads 10
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

_EMPTY_SEAT_VALUES = (None, "", "0", 0)


def bulk_room_load(
    phones: list[str],
    *,
    login_fn,
    enter_fn,
    mic_list_fn,
    mic_up_fn,
    room_id: str,
    threads: int = 10,
    evidence_dir: str | Path | None = None,
    label: str = "bulk",
    progress_every: int = 50,
) -> dict:
    """批量加载房间：并发登录+进房，结束后顺序补占全部空麦位（两轮补漏）。

    返回 summary dict；evidence_dir 提供时自动落盘 JSON 证据。
    """
    summary: dict = {
        "room_id": room_id, "mode": label,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(phones), "threads": threads,
    }

    def worker(phone: str) -> tuple[dict, dict | None]:
        entry: dict = {"phone": phone}
        try:
            cred = login_fn(phone)
            if not cred:
                entry["status"] = "login_failed"
                return entry, None
            entry["uid"] = cred.get("uid") if isinstance(cred, dict) else None
            enter_code, sync_code = enter_fn(cred)
            entry["enter"] = enter_code
            entry["sync"] = sync_code
            entry["status"] = "online" if enter_code == 0 else f"enter_{enter_code}"
            return entry, cred
        except Exception as e:  # noqa: BLE001
            entry["status"] = f"error: {type(e).__name__}: {e}"
            return entry, None

    entries: list[dict] = []
    creds: list[dict] = []
    with ThreadPoolExecutor(max_workers=threads) as pool:
        futs = [pool.submit(worker, p) for p in phones]
        for i, fut in enumerate(as_completed(futs), 1):
            e, c = fut.result()
            entries.append(e)
            if c:
                creds.append(c)
            if i % progress_every == 0 or i == len(phones):
                online = sum(1 for x in entries if x["status"] == "online")
                print(f"  进度 {i}/{len(phones)}，在线 {online}")

    entries.sort(key=lambda x: x["phone"])
    summary["online"] = sum(1 for e in entries if e["status"] == "online")
    summary["login_failed"] = sum(1 for e in entries if e["status"] == "login_failed")
    summary["enter_rejected"] = sum(
        1 for e in entries if str(e.get("status", "")).startswith("enter_"))

    # ---- 顺序补占麦位（两轮：list → up → 再 list 补漏）----
    filled: dict[str, object] = {}
    mic_fill_error = ""
    try:
        pool_idx = 0
        for _pass in range(2):
            mics = mic_list_fn(creds[0])
            empty = [m["mic_num"] for m in mics
                     if m.get("mic_user_id") in _EMPTY_SEAT_VALUES]
            if not empty:
                break
            for seat in empty:
                if pool_idx >= len(creds):
                    break
                cred = creds[pool_idx]
                pool_idx += 1
                if mic_up_fn(cred, seat) == 0:
                    filled[str(seat)] = cred.get("uid") if isinstance(cred, dict) else None
    except Exception as e:  # noqa: BLE001
        mic_fill_error = str(e)
    summary["mic_fill_error"] = mic_fill_error
    summary["mics_filled"] = filled

    # ---- 最终麦位快照 ----
    try:
        mics = mic_list_fn(creds[0])
        summary["seats_final"] = {str(m["mic_num"]): m.get("mic_user_id") for m in mics}
        summary["on_mic"] = sum(
            1 for v in summary["seats_final"].values() if v not in _EMPTY_SEAT_VALUES)
    except Exception as e:  # noqa: BLE001
        summary["seats_final_error"] = str(e)

    summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
    if evidence_dir:
        root = Path(evidence_dir)
        root.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        payload = dict(summary)
        payload["accounts"] = entries
        (root / f"roomload_{label}_{ts}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["accounts"] = entries
    return summary
