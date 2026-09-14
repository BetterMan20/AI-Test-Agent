# -*- coding: utf-8 -*-
"""HIGO 红包能力（项目适配层内实现，Core 不知道它）。

业务动作：
  · Phase A — API: POST /live/room/send_red_packet（真实抓包原样回放）
  · Phase B — ADB+UI 自动化: 解锁 -> uiautomator dump -> 解析红包入口 -> tap 下钻 -> 回 dump 校验

全部配置/数据/凭证来自 core.config.loader；sign/raw_body 取自 testdata 的敏感样本。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from core.config import loader
from engine import TestEngine
from execution.planner import ExecutionPlanner


def parse_redpacket_bounds(xml: str) -> tuple[int, int, int] | None:
    """从 uiautomator XML 找红包/礼物入口，返回点击中心 (x, y, priority)。"""
    RED_KW = ("红包", "redpacket", "red_packet", "red packet", "lucky", "幸运", "开红包", "抢红包")
    GIFT_KW = ("gift", "礼物", "iv_gift", "fl_gift", "金币", "coin")
    nodes = re.findall(r"<node[^>]*?>", xml)
    best, best_pri, best_area = None, 0, 0
    for n in nodes:
        m = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', n)
        if not m:
            continue
        text = (re.search(r'text="([^"]*)"', n) or [None, ""])[1]
        desc = (re.search(r'content-desc="([^"]*)"', n) or [None, ""])[1]
        rid = (re.search(r'resource-id="([^"]*)"', n) or [None, ""])[1]
        hay = f"{text} {desc} {rid}".lower()
        pri = 3 if any(k.lower() in hay for k in RED_KW) else (
            2 if any(k.lower() in hay for k in GIFT_KW) else 0)
        if pri == 0:
            continue
        x1, y1, x2, y2 = map(int, m.group(1, 2, 3, 4))
        area = (x2 - x1) * (y2 - y1)
        if pri > best_pri or (pri == best_pri and area > best_area):
            best_pri, best_area, best = pri, area, ((x1 + x2) // 2, (y1 + y2) // 2, pri)
    return best


def dump_cmd(tag: str) -> str:
    return ("input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; "
            f"uiautomator dump /sdcard/_rp_{tag}.xml >/dev/null 2>&1; "
            f"cat /sdcard/_rp_{tag}.xml")


def read_adb_output(tc_dir: Path, step_id: int) -> str:
    out = tc_dir / f"step{step_id}_adb_output.json"
    if not out.exists():
        return ""
    try:
        return json.loads(out.read_text(encoding="utf-8")).get("output", "")
    except Exception:
        return out.read_text(encoding="utf-8")


def run(project: str, env: str, evidence_dir: str | None = None) -> tuple[int, dict]:
    env_cfg = loader.load_env(project, env)
    proj = loader.load_project(project)
    data = loader.load_testdata(project, "redpacket")   # 合并 .auth 敏感样本(sign/raw_body/token)
    assets = proj.assets

    base_url = env_cfg.api_base_url
    headers = dict(env_cfg.api_headers)
    serial = env_cfg.device_serial
    sign = str(data.get("sign", ""))
    raw_body = str(data.get("raw_body", ""))
    path = str(assets.get("redpacket_path", "/live/room/send_red_packet"))

    if not sign or not raw_body:
        raise ValueError("缺少敏感样本 redpacket.auth.yaml（sign/raw_body）——该文件已 gitignore，需本地补全。")

    out_root = Path(evidence_dir) if evidence_dir else Path("output/evidence") / f"{project}-redpacket-e2e"
    out_root.mkdir(parents=True, exist_ok=True)

    engine = TestEngine(
        api_base_url=base_url, api_headers=headers, api_timeout=env_cfg.api_timeout,
        evidence_dir=str(out_root), adb_device_serial=serial, validate_plans=False,
    )
    results = []
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    # ── Phase A: API 发送红包 ──────────────────────────────
    print("\n========== Phase A: API send_red_packet ==========", flush=True)
    api_plan = ExecutionPlanner.plan_from_dict({
        "tc_id": "TC-RP-API-001",
        "title": "发红包-send_red_packet-真实抓包原样回放",
        "preconditions": ["来自真实抓包成功请求", "sign 基于 h_ts+token+body 计算，须原样回放"],
        "test_data": [f"room_id={data.get('room_id')}", f"coins={data.get('coins')}",
                      f"quantity={data.get('quantity')}", f"countdown_seconds={data.get('countdown_seconds')}"],
        "steps": [{
            "step_id": 1, "type": "api",
            "description": f"POST {path}（原样 data）",
            "config": {"method": "POST", "path": path,
                       "params": {"sign": sign}, "headers": headers, "data": raw_body},
            "assertions": [
                {"type": "status_code", "expected": 200},
                {"type": "json_path", "path": "$.ret", "expected": 1},
                {"type": "json_path", "path": "$.data.status", "expected": 0},
            ],
            "evidence_types": ["api_response"],
        }],
    })
    r = engine.run_plan(api_plan)
    print(f"API 结果: status={r.status} assert_ok={r.step_results[0].assertions_passed if r.step_results else 0}")
    results.append(r)

    # ── Phase B: ADB+UI 自动化 ─────────────────────────────
    print("\n========== Phase B: ADB+UI 自动化 ==========", flush=True)
    ui1_dir = out_root / "TC-RP-UI-001"
    plan_dump = ExecutionPlanner.plan_from_dict({
        "tc_id": "TC-RP-UI-001",
        "title": "加载当前直播页面并 dump UI（wakeup+unlock）",
        "steps": [{
            "step_id": 1, "type": "adb", "description": "解锁并抓取当前页面 UI 层级",
            "config": {"command": dump_cmd("before")},
            "assertions": [{"type": "text_contains", "expected": "<hierarchy"}],
            "evidence_types": ["screenshot", "logcat"],
        }],
    })
    r1 = engine.run_plan(plan_dump)
    print(f"UI dump 结果: status={r1.status}")
    results.append(r1)

    xml = read_adb_output(ui1_dir, 1)
    print(f"首页 dump 长度 {len(xml)}")

    hit_red, seq = False, 2
    for _ in range(4):
        tgt = parse_redpacket_bounds(xml)
        if tgt is None:
            print("⚠ 当前视图未发现红包/礼物入口，停止下钻")
            break
        x, y, pri = tgt
        kind = "红包入口" if pri >= 3 else "礼物面板"
        ui_tc = f"TC-RP-UI-{seq:03d}"
        seq += 1
        dir_ = out_root / ui_tc
        p = ExecutionPlanner.plan_from_dict({
            "tc_id": ui_tc,
            "title": f"点击{kind} ({x},{y}) 后回 dump",
            "steps": [{
                "step_id": 1, "type": "adb",
                "description": f"input tap {x} {y} 触碰{kind}并重新 dump",
                "config": {"command": f"input tap {x} {y}; sleep 2; {dump_cmd('after_' + ui_tc[-3:])}"},
                "assertions": [], "evidence_types": ["screenshot", "logcat"],
            }],
        })
        r = engine.run_plan(p)
        print(f"{ui_tc} 点击{kind}({x},{y}): status={r.status}")
        results.append(r)
        xml = read_adb_output(dir_, 1)
        if pri >= 3:
            hit_red = True
            print(f"  ✅ 已触达红包入口，新 dump 长度 {len(xml)}")
            break

    panel_kw = ("coins", "金币", "red", "红包", "quantity", "人数", "send", "发送", "countdown", "抢")
    panel_ok = bool(xml and any(k.lower() in xml.lower() for k in panel_kw))
    print("✅ 面板校验：命中红包/金币特征" if panel_ok else "⚠ 面板校验未命中红包/金币特征")

    summary = [{
        "tc_id": x.tc_id, "title": x.title, "status": x.status,
        "duration_ms": x.duration_ms,
        "steps": [{"step": s.step_id, "type": s.step_type, "status": s.status,
                   "assert_ok": s.assertions_passed, "error": s.error,
                   "evidence": [Path(ev).name if ev else ev for ev in s.evidence_refs]}
                  for s in x.step_results],
    } for x in results]
    report = {
        "run_time": now, "project": project, "env": env,
        "config": {"path": path, "device": serial, "sign_present": bool(sign)},
        "notes": f"countdown_seconds={data.get('countdown_seconds')}",
        "panel_verified": panel_ok,
        "redirect_reached": hit_red,
        "results": summary, "evidence_root": str(out_root),
    }
    rep_path = out_root / "execution_result.json"
    rep_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 汇总已写入: {rep_path}")
    engine.close()

    all_pass = all(x.status in ("PASS", "passed") for x in results)
    status = "PASS" if all_pass else "FAIL"
    return (0 if all_pass else 1, {"status": status, "report": str(rep_path),
                                   "panel_verified": panel_ok, "evidence_root": str(out_root)})