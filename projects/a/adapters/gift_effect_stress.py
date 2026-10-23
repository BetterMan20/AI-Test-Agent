# -*- coding: utf-8 -*-
"""A 项目礼物特效压力复现原语 —— PAGAnimator finalize 死锁闪退（DEF-A-PAG-001）。

把手动复现路径固化为可独立运行的 CLI 动作（无 LLM、无人工干预）：
  建房 → 进房 → 循环 N 轮[送最便宜礼物 → 播放中退房(触发 onAnimationCancel)
  → 退后台强制 GC(trim memory) → 查 crash 特征]
命中特征（PAGAnimator.finalize() timed out / 进程死亡）即落证据：
  crash logcat、截图、每轮 adb_execution 元数据、summary.json。

用法：
  python -m projects.a.adapters.gift_effect_stress --project a --env test --cycles 10

前置条件：
  - 真机已连接（serial 取 config/environments/<project>-<env>.yaml 的 device.serial）
  - 账号已登录（启动直达 MainActivity），且金币余额 >= 最便宜礼物价格
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

PACKAGE = "com.st.game.android"
CRASH_SIGNATURE = "PAGAnimator.finalize() timed out"
EVIDENCE_ROOT = Path("output") / "evidence_a_crash"

MAIN_ACTIVITY = "com.tg.ui.home.MainActivity"
ROOM_ACTIVITY = "com.tg.room.LiveRoomActivity"
LOGIN_HINT = "com.tg.ui.auth"

# 界面文案随系统语言切换（en/ar，ar 为 RTL 布局），定位用语义集合而非坐标/索引
TAB_ROOM_TEXTS = {"Room", "الغرف"}
TAB_MINE_TEXTS = {"Mine", "غرفي"}
TAB_EXPLORE_TEXTS = {"Explore", "استكشاف"}
SELF_NICK = "النجم الساطع"  # 测试账号 66002 昵称：自建房送礼无效（麦上无他人），须进别人房间


# ---------------- adb 基础（15s 超时防挂起，异常不中断主循环） ----------------

def _adb(serial: str, *args: str, timeout: int = 15) -> str:
    try:
        r = subprocess.run(["adb", "-s", serial, *args], capture_output=True,
                           text=True, timeout=timeout, encoding="utf-8", errors="replace")
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f"__ADB_ERROR__ {e}"


def _tap(serial: str, x: int, y: int) -> None:
    _adb(serial, "shell", "input", "tap", str(x), str(y))


def _pid(serial: str) -> str:
    return _adb(serial, "shell", "pidof", PACKAGE).strip()


def _current_activity(serial: str) -> str:
    out = _adb(serial, "shell", "dumpsys", "activity", "activities")
    m = re.search(r"mResumedActivity:.*?([\w.]+/[\w.]+)", out)
    return m.group(1) if m else ""


def _dump_ui(serial: str) -> ET.Element | None:
    """uiautomator dump 并剥壳（真机 dump 混有噪声头），返回 XML 根。"""
    _adb(serial, "shell", "uiautomator", "dump", "/sdcard/__ui.xml")
    raw = _adb(serial, "shell", "cat", "/sdcard/__ui.xml")
    start, end = raw.find("<?xml"), raw.rfind("</hierarchy>")
    if start < 0 or end < 0:
        return None
    try:
        return ET.fromstring(raw[start:end + len("</hierarchy>")])
    except ET.ParseError:
        return None


def _bounds_center(bounds: str) -> tuple[int, int] | None:
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def _find_by_id(root: ET.Element, rid_suffix: str) -> ET.Element | None:
    for n in root.iter("node"):
        if (n.get("resource-id") or "").endswith(rid_suffix):
            return n
    return None


def _find_by_text(root: ET.Element, text: str) -> ET.Element | None:
    for n in root.iter("node"):
        if (n.get("text") or "") == text:
            return n
    return None


def _tap_node(serial: str, node: ET.Element | None) -> bool:
    if node is None:
        return False
    c = _bounds_center(node.get("bounds"))
    if not c or c == (0, 0):
        return False
    _tap(serial, *c)
    return True


def _screen_size(serial: str) -> tuple[int, int]:
    out = _adb(serial, "shell", "wm", "size")
    m = re.search(r"(\d+)x(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (1080, 2400)


def _tap_bottom_tab(serial: str, texts: set) -> bool:
    """动态定位底部 tab：标签文案向上找可点击祖先（兼容 LTR/RTL，与 x 顺序无关）。"""
    root = _dump_ui(serial)
    if root is None:
        return False
    parent = {c: p for p in root.iter("node") for c in p}
    for n in root.iter("node"):
        if (n.get("text") or "") in texts:
            cur = n
            while cur is not None:
                if cur.get("clickable") == "true":
                    c = _bounds_center(cur.get("bounds"))
                    if c and c != (0, 0):
                        _tap(serial, *c)
                        return True
                cur = parent.get(cur)
    return False


_SIZE_CACHE: dict = {}


def _screen_size_cache(serial: str) -> tuple[int, int]:
    if serial not in _SIZE_CACHE:
        _SIZE_CACHE[serial] = _screen_size(serial)
    return _SIZE_CACHE[serial]


# ---------------- 业务步骤 ----------------

def _launch(serial: str) -> str:
    _adb(serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
    w, h = _screen_size_cache(serial)
    _adb(serial, "shell", "input", "swipe", str(w // 2), str(int(h * 0.8)),
         str(w // 2), str(int(h * 0.3)))  # 上滑解锁（锁屏杂志会挡 monkey 拉起）
    _adb(serial, "shell", "monkey", "-p", PACKAGE,
         "-c", "android.intent.category.LAUNCHER", "1")
    for _ in range(20):
        time.sleep(1)
        act = _current_activity(serial)
        if LOGIN_HINT in act:
            return act
        if ROOM_ACTIVITY in act:
            return act
        if MAIN_ACTIVITY in act and _main_ui_ready(serial):
            break
    return _current_activity(serial)


def _main_ui_ready(serial: str) -> bool:
    """主界面渲染就绪判据：底部 tab 条已出现（冷启动 splash 期间不可点击）。"""
    root = _dump_ui(serial)
    if root is None:
        return False
    _, h = _screen_size_cache(serial)
    segs = [n for n in root.iter("node")
            if n.get("clickable") == "true" and "LinearLayout" in (n.get("class") or "")
            and re.match(r"\[(\d+),(\d+)\]", n.get("bounds") or "")
            and int(re.match(r"\[(\d+),(\d+)\]", n.get("bounds")).group(2)) > h - 220]
    return len(segs) >= 5


def _enter_room(serial: str) -> bool:
    """优先进 Explore 列表里别人的房（麦上有真实用户，送礼才有效）；
    列表为空时回退自建房（Mine → Create/房间卡）。每步一次重试。"""
    if ROOM_ACTIVITY in _current_activity(serial):
        return True
    for attempt in range(2):
        _tap_bottom_tab(serial, TAB_ROOM_TEXTS)
        time.sleep(2.5)
        root = _dump_ui(serial)
        if root is None:
            continue
        # 确保在 Explore 子 tab
        explore = next((n for n in root.iter("node")
                        if (n.get("text") or "") in TAB_EXPLORE_TEXTS), None)
        if explore is not None:
            _tap_node(serial, explore)
            time.sleep(2.5)
            root = _dump_ui(serial)
        if root is None:
            continue
        # 房间列表 tvTitle：排除自己的房
        titles = [n for n in root.iter("node")
                  if (n.get("resource-id") or "").endswith("tvTitle")
                  and SELF_NICK not in (n.get("text") or "")]
        if titles:
            if _tap_node(serial, titles[0]):
                for _ in range(10):
                    time.sleep(1)
                    if ROOM_ACTIVITY in _current_activity(serial):
                        return True
                continue
        else:
            # 空列表：点一次刷新（btnEmptyAction），仍无房则回退自建
            _tap_node(serial, _find_by_id(root, "btnEmptyAction"))
            time.sleep(2.5)
            if attempt == 0:
                continue
            # 回退：Mine → Create 或已有房卡
            root = _dump_ui(serial)
            mine = next((n for n in (root.iter("node") if root is not None else [])
                         if (n.get("text") or "") in TAB_MINE_TEXTS), None)
            if mine is None or not _tap_node(serial, mine):
                return False
            time.sleep(2.5)
            root = _dump_ui(serial)
            if root is None:
                return False
            target = _find_by_id(root, "btnOwnerEmptyCreate")
            if target is None:
                target = _find_by_id(root, "ownerCardRoot")
            if target is None or not _tap_node(serial, target):
                return False
            for _ in range(10):
                time.sleep(1)
                if ROOM_ACTIVITY in _current_activity(serial):
                    return True
    return False


def _read_balance(serial: str) -> int | None:
    """Game tab 的 tvCoinBalance 读取金币余额；读不到返回 None（不误判为 0）。"""
    _tap_bottom_tab(serial, {"Game", "الألعاب"})
    time.sleep(2)
    root = _dump_ui(serial)
    if root is None:
        return None
    n = _find_by_id(root, "tvCoinBalance")
    if n is not None:
        try:
            return int(re.sub(r"\D", "", n.get("text") or "") or 0)
        except ValueError:
            return None
    return None


def _send_combo_gift(serial: str, combo: int = 7) -> dict:
    """房间内：btnGift → 选 All → 选最便宜礼物 → **快速连送 N 次**触发 combo 全屏 PAG 特效。

    combo 窗口 2500ms，单次 Send 间隔 ≤ 0.8s 可落同一 combo。MongoDB batch_num_levels=[2,4,6]
    是 UI 快捷批量按钮，但 PAG 全屏庆典在 combo_times 越高越容易触发（取 7 连送 > 6）。
    """
    meta: dict = {"steps": [], "combo_target": combo}
    root = _dump_ui(serial)
    if root is None or not _tap_node(serial, _find_by_id(root, "btnGift")):
        meta["error"] = "未找到礼物入口 btnGift"
        return meta
    time.sleep(3)
    root = _dump_ui(serial)
    if root is None:
        meta["steps"].append("礼物面板 dump 失败")
        return meta
    _tap_node(serial, _find_by_id(root, "tvSelectAllRecipients"))
    meta["steps"].append("recipient=All")
    time.sleep(1.5)

    prices = [(int(re.sub(r"\D", "", n.get("text") or "0") or 0), n.get("bounds"))
              for n in root.iter("node") if (n.get("resource-id") or "").endswith("tvGiftPrice")]
    names = [n for n in root.iter("node") if (n.get("resource-id") or "").endswith("tvGiftName")]
    if not prices or not names:
        meta["error"] = "礼物列表为空"
        return meta
    min_price, pb = min(prices, key=lambda t: t[0])
    meta["gift_price"] = min_price
    py = _bounds_center(pb)[1]
    target = min(names, key=lambda n: abs((_bounds_center(n.get("bounds")) or (0, 0))[1] - py))
    meta["gift_name"] = target.get("text") or ""
    _tap_node(serial, target)
    time.sleep(1.5)

    # 连送 N 次：Send 按钮位置固定，用坐标 tap 避免 dump 开销（窗口 2500ms 内完成）
    root = _dump_ui(serial)
    send_node = _find_by_id(root, "tvGiftSend") if root is not None else None
    if send_node is None:
        meta["error"] = "未找到 Send 按钮"
        return meta
    sx, sy = _bounds_center(send_node.get("bounds"))
    sent = 0
    for i in range(combo):
        _adb(serial, "shell", "input", "tap", str(sx), str(sy))
        sent += 1
        meta["steps"].append(f"send#{sent}")
        time.sleep(0.6)  # 0.6s 间隔 < combo_interval_ms(2500)，同 combo
    meta["sent_count"] = sent
    return meta


def _exit_room_during_playback(serial: str) -> None:
    """播放中退房：Back 关面板/触退出确认 → tvExit。触发 onAnimationCancel 路径。"""
    time.sleep(1.0)
    for _ in range(3):
        _adb(serial, "shell", "input", "keyevent", "4")
        time.sleep(1.2)
        root = _dump_ui(serial)
        node = _find_by_id(root, "tvExit") if root is not None else None
        if node is not None:
            _tap_node(serial, node)
            time.sleep(2)
            return
        if ROOM_ACTIVITY not in _current_activity(serial):
            return


def _background_and_gc(serial: str) -> None:
    """退后台 + trim memory 80(TRIM_MEMORY_COMPLETE) 诱导 GC，让 finalize 尽快开跑。"""
    _adb(serial, "shell", "input", "keyevent", "3")
    time.sleep(2)
    pid = _pid(serial)
    if pid:
        _adb(serial, "shell", "am", "send-trim-memory", pid, "80")


def _check_crash(serial: str, base_pid: str) -> tuple[bool, str]:
    """crash buffer 特征 + 进程死亡双重确认（adb 偶发空读，死亡需连续两次确认）。"""
    crash = _adb(serial, "logcat", "-d", "-b", "crash")
    if CRASH_SIGNATURE in crash:
        return True, "signature"
    now = _pid(serial)
    if not now or now != base_pid:
        time.sleep(2)
        now2 = _pid(serial)
        if not now2 or now2 != base_pid:
            return True, f"process_died({base_pid}->{now2 or 'gone'})"
    return False, ""


# ---------------- 主流程 ----------------

def run(env_cfg=None, evidence_dir: str | None = None, cycles: int = 10,
        settle_wait: int = 300, combo: int = 7) -> tuple[int, dict]:
    root = Path(evidence_dir) if evidence_dir else EVIDENCE_ROOT
    root.mkdir(parents=True, exist_ok=True)

    serial = getattr(env_cfg, "device_serial", "") if env_cfg else ""
    if not serial:
        return 2, {"status": "ERROR", "error": "env 配置缺 device.serial"}
    state = _adb(serial, "get-state", timeout=5)
    if "device" not in state:  # adb daemon 冷启动时首条输出被启动噪声覆盖，重试一次
        time.sleep(2)
        state = _adb(serial, "get-state", timeout=5)
    if "device" not in state.replace("daemon started", ""):
        return 2, {"status": "ERROR", "error": f"设备 {serial} 不在线"}

    summary: dict = {"status": "PASS", "crash_found": False, "cycles_done": 0,
                     "package": PACKAGE, "device": serial,
                     "started_at": datetime.now().isoformat(timespec="seconds"),
                     "evidence": []}

    act = _launch(serial)
    if LOGIN_HINT in act:
        summary.update(status="ERROR", error="当前在登录页，请先手动登录后重跑")
        return 2, summary

    balance = _read_balance(serial)
    summary["initial_balance"] = balance

    base_pid = _pid(serial)
    crashed = False
    for i in range(1, cycles + 1):
        t0 = time.time()
        cycle: dict = {"cycle": i, "actions": []}

        if not _enter_room(serial):
            cycle["error"] = "进房失败"
        else:
            gift_meta = _send_combo_gift(serial, combo=combo)
            cycle["gift"] = gift_meta
            if "error" in gift_meta:
                cycle["error"] = gift_meta["error"]
            else:
                _exit_room_during_playback(serial)
                cycle["actions"].append("exit_during_playback")
        _background_and_gc(serial)
        cycle["actions"].append("background_gc")

        crashed, how = _check_crash(serial, base_pid)
        cycle["cost_s"] = round(time.time() - t0, 1)
        (root / f"cycle_{i:02d}_execution.json").write_text(
            json.dumps(cycle, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["cycles_done"] = i
        if crashed:
            summary["crash_how"] = how
            summary["crash_cycle"] = i
            break
        if cycle.get("error"):
            # 送不出礼物（大概率余额不足）→ 继续无意义，提前终止
            summary["status"] = "ERROR"
            summary["error"] = f"cycle{i}: {cycle['error']}（检查余额是否充足）"
            break
        # 回到前台准备下一轮
        _launch(serial)

    # 末轮后静默等待 finalize 超时引爆（特征窗口最长 300s）
    if not crashed and summary["status"] != "ERROR":
        deadline = time.time() + settle_wait
        while time.time() < deadline:
            time.sleep(15)
            crashed, how = _check_crash(serial, base_pid)
            if crashed:
                summary["crash_how"] = how
                summary["crash_cycle"] = f"settle(+{int(settle_wait - (deadline - time.time()))}s)"
                break

    if crashed:
        summary["crash_found"] = True
        summary["status"] = "CRASH_REPRODUCED"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (root / f"crash_logcat_{ts}.txt").write_text(
            _adb(serial, "logcat", "-d", "-b", "crash", timeout=30), encoding="utf-8")
        _adb(serial, "shell", "screencap", "-p", "/sdcard/__crash.png")
        shot = subprocess.run(["adb", "-s", serial, "pull", "/sdcard/__crash.png",
                               str(root / f"crash_screen_{ts}.png")],
                              capture_output=True, text=True, timeout=30)
        summary["evidence"] += [f"crash_logcat_{ts}.txt", f"crash_screen_{ts}.png"]
        summary["evidence_pull"] = (shot.stdout or "").strip()

    (root / "stress_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return (1 if crashed else (2 if summary["status"] == "ERROR" else 0)), summary


def main() -> int:
    ap = argparse.ArgumentParser(description="A 项目礼物特效 finalize 死锁复现")
    ap.add_argument("--project", default="a")
    ap.add_argument("--env", default="test")
    ap.add_argument("--cycles", type=int, default=10)
    ap.add_argument("--settle-wait", type=int, default=300,
                    help="末轮后等待 FinalizerWatchdog 引爆的秒数（默认300）")
    ap.add_argument("--evidence-dir", default=None)
    ap.add_argument("--combo", type=int, default=7, help="每轮连送次数触发 combo→PAG 全屏特效（MongoDB batch_num_levels=[2,4,6]，推荐 7）")
    args = ap.parse_args()

    from core.config import loader
    env_cfg = loader.load_env(args.project, args.env)
    rc, summary = run(env_cfg, args.evidence_dir, args.cycles, args.settle_wait, args.combo)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main())
