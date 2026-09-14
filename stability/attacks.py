# -*- coding: utf-8 -*-
"""攻击思维层（第二步）—— 从「业务测试点」派生攻击用例。

对每个业务点自动追问：连续/重复/改参/越权/重放/断网/切后台/并发/退出/杀进程。
把用户给的 A01-A10 形式化为 AttackCase 元数据，标注可执行性与所需基建。

每种攻击的执行原语在 stability/actor.py / replay 里已具备一部分；
标「需sign」的表示要能验证业务成功态需要重算签名（当前自动化的唯一闸门）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AttackCase:
    id: str
    title: str
    victim: str                # 攻击目标（业务点）
    action_seq: list[str]      # 动作原语序列
    kind: str                  # 连续/重复/改参/越权/重放/断网/切后台/并发/退出/杀进程
    feasibility: str           # executable / needs_sign / needs_infra
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "victim": self.victim,
            "kind": self.kind, "feasibility": self.feasibility,
            "action_seq": self.action_seq, "notes": self.notes,
        }


def build_attack_catalog(victim: str = "发送红包") -> list[AttackCase]:
    return [
        AttackCase("A01", "连续快速点击发送", victim,
                   ["BURST_TAP:*sendelement*"], "连续", "executable",
                   "UI 连点发送按钮，看是否重复发/卡死/闪退"),
        AttackCase("A02", "100次重复请求", victim,
                   ["REPLAY:100"], "重复", "executable",
                   "同一抓包原样回放 100 次，兜底防重放/幂等（ret=-1 是预期观测）"),
        AttackCase("A03", "修改金额参数", victim,
                   ["MUTATE_BODY:coins"], "改参", "needs_sign",
                   "改 coins/quantity 后要重算 sign 才能验证业务成功态"),
        AttackCase("A04", "修改用户MID", victim,
                   ["MUTATE_ZYP:mid"], "越权", "needs_sign",
                   "换 zyp/body 的 mid 越权，受 sign 校验限制"),
        AttackCase("A05", "请求重放", victim,
                   ["REPLAY:1"], "重放", "executable",
                   "字节级原样重放一次（capture_replay 已实现）"),
        AttackCase("A06", "网络断开后恢复", victim,
                   ["NET_OFF", "TAP:*sendelement*", "NET_ON"], "断网",
                   "executable",
                   "飞行模式断开→点击发送→恢复，验证失败处理与重试"),
        AttackCase("A07", "发送过程中切后台", victim,
                   ["TAP:*sendelement*", "BACKGROUND", "FOREGROUND"], "切后台",
                   "executable",
                   "发红包瞬间切后台再恢复（BACKGROUND 原语已实现）"),
        AttackCase("A08", "多用户同时发送", victim,
                   ["CONCURRENCY:2accounts"], "并发", "needs_infra",
                   "需多账号并行（账号库已有 9 个可登录账号，但换 token 发需 sign）"),
        AttackCase("A09", "接收方退出", victim,
                   ["EXPRESS:receiver_exit"], "退出", "needs_infra",
                   "需双端/多账号状态协调基建"),
        AttackCase("A10", "App杀死后重新进入", victim,
                   ["KILL_APP", "RELAUNCH", "TAP:*sendelement*"], "杀进程",
                   "executable",
                   "am force-stop + am start 后重发，验证状态恢复/会话"),
    ]


def executable_attacks() -> list[AttackCase]:
    return [a for a in build_attack_catalog() if a.feasibility == "executable"]


def by_kind(kind: str) -> list[AttackCase]:
    return [a for a in build_attack_catalog() if a.kind == kind]


if __name__ == "__main__":
    import json
    cat = build_attack_catalog()
    print("攻击用例总数:", len(cat))
    byf: dict[str, int] = {}
    for a in cat:
        byf[a.feasibility] = byf.get(a.feasibility, 0) + 1
    print("可行性分布:", byf)
    print(json.dumps([a.to_dict() for a in cat], ensure_ascii=False, indent=2)[:1200])