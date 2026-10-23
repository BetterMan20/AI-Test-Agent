# -*- coding: utf-8 -*-
"""业务码归因：回放业务码(replayed_ret)相对抓包业务码(captured_ret)的确定性分类。

分层语义（协议层 ≠ 业务层）：
  协议层 status_code → 硬断言，决定步骤 pass/fail（HTTP 可达性）
  业务层 ret         → 观察项，归因后呈现；环境归因(凭证失效/防重放/限频)
                       是有效业务状态观察，不判产品缺陷，不计 TC 失败
"""
from __future__ import annotations

VERDICT_REPRODUCED = "reproduced"            # 回放码与抓包一致，业务复现
VERDICT_AUTH_EXPIRED = "auth_expired"        # ret=-11 凭证失效（环境）
VERDICT_ANTI_REPLAY = "anti_replay"          # ret=-1 后端防重放（环境）
VERDICT_RATE_LIMITED = "rate_limited"        # ret=-101 频率限制（环境）
VERDICT_NO_RESPONSE = "no_response"          # 回放响应无业务码可提取
VERDICT_BUSINESS_MISMATCH = "business_mismatch"  # 不属已知归因，疑似业务异常

VERDICT_NOTES = {
    VERDICT_REPRODUCED: "业务复现（回放业务码与抓包一致）",
    VERDICT_AUTH_EXPIRED: "凭证失效（ret=-11 Authorization code error），需刷新登录态后重跑，属环境归因",
    VERDICT_ANTI_REPLAY: "后端防重放（ret=-1），同一抓包字节重复提交被拒，属有效业务观察",
    VERDICT_RATE_LIMITED: "频率限制（ret=-101），属有效业务观察",
    VERDICT_NO_RESPONSE: "回放响应中未提取到业务码",
    VERDICT_BUSINESS_MISMATCH: "业务码不符且不属于已知环境归因，疑似业务异常，需人工排查",
}

# 环境归因集合：不判产品缺陷的已知业务状态
ENV_VERDICTS = {VERDICT_AUTH_EXPIRED, VERDICT_ANTI_REPLAY, VERDICT_RATE_LIMITED}


def classify_business_verdict(captured_ret, replayed_ret) -> str:
    """由抓包业务码与回放业务码确定归因（纯函数，无 LLM）。"""
    if replayed_ret is None:
        return VERDICT_NO_RESPONSE
    if captured_ret == replayed_ret:
        return VERDICT_REPRODUCED
    if replayed_ret == -11:
        return VERDICT_AUTH_EXPIRED
    if replayed_ret == -1:
        return VERDICT_ANTI_REPLAY
    if replayed_ret == -101:
        return VERDICT_RATE_LIMITED
    return VERDICT_BUSINESS_MISMATCH


def verdict_note(verdict: str) -> str:
    return VERDICT_NOTES.get(verdict, f"未知归因: {verdict}")
