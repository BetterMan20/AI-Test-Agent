# -*- coding: utf-8 -*-
"""A 项目：批量账户登录 → 进房间 1096 → 占满麦位（压力测试前置条件）。

流程（每个账户）：
  1. get_captcha → login_by_captcha（通用验证码 3491）
  2. room/enter → room/enter/status/sync(is_rtc_online=true)
  3. mic/up 占一个空麦位（无空麦位则仅在线）

用法：
  python -m projects.a.adapters.mic_fill --phones 66001 66002 66003 --room 1096
  python -m projects.a.adapters.mic_fill --list-only   # 只看麦位现状
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

BASE = "https://test-api.miregame.com"
ROOM_ID = "1096"
CAPTCHA = "3491"
EVIDENCE_ROOT = Path("output") / "evidence_a_micfill"

# 未登录 Android 模板（来自真实抓包 1792741033）
H_ANDROID = {
    "h_dt": "0", "h_did": "bef1808d819c176e", "h_av": "1.1.0.295",
    "h_language": "ar", "h_model": "V2020CA", "h_app": "ht",
    "h_content_region": "AR", "h_room_id": "", "h_appid": "luckimo",
    "h_ts": "", "h_nonce": "c7e4b9a9532a432ca432ba949781569b",
    "h_sign": "A38PsBlIgQ9a70/j/edkXNkTRzlOKm2YJ+S2KNFhGn4=",
    "content-type": "application/json; charset=UTF-8",
    "accept-encoding": "gzip", "user-agent": "okhttp/5.4.0",
}

# vivo 真机账户（真机 UI 上麦，API 不用管）
REAL_DEVICE_UID = 20337846


def _call(path: str, body: dict, headers: dict | None = None) -> dict:
    h = dict(headers or H_ANDROID, h_ts=str(int(time.time())))
    resp = requests.post(BASE + path, headers=h, data=json.dumps(body).encode(), timeout=15)
    try:
        return resp.json()
    except Exception:
        return {"http": resp.status_code, "text": resp.text[:200]}


def login(phone: str, cc: str = "+966") -> dict:
    """get_captcha → login_by_captcha；未注册自动 register_by_captcha。
    每账户独立 h_did（服务端按设备限注册数 ret=1049，且验证码与设备绑定 ret=1009）。"""
    did = uuid.uuid4().hex[:16]

    def _c(path: str, body: dict) -> dict:
        return _call(path, body, dict(H_ANDROID, h_did=did, h_ts=str(int(time.time()))))

    _c("/account/get_captcha", {"captcha_type": 1, "country_code": cc, "phone": phone, "scene": 1})
    time.sleep(0.3)
    r = _c("/account/login_by_captcha",
           {"captcha": CAPTCHA, "captcha_type": 1, "country_code": cc, "phone": phone})
    if r.get("need_register"):
        time.sleep(0.3)
        r = _c("/account/register_by_captcha",
               {"captcha": CAPTCHA, "captcha_type": 1, "country_code": cc,
                "phone": phone, "system_language": "zh-CN"})
    uid = (r.get("user_basic_info") or {}).get("user_id") or r.get("user_id")
    return {
        "phone": phone, "cc": cc,
        "ret": r.get("ret"), "need_register": r.get("need_register"),
        "uid": uid,
        "access_token": r.get("access_token") or "",
        "refresh_token": r.get("refresh_token") or "",
        "name": (r.get("user_basic_info") or {}).get("name"),
    }


def mic_list(refresh: str, access: str, uid: int | str) -> list[dict]:
    h = dict(H_ANDROID, h_m=str(uid), h_token=refresh, authorization=f"Bearer {access}")
    r = _call("/voice_room/api/app/room_core/v1/room/mic/list", {"room_id": ROOM_ID}, h)
    return (r.get("data") or {}).get("mic_list") or []


def enter_room(refresh: str, access: str, uid: int | str) -> tuple[int, int]:
    """enter + status/sync，返回 (enter_code, sync_code)。"""
    h = dict(H_ANDROID, h_m=str(uid), h_token=refresh, authorization=f"Bearer {access}")
    r1 = _call("/voice_room/api/app/room_core/v1/room/enter",
               {"room_id": ROOM_ID, "source": "home_room_card"}, h)
    time.sleep(0.4)
    r2 = _call("/voice_room/api/app/room_core/v1/room/enter/status/sync",
               {"is_rtc_online": True, "room_id": ROOM_ID}, h)
    return r1.get("code"), r2.get("code")


def mic_up(refresh: str, access: str, uid: int | str, seat: int) -> dict:
    h = dict(H_ANDROID, h_m=str(uid), h_token=refresh, authorization=f"Bearer {access}")
    r = _call("/voice_room/api/app/room_core/v1/room/mic/up",
              {"mic_num": seat, "room_id": ROOM_ID}, h)
    return r


def run(phones: list[str], cc: str = "+966") -> dict:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    summary: dict = {
        "room_id": ROOM_ID, "started_at": datetime.now().isoformat(timespec="seconds"),
        "accounts": [], "seats_final": {}, "on_mic": 0, "online": 0,
    }

    for phone in phones:
        entry: dict = {"phone": phone}
        try:
            cred = login(phone, cc)
            entry.update({k: cred[k] for k in ("ret", "need_register", "uid", "name")})
            if cred["ret"] != 0 or not cred["access_token"]:
                entry["status"] = "login_failed"
                summary["accounts"].append(entry)
                continue

            enter_code, sync_code = enter_room(cred["refresh_token"], cred["access_token"], cred["uid"])
            entry["enter"] = enter_code
            entry["sync"] = sync_code

            mics = mic_list(cred["refresh_token"], cred["access_token"], cred["uid"])
            empty = [m["mic_num"] for m in mics if m.get("mic_user_id") in (None, "0", 0)]

            if empty:
                seat = empty[0]
                r = mic_up(cred["refresh_token"], cred["access_token"], cred["uid"], seat)
                ok = r.get("code") == 0
                entry["seat"] = seat if ok else None
                entry["mic_up_code"] = r.get("code")
                entry["status"] = "on_mic" if ok else "mic_up_failed"
                time.sleep(0.4)
            else:
                entry["status"] = "online_no_seat"

            summary["accounts"].append(entry)
            print(f"  {phone} uid={entry.get('uid')} -> {entry['status']}"
                  + (f" seat={entry['seat']}" if entry.get("seat") else ""))
            time.sleep(0.5)
        except Exception as e:  # noqa: BLE001
            entry["status"] = f"error: {type(e).__name__}: {e}"
            summary["accounts"].append(entry)
            print(f"  {phone} -> {entry['status']}")

    # 最终麦位快照
    try:
        cred0 = login(phones[0], cc)
        mics = mic_list(cred0["refresh_token"], cred0["access_token"], cred0["uid"])
        summary["seats_final"] = {str(m["mic_num"]): m.get("mic_user_id") for m in mics}
        summary["on_mic"] = sum(1 for v in summary["seats_final"].values() if v not in (None, "0"))
    except Exception as e:  # noqa: BLE001
        summary["seats_final_error"] = str(e)

    summary["online"] = sum(1 for a in summary["accounts"] if a["status"] in ("on_mic", "online_no_seat"))
    summary["finished_at"] = datetime.now().isoformat(timespec="seconds")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    (EVIDENCE_ROOT / f"micfill_{ts}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def run_bulk(phones: list[str], cc: str = "+966", threads: int = 10) -> dict:
    """批量进房 1096 并占满麦位（编排逻辑在 core.load.bulk_room_load，本函数只绑定 A 项目回调）。"""
    from core.load import bulk_room_load

    failures: list[dict] = []

    def login_fn(phone: str) -> dict | None:
        cred = login(phone, cc)
        if cred["ret"] != 0 or not cred["access_token"]:
            failures.append({"phone": phone, "ret": cred.get("ret")})
            return None
        return cred

    def enter_fn(cred: dict) -> tuple[int, int]:
        return enter_room(cred["refresh_token"], cred["access_token"], cred["uid"])

    def mic_list_fn(cred: dict) -> list[dict]:
        return mic_list(cred["refresh_token"], cred["access_token"], cred["uid"])

    def mic_up_fn(cred: dict, seat: int) -> int:
        r = mic_up(cred["refresh_token"], cred["access_token"], cred["uid"], seat)
        return r.get("code", -1)

    summary = bulk_room_load(
        phones, login_fn=login_fn, enter_fn=enter_fn,
        mic_list_fn=mic_list_fn, mic_up_fn=mic_up_fn,
        room_id=ROOM_ID, threads=threads, evidence_dir=EVIDENCE_ROOT, label="bulk",
    )
    summary["login_failures"] = failures[:50]
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="批量登录进房占麦位")
    ap.add_argument("--phones", nargs="+", default=[f"660{n:02d}" for n in range(1, 11)])
    ap.add_argument("--count", type=int, default=0,
                    help="批量数量 N → 手机号 66001..660NN（覆盖 --phones）")
    ap.add_argument("--cc", default="+966")
    ap.add_argument("--threads", type=int, default=10)
    ap.add_argument("--list-only", action="store_true")
    args = ap.parse_args()

    if args.list_only:
        cred = login(args.phones[0], args.cc)
        mics = mic_list(cred["refresh_token"], cred["access_token"], cred["uid"])
        for m in mics:
            print(f"  mic {m['mic_num']}: {m.get('mic_user_id') or '(空)'}")
        return 0

    phones = ([f"66{n:03d}" for n in range(1, args.count + 1)]
              if args.count else args.phones)
    summary = run_bulk(phones, args.cc, args.threads)
    slim = {k: v for k, v in summary.items() if k != "accounts"}
    print(json.dumps(slim, ensure_ascii=False, indent=2))
    bad = [a for a in summary["accounts"] if a["status"] != "online"]
    print(f"非在线账户 {len(bad)} 个: {json.dumps(bad[:20], ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
