# -*- coding: utf-8 -*-
"""HIGO red_packet_claim「历史Bug反推·第一类」真机复现探针（项目适配层）。

聚焦复现历史截图中的状态冲突：
  UI 认为「可 OPEN」 与 业务认为「还没开始(CLAIM_NOT_STARTED)」同时存在。

做法（RP-001..RP-004，网络攻撃 RP-005 因无 NetworkExecutor 已停用）：
  1) 拉取业务态 get_red_packet_info → (status, server_time, open_at, claimed_by_self)
  2) 真机打开红包弹窗（open_red_packet）→ dump UI 识别弹窗显示的 ui_state
  3) 用 core.attack.consistency 判定「UI 与业务状态一致性」是否违反

核心判定：status=3 WAITING(server_time<open_at) 时，UI 本应显示 COUNTDOWN，
若实测弹窗仍渲染出 OPEN(引导点击的领取按钮) => 复现历史 bug。
网络扰动(DISABLE/NETWORK) 一律不执行，避免打穿脆弱测试承载。
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from core.attack.consistency import load_model, check_consistency
from core.config import loader
from replay.capture_replay import CaptureReplay


MODEL_PATH = Path(__file__).resolve().parents[1] / "attack" / "red_packet_claim.json"


def _adb(serial: str, cmd: str, timeout: int = 15) -> str:
    # 关键：cmd 常含 `dump...; cat...` 分号。Windows shell=True 会把分号当 PowerShell 命令分隔符，
    # 导致 uiautomator/cat 在本地被当命令执行而失败。必须整体作为单参数传给 adb shell，
    # 用转义序列让 adb 端解析，避免 host 分号拆分。这里把 shell 命令整体用双引号包住传给 adb。
    quoted = cmd.replace('"', '\\"')
    full = (f'adb -s {serial} shell "{quoted}"' if serial else f'adb shell "{quoted}"')
    try:
        rp = subprocess.run(full, shell=True, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return rp.stdout or ""
    except Exception:
        return ""


def _dump_ui(serial: str, retries: int = 3) -> str:
    # 重定向(含 stderr)一律落到设备内 /sdcard，绝不用 /dev/null→Windows cmd 会解析成 D:\dev\null。
    # uiautomator 在直播间(动态画面)偶发 "could not get idle state"，重试即可。
    for _ in range(retries):
        out = _adb(serial, "uiautomator dump /sdcard/_attk.xml 2>/sdcard/_attk.err; cat /sdcard/_attk.xml")
        if out and "<hierarchy" in out:
            return out
        time.sleep(1)
    return ""


def _ensure_dump_ready(serial: str) -> None:
    """关闭系统动画+亮屏，消除 'could not get idle state'（直播间动态画面下 dump 极不稳定）。"""
    if not serial:
        return
    _adb(serial, "settings put global window_animation_scale 0; "
                 "settings put global transition_animation_scale 0; "
                 "settings put global animator_duration_scale 0; "
                 "input keyevent KEYCODE_WAKEUP")


def _ui_state_from_xml(xml: str) -> str | None:
    if not xml or "<hierarchy" not in xml:
        return None
    # 权威信号：红包入口状态 overlay（text 直接就是 OPEN/COUNTDOWN/...）
    import re as _re
    m = _re.search(r'<node[^>]*resource-id="[^"]*tv_red_packet_status_overlay"[^>]*text="([^"]*)"', xml)
    if m and m.group(1).strip():
        return m.group(1).strip().upper()
    # 兜底：按面板文案识别
    low = xml.lower()
    if any(k in low for k in ("claimed", "已领取")):
        return "CLAIMED"
    if any(k in low for k in ("countdown", "倒计时", "not started", "未开始")):
        return "COUNTDOWN"
    if any(k in low for k in ("open", "领取")):
        return "OPEN"
    if any(k in low for k in ("expired", "已过期")):
        return "EXPIRED"
    return None


def _fetch_state(project: str, env: str, cap_dir: Path, path_sub: str) -> dict | None:
    """回放拉取一次 get_red_packet_info，返回 {status, server_time, open_at, claimed_by_self}。"""
    replay = CaptureReplay(capture_dir=str(cap_dir), evidence_root="")
    entries = replay.scan(path_sub)
    if not entries:
        return None
    entry = replay.pick_successful(entries)
    try:
        body = entry.res_body
        if isinstance(body, str):
            body = json.loads(body)
        d = body.get("data") if isinstance(body, dict) else None
        rpi = (d or {}).get("red_packet_info") or {}
        return {"status": rpi.get("status"), "server_time": (d or {}).get("server_time"),
                "open_at": rpi.get("open_at"), "claimed_by_self": rpi.get("claimed_by_self")}
    except Exception:
        return None


def _open_red_packet(serial: str, idx: int) -> str:
    """真机点开红包弹窗：dump→定位红包入口(overlay 所在可点击容器)→tap→回 dump。

    返回点击后的 UI 层级 XML（尽力而为，失败返回空串）。
    """
    import re as _re
    xml = _dump_ui(serial)
    tgt = _clickable_center_of_overlay(xml)
    if tgt is None:
        from projects.higo.adapters.redpacket import parse_redpacket_bounds
        tgt = parse_redpacket_bounds(xml)
    if tgt is None:
        return ""
    x, y, pri = tgt
    _adb(serial, f"input tap {x} {y}", timeout=15)
    time.sleep(2)
    return _dump_ui(serial)


def _clickable_center_of_overlay(xml: str) -> tuple[int, int, int] | None:
    """从 XML 找 tv_red_packet_status_overlay 覆盖的可点击祖先（红包入口按钮）。

    返回 (x, y) 中心 + 优先级 3。找不到则 None。
    """
    import re as _re
    m = _re.search(r'<node[^>]*resource-id="[^"]*tv_red_packet_status_overlay"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
    if not m:
        return None
    cx = (int(m.group(1)) + int(m.group(3))) // 2
    cy = (int(m.group(2)) + int(m.group(4))) // 2
    # overlay 中心必落在其可点击祖先内；直接在祖先 bounds 中找唯一包含该点且可点击的
    for node in _re.findall(r'<node[^>]*>', xml):
        bm = _re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*clickable="true"', node) or \
             _re.search(r'clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        if not bm:
            continue
        x1, y1, x2, y2 = map(int, bm.group(1, 2, 3, 4))
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            return ((x1 + x2) // 2, (y1 + y2) // 2, 3)
    return (cx, cy, 3)


def run(project: str, env: str, evidence_dir: str | None = None,
        live_probe: bool = True) -> tuple[int, dict]:
    model = load_model(MODEL_PATH)

    proj = loader.load_project(project)
    env_cfg = loader.load_env(project, env)
    cap_dir = Path(proj.assets.get("whistle_dir") or f"output/captures/{project}")
    serial = env_cfg.device_serial

    # 关闭动画+亮屏，消除直播间动态画面下的 uiautomator 'could not get idle state'
    _ensure_dump_ready(serial)

    out_root = Path(evidence_dir) if evidence_dir else Path("output/evidence") / f"{project}-redpacket-claim-attack"
    out_root.mkdir(parents=True, exist_ok=True)

    # 业务态：优先抓包回放取真值；取不到则回退到模型内嵌的 WAITING(反推) 样本
    obs = _fetch_state(project, env, cap_dir, "/live/room/get_red_packet_info")
    if obs is None:
        obs = {"status": 3, "server_time": 0, "open_at": 1, "claimed_by_self": False}

    known = model["known_anomaly"]

    # ── 真机打开红包弹窗，观测 UI 是否错误渲染成 OPEN（复现核心） ──
    observations = []

    def note(label: str, business: dict, ui: str | None) -> dict:
        v = check_consistency(model, business.get("status"), business.get("server_time"),
                              business.get("open_at"), ui)
        observations.append({"label": label, "business": business, **v.to_dict()})
        return v

    # ① 历史反推样本：证明引擎能力命中历史异常
    note("bug复现观测(反推)", {"status": 3, "server_time": 0, "open_at": 1}, "OPEN")

    # ② 真机现场：打开红包弹窗后，按当前抓包业务态对照 UI
    popup_ui = None
    if live_probe and serial:
        xml2 = _open_red_packet(serial, idx=1)
        popup_ui = _ui_state_from_xml(xml2)
        note("真机现场观测(打开红包弹窗)", obs, popup_ui)

    # ③ 弹窗停留后重拉业务态，观察是否发生状态推进 UI 未刷新
    stale = None
    if live_probe and serial:
        before = dict(obs)
        time.sleep(3)
        after = _fetch_state(project, env, cap_dir, "/live/room/get_red_packet_info") or before
        ui_still = _ui_state_from_xml(_dump_ui(serial))
        status_moved = before.get("status") != after.get("status")
        stale = {
            "id": "P-07", "trigger": "T-07 state refresh gap",
            "status_before": before.get("status"), "status_after": after.get("status"),
            "ui_observed": ui_still, "status_moved": status_moved,
            "ui_stale_against_moved_status": status_moved and (popup_ui == ui_still),
        }
        note("真机刷新对照(状态推进后)", after, ui_still)

    # ── 复现判定 ──────────────────────────────────────────
    reproduced = any(o.get("label", "").startswith("真机") and not o["consistent"] for o in observations)
    anomaly_detected = any(not o["consistent"] for o in observations)
    live_consistent = not reproduced          # 现场未复现冲突 => 在线一致(PASS)

    # S0 回填：把本次执行的观测合并进 App Knowledge Base（长期累积，非一次性）
    try:
        from projects.higo.adapters.discover import (AppKnowledgeBase, backfill_observations)
        kb = AppKnowledgeBase(base_dir=Path("output/app_kb"), app=project)
        backfill_observations(kb, observations, room="14775",
                              source=f"exec:claim_attack:{time.strftime('%H%M%S')}")
    except Exception as _e:
        print(f"  · [discovery] KB 回填跳过: {_e}")

    report = {
        "target": model["target"],
        "bug_brief": model["bug_brief"],
        "known_anomaly": known,
        "engine": "core.attack.consistency (历史Bug反推·第一类)",
        "consistency_invariant": model["consistency_invariant"]["must_hold"],
        "observations": observations,
        "state_refresh_probe": stale,
        "reproduced_on_device": reproduced,
        "network_attack": {"enabled": False,
                           "reason": "RP-005 网络攻撃无 NetworkExecutor，已停用以避免打穿测试承载"},
        "anomaly_detected_by_engine": anomaly_detected,
        "live_consistent": live_consistent,
        "evidence_root": str(out_root),
    }
    (out_root / "execution_result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[red_packet_claim] 真机复现结束：引擎识别历史异常 = {anomaly_detected} | "
          f"现场复现冲突 = {reproduced}")
    for o in observations:
        print(f"  · {o['label']}: phase={o['phase']} 期望UI={o['expected_ui']} "
              f"观测UI={o['observed_ui']} 一致={o['consistent']}")
        for vi in o.get("violations", []):
            print(f"      ✗ {vi}")
    print(f"  · 网络攻撃: 已停用(RP-005 无 NetworkExecutor)")
    status = "FAIL" if reproduced else "PASS"
    print(f"  · 汇总: {status} -> {out_root / 'execution_result.json'}")
    return (1 if reproduced else 0, {"status": status,
                                     "reproduced_on_device": reproduced,
                                     "anomaly_detected_by_engine": anomaly_detected,
                                     "live_consistent": live_consistent,
                                     "report": str(out_root / 'execution_result.json'),
                                     "evidence_root": str(out_root)})