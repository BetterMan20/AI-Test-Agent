# -*- coding: utf-8 -*-
"""A 项目 PAG 礼物特效压力测试（完整闭环版本）。

前置条件自动化：
  1. DB 查询 10 个金币充足账户（可选，当前只用到真机登录的 1 个）
  2. DB 自动补金币：user_wallet_ht SET balance = 1000000
  3. 自动进房：Explore tab → 选有人的房间 → Join
  4. 自动上麦：点击空麦位占座
  5. 礼物压力循环：多人上麦 → combo 送礼 → 播放中退房
  6. Crash 恢复：检测 FinalizerWatchdog 崩溃 → 等 App 重启 → 继续下一轮

用法：
  python -m projects.a.adapters.pag_pressure --cycles 10 --combo 10
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
import pymysql

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PACKAGE = "com.st.game.android"
USER_ID = 20337846
CRASH_SIG = "PAGAnimator.finalize() timed out"
EVIDENCE_ROOT = Path("output") / "evidence_a_pressure"

MAIN_ACTIVITY = "com.tg.ui.home.MainActivity"
ROOM_ACTIVITY = "com.tg.room.LiveRoomActivity"


# ================================================================
# DB 层（补金币）
# ================================================================
def _db():
    return pymysql.connect(
        host=os.environ["A_DB_HOST"],
        port=int(os.environ["A_DB_PORT"]),
        user=os.environ["A_DB_USER"],
        password=os.environ["A_DB_PASSWORD"],
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        connect_timeout=10,
        read_timeout=10,
    )


def ensure_coins(target: int = 1_000_000, user_id: int = USER_ID) -> int:
    """确保 user_id 的金币余额 >= target；不够就直接 UPDATE。返回补到的余额。"""
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT balance FROM `wallet-engine`.user_wallet_ht "
                "WHERE user_id=%s AND currency_type=1",
                (user_id,),
            )
            rows = cur.fetchall()
            cur_balance = int(rows[0]["balance"]) if rows else 0
            if cur_balance < target:
                cur.execute(
                    "UPDATE `wallet-engine`.user_wallet_ht SET balance=%s "
                    "WHERE user_id=%s AND currency_type=1",
                    (target, user_id),
                )
                return target
            return cur_balance


def top_coin_accounts(limit: int = 10) -> list[dict]:
    """查询金币余额充足的活跃账户。"""
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, balance, frozen_amount, updated_at "
                "FROM `wallet-engine`.user_wallet_ht "
                "WHERE currency_type=1 AND balance > 1000 "
                "ORDER BY balance DESC LIMIT %s",
                (limit,),
            )
            return cur.fetchall()


# ================================================================
# ADB 基础
# ================================================================
def _adb(serial: str, *args: str, timeout: int = 15) -> str:
    try:
        r = subprocess.run(
            ["adb", "-s", serial, *args],
            capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
        )
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f"__ADB_ERROR__ {e}"


def _tap(serial: str, x: int, y: int) -> None:
    _adb(serial, "shell", "input", "tap", str(x), str(y))


def _pid(serial: str) -> str:
    return _adb(serial, "shell", "pidof", PACKAGE).strip()


def _current_activity(serial: str) -> str:
    out = _adb(serial, "shell", "dumpsys", "activity", "activities")
    for line in out.split("\n"):
        if "mResumedActivity" in line:
            m = re.search(r"([\w.]+/[\w.]+)", line)
            if m:
                return m.group(1)
    return ""


def _dump_ui(serial: str) -> ET.Element | None:
    _adb(serial, "shell", "uiautomator", "dump", "/sdcard/__ui.xml")
    raw = _adb(serial, "shell", "cat", "/sdcard/__ui.xml")
    start, end = raw.find("<?xml"), raw.rfind("</hierarchy>")
    if start < 0 or end < 0:
        return None
    try:
        return ET.fromstring(raw[start : end + len("</hierarchy>")])
    except ET.ParseError:
        return None


def _find_by_id(root: ET.Element, suffix: str) -> ET.Element | None:
    for n in root.iter("node"):
        if (n.get("resource-id") or "").endswith(suffix):
            return n
    return None


def _find_by_text(root: ET.Element, text: str) -> ET.Element | None:
    for n in root.iter("node"):
        if (n.get("text") or "") == text:
            return n
    return None


def _bounds_center(bounds: str) -> tuple[int, int] | None:
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return ((x1 + x2) // 2, (y1 + y2) // 2)


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
    return (int(m.group(1)), int(m.group(2))) if m else (1080, 2318)


# ================================================================
# App 启动 / 状态恢复
# ================================================================
def wake_and_launch(serial: str) -> str:
    """唤醒 → 解锁 → monkey 拉起 App，返回当前 Activity。"""
    _adb(serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
    time.sleep(0.5)
    w, h = _screen_size(serial)
    _adb(serial, "shell", "input", "swipe", str(w // 2), str(int(h * 0.8)),
         str(w // 2), str(int(h * 0.3)))
    time.sleep(0.5)
    _adb(serial, "shell", "monkey", "-p", PACKAGE,
         "-c", "android.intent.category.LAUNCHER", "1", timeout=10)
    # 等主界面或登录页或房间出现
    for _ in range(25):
        time.sleep(1)
        act = _current_activity(serial)
        if act and (MAIN_ACTIVITY in act or ROOM_ACTIVITY in act or "tg.ui" in act):
            return act
    return _current_activity(serial)


def wait_recovery(serial: str, timeout: int = 60) -> str:
    """crash 后等待 App 自动重启或系统恢复，返回最终 Activity。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        act = _current_activity(serial)
        if PACKAGE in act:
            # 等一下再确认不是 crash 中间态
            time.sleep(2)
            act2 = _current_activity(serial)
            if PACKAGE in act2:
                return act2
        time.sleep(2)
    # 超时，手动拉起
    return wake_and_launch(serial)


# ================================================================
# 进房逻辑
# ================================================================
def _tap_bottom_tab(serial: str, texts: set[str]) -> bool:
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


ROOM_TAB_TEXTS = {"الغرف", "Rooms"}  # RTL: الغرف = Rooms (底部第二个)
GAME_TAB_TEXTS = {"الألعاب", "Games"}
ROOM_ACTIVE_TAB_TEXTS = {"استكشاف", "Explore"}  # 房间子 tab


def ensure_in_room(serial: str) -> bool:
    """确保在直播间内；不在就：force-stop 冷启动回主页 → Rooms tab → 进第一个有人的房间。"""
    if ROOM_ACTIVITY in _current_activity(serial):
        return True

    # 退房后 App 可能停在搜索页/游戏页等任意 Activity（返回栈不可控），
    # Back 循环和 monkey 前台拉起都不可靠，直接冷启动最稳
    _adb(serial, "shell", "am", "force-stop", PACKAGE)
    time.sleep(2)
    wake_and_launch(serial)
    time.sleep(2)

    # 切到 Rooms tab
    _tap_bottom_tab(serial, ROOM_TAB_TEXTS)
    time.sleep(3)

    for attempt in range(2):
        root = _dump_ui(serial)
        if root is None:
            continue

        # 确保在 Explore 子 tab（如果有）
        explore = _find_by_text(root, "استكشاف")
        if explore is None:
            explore = _find_by_text(root, "Explore")
        if explore is not None:
            _tap_node(serial, explore)
            time.sleep(2.5)
            root = _dump_ui(serial)

        if root is None:
            continue

        # 方式 1：点 btnJoin（别人房间卡上的 Join 按钮）
        join_btn = _find_by_id(root, "btnJoin")
        if join_btn is not None and _tap_node(serial, join_btn):
            for _ in range(10):
                time.sleep(1)
                if ROOM_ACTIVITY in _current_activity(serial):
                    return True
            continue

        # 方式 2：点第一个房间卡
        titles = [n for n in root.iter("node")
                  if (n.get("resource-id") or "").endswith("tvTitle") and (n.get("bounds") or "")]
        if titles:
            if _tap_node(serial, titles[0]):
                for _ in range(10):
                    time.sleep(1)
                    if ROOM_ACTIVITY in _current_activity(serial):
                        return True

        if attempt == 0:
            time.sleep(3)
    return False


# ================================================================
# 上麦逻辑
# ================================================================
def ensure_on_mic(serial: str) -> bool:
    """尝试占据一个空麦位。"""
    root = _dump_ui(serial)
    if root is None:
        return False

    # 找 micItem1-8，挑一个没有 ivOwner 的（空的）
    empty_slots: list[ET.Element] = []
    for rid_num in range(1, 9):
        slot = _find_by_id(root, f"micItem{rid_num}")
        if slot is None:
            continue
        # 检查这个 slot 有没有 ivOwner 或 ivAvatar（= 已有人）
        has_owner = any(
            (c.get("resource-id") or "").endswith("ivOwner")
            for c in slot.iter("node")
        )
        if not has_owner:
            empty_slots.append(slot)

    if not empty_slots:
        return False

    # 选第一个空麦位
    target = empty_slots[0]
    if not _tap_node(serial, target):
        return False

    time.sleep(2)
    # 可能弹出上麦确认按钮（阿拉伯语 "انضمام للميكروفون" / "Join Mic"）
    root = _dump_ui(serial)
    if root is None:
        return True
    for confirm_text in ["انضمام", "انضمام للميكروفون", "Join", "Join Mic", "OK", "تأكيد"]:
        btn = _find_by_text(root, confirm_text)
        if btn is not None and _tap_node(serial, btn):
            time.sleep(1)
            return True
    return True  # 点空麦位没弹确认 = 直接上麦了


# ================================================================
# 礼物压力
# ================================================================
def send_combo_gift(serial: str, combo: int = 10) -> dict:
    """房间内：打开礼物 → All recipient → 最便宜礼物 → combo 连送。"""
    meta: dict = {"gift": {}, "sent": 0, "steps": []}

    # 确认在房间内
    act = _current_activity(serial)
    if ROOM_ACTIVITY not in act:
        meta["error"] = f"不在房间内: {act}"
        return meta

    root = _dump_ui(serial)
    if root is None:
        meta["error"] = "dump 失败"
        return meta

    btn_gift = _find_by_id(root, "btnGift")
    if btn_gift is None:
        meta["error"] = "未找到 btnGift"
        return meta
    _tap_node(serial, btn_gift)
    meta["steps"].append("tap_btnGift")
    time.sleep(4)  # 等面板 fully render

    root = _dump_ui(serial)
    if root is None:
        meta["error"] = "礼物面板 dump 失败"
        return meta

    # 选所有接收人
    all_recip = _find_by_id(root, "tvSelectAllRecipients")
    if all_recip is not None:
        _tap_node(serial, all_recip)
        meta["steps"].append("select_all_recipients")
        time.sleep(1.5)

    # 找最便宜的礼物
    prices, names = [], []
    for n in root.iter("node"):
        rid = n.get("resource-id") or ""
        if rid.endswith("tvGiftPrice"):
            p = int(re.sub(r"\D", "", n.get("text") or "0") or 0)
            prices.append((p, n.get("bounds")))
        if rid.endswith("tvGiftName"):
            names.append(n)
    if not prices or not names:
        meta["error"] = f"礼物列表为空 prices={len(prices)} names={len(names)}"
        return meta

    min_price, pb = min(prices, key=lambda t: t[0])
    py = _bounds_center(pb)[1]
    target = min(names, key=lambda n: abs((_bounds_center(n.get("bounds")) or (0, 0))[1] - py))
    meta["gift"] = {"price": min_price, "name": target.get("text") or ""}
    _tap_node(serial, target)
    meta["steps"].append(f"pick_gift={meta['gift']['name']}")
    time.sleep(1.5)

    # 重新 dump 找 Send 按钮（选礼物后面板可能刷新）
    root = _dump_ui(serial)
    send_node = _find_by_id(root, "tvGiftSend") if root is not None else None
    if send_node is None:
        meta["error"] = "未找到 tvGiftSend"
        return meta

    sx, sy = _bounds_center(send_node.get("bounds"))
    meta["steps"].append(f"send_btn=({sx},{sy})")
    sent = 0
    for i in range(combo):
        _adb(serial, "shell", "input", "tap", str(sx), str(sy))
        sent += 1
        time.sleep(0.6)
    meta["sent"] = sent
    meta["steps"].append(f"sent={sent}")
    return meta


def exit_room_during_playback(serial: str) -> None:
    """播放中退房 → 触发 onAnimationCancel → finalize。"""
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


def check_crash(serial: str, base_pid: str) -> tuple[bool, str]:
    crash = _adb(serial, "logcat", "-d", "-b", "crash", timeout=30)
    if CRASH_SIG in crash:
        return True, "signature"
    now = _pid(serial)
    if not now or now != base_pid:
        time.sleep(2)
        now2 = _pid(serial)
        if not now2 or now2 != base_pid:
            return True, f"process_died({base_pid}->{now2 or 'gone'})"
    return False, ""


# ================================================================
# 主流程
# ================================================================
def run(
    env_cfg=None,
    evidence_dir: str | None = None,
    cycles: int = 10,
    combo: int = 10,
    settle_wait: int = 0,
) -> tuple[int, dict]:
    root = Path(evidence_dir) if evidence_dir else EVIDENCE_ROOT
    root.mkdir(parents=True, exist_ok=True)

    serial = getattr(env_cfg, "device_serial", "") if env_cfg else ""
    if not serial:
        # 从 a-test.yaml 的默认值
        serial = "e5c839cf"

    state = _adb(serial, "get-state", timeout=5)
    if "device" not in state.replace("daemon started", ""):
        return 2, {"status": "ERROR", "error": f"设备 {serial} 不在线"}

    summary: dict = {
        "status": "PASS",
        "cycles_done": 0,
        "crashes": 0,
        "package": PACKAGE,
        "device": serial,
        "user_id": USER_ID,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "coins_preflight": ensure_coins(1_000_000),
        "account_pool_size": len(top_coin_accounts(10)),
    }

    for i in range(1, cycles + 1):
        t0 = time.time()
        entry: dict = {"cycle": i, "start": datetime.now().isoformat(timespec="seconds")}

        # 清 crash buffer（避免读到上一轮或旧 crash）
        _adb(serial, "logcat", "-b", "crash", "-c", timeout=5)
        _adb(serial, "logcat", "-c", timeout=5)

        # --- 确保在房间内 ---
        if ROOM_ACTIVITY not in _current_activity(serial):
            entry["room_enter"] = ensure_in_room(serial)

        # --- 确保有麦 ---
        entry["on_mic"] = ensure_on_mic(serial)

        # --- 记录 base_pid ---
        base_pid = _pid(serial)
        entry["base_pid"] = base_pid

        # --- 礼物循环 ---
        entry["gift"] = send_combo_gift(serial, combo=combo)

        # --- 退房触发 finalize ---
        if "error" not in entry["gift"]:
            exit_room_during_playback(serial)
            entry["exit"] = "ok"
        else:
            entry["exit"] = "skipped(gift_error)"

        # --- 退后台 + GC ---
        _adb(serial, "shell", "input", "keyevent", "3")
        time.sleep(2)
        if base_pid:
            _adb(serial, "shell", "am", "send-trim-memory", base_pid, "80")

        # --- 等待 finalize 窗口 ---
        if settle_wait > 0:
            deadline = time.time() + settle_wait
            while time.time() < deadline:
                time.sleep(15)
                crashed, how = check_crash(serial, base_pid)
                if crashed:
                    break

        # --- 检查 crash ---
        crashed, how = check_crash(serial, base_pid)
        entry["crash"] = crashed
        entry["crash_how"] = how
        entry["cost_s"] = round(time.time() - t0, 1)

        (root / f"cycle_{i:02d}.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary["cycles_done"] = i
        if crashed:
            summary["crashes"] += 1
            # 采证
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            crash_log = _adb(serial, "logcat", "-d", "-b", "crash", timeout=30)
            (root / f"crash_{i:02d}_{ts}.txt").write_text(crash_log, encoding="utf-8")
            _adb(serial, "shell", "screencap", "-p", "/sdcard/__crash.png")
            subprocess.run(
                ["adb", "-s", serial, "pull", "/sdcard/__crash.png",
                 str(root / f"crash_screen_{i:02d}_{ts}.png")],
                capture_output=True, text=True, timeout=30,
            )
            # 等待恢复
            wait_recovery(serial)
            # 补金币（可能 crash 丢失 session）
            summary["coins_after_crash"] = ensure_coins(1_000_000)

    summary["status"] = "CRASH_REPRODUCED" if summary["crashes"] > 0 else "PASS"
    summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
    (root / "pressure_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return (0 if summary["status"] == "PASS" else 1), summary


def main() -> int:
    ap = argparse.ArgumentParser(description="A 项目 PAG 礼物特效压力测试（完整闭环）")
    ap.add_argument("--project", default="a")
    ap.add_argument("--env", default="test")
    ap.add_argument("--cycles", type=int, default=10)
    ap.add_argument("--combo", type=int, default=10)
    ap.add_argument("--settle-wait", type=int, default=0,
                    help="每轮后等待 finalize 引爆的秒数")
    ap.add_argument("--evidence-dir", default=None)
    args = ap.parse_args()

    from core.config import loader
    env_cfg = loader.load_env(args.project, args.env)
    rc, summary = run(env_cfg, args.evidence_dir, args.cycles, args.combo, args.settle_wait)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main())
