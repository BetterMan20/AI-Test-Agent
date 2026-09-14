# -*- coding: utf-8 -*-
"""账号健康度巡检（方案2：素材库 + 自动巡检，无需 sign 算法）。

思路：抓包库既是「可执行回归素材」，也是「测试账号登记簿」。
通过原样回放每个账号的登录样本(login_by_verify_code)，判定：
  - 该账号授权是否仍有效（replayed_ret 是否复现抓包时的 ret）
  - 最新 token 前缀 / mid（供后续判断发红包样本是否需要重抓）
并把「可续登录账号」与「发红包样本(mid from zyp)」关联，标出孤儿发送样本。

注意：probe_login=True 时会对每个账号真实回放一次登录接口，会刷新/重登该账号
会话。巡检每个账号仅一次，测试环境视为可接受。
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from replay.capture_replay import CaptureReplay


@dataclass
class AccountHealth:
    phone: str = ""
    mid: str = ""                       # 最近一次登录回放返回的 mid
    login_samples: int = 0              # 该账号成功登录抓包样本数
    latest_login_ts: int | None = None
    latest_send_ts: int | None = None
    send_samples: int = 0               # 该账号(mid) 发红包样本数
    login_ret: Any = None               # 最近一次原样回放登录的 replayed_ret
    login_state: str = "unknown"        # login_pass / login_fail / not_probed
    new_token_prefix: str = ""          # 回放后服务端返回的最新 token 前缀
    status: str = "unknown"             # ok / login_fail / no_send / orphan
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phone": self.phone,
            "mid": self.mid,
            "login_samples": self.login_samples,
            "latest_login_ts": self.latest_login_ts,
            "latest_send_ts": self.latest_send_ts,
            "send_samples": self.send_samples,
            "login_ret": self.login_ret,
            "login_state": self.login_state,
            "new_token_prefix": self.new_token_prefix,
            "status": self.status,
            "notes": self.notes,
        }


class AccountHealthChecker:
    def __init__(
        self,
        capture_dir: str | Path,
        evidence_root: str | Path = "output/evidence_account_health",
        endpoint_login: str = "login_by_verify_code",
        endpoint_send: str = "send_red_packet",
    ) -> None:
        self._capture = CaptureReplay(capture_dir, evidence_root)
        self._evidence_root = str(evidence_root)
        self._login_kw = endpoint_login
        self._send_kw = endpoint_send
        # 一次性扫描缓存，避免逐账号重复全目录 grep
        self._login_samples = [e for e in self._capture.scan(endpoint_login)
                               if e.status_code == 200]
        self._send_samples = [e for e in self._capture.scan(endpoint_send)]

    # ── 采集：把抓包样本按账号归类 ──────────────────────
    def _phone_of(self, sample) -> str:
        try:
            d = json.loads(sample.req_body_raw)
            return str(d.get("phone") or "")
        except Exception:
            return ""

    def _mid_of_zyp(self, sample) -> str:
        zyp = (sample.req_headers or {}).get("zyp", "")
        if zyp.startswith("mid="):
            return zyp[4:]
        return ""

    def _collect_accounts(self) -> list[AccountHealth]:
        by_phone: dict[str, list] = defaultdict(list)
        for e in self._login_samples:
            p = self._phone_of(e)
            if p:
                by_phone[p].append(e)
        accounts: list[AccountHealth] = []
        for phone, samples in sorted(by_phone.items()):
            a = AccountHealth(phone=phone, login_samples=len(samples))
            a.latest_login_ts = max(s.timestamp or 0 for s in samples)
            accounts.append(a)
        return accounts

    def _link_sends(self, accounts: list[AccountHealth]) -> list[dict[str, Any]]:
        by_mid = {a.mid: a for a in accounts if a.mid}
        orphan_sends: list[dict[str, Any]] = []
        mid_groups: dict[str, list] = defaultdict(list)
        for e in self._send_samples:
            m = self._mid_of_zyp(e)
            if m:
                mid_groups[m].append(e)
        for mid, samples in sorted(mid_groups.items()):
            acct = by_mid.get(mid)
            if acct is not None:
                acct.send_samples += len(samples)
                acct.latest_send_ts = max(s.timestamp or 0 for s in samples)
            else:
                orphan_sends.append({
                    "mid": mid,
                    "send_samples": len(samples),
                    "example_token_prefix": _token_prefix_of(samples[0]),
                })
        return orphan_sends

    # ── 巡检：对每个账号原样回放一次登录 ─────────────────
    def _probe(self, a: AccountHealth) -> None:
        samples = [e for e in self._login_samples if self._phone_of(e) == a.phone]
        if not samples:
            a.login_state = "not_probed"
            a.notes.append("无成功登录样本可巡检")
            return
        latest = max(samples, key=lambda s: s.timestamp or 0)
        out = self._capture.run(
            latest,
            tc_id=f"TC-HLTH-{a.phone[-4:]}",
            title=f"账号健康巡检 {a.phone}",
            include_meta=True,
        )
        a.login_ret = out.replayed_ret
        if isinstance(out.body, dict):
            data = out.body.get("data") or {}
            a.mid = str(data.get("mid") or a.mid)
            a.new_token_prefix = str(data.get("token") or "")[:8]
        if out.replayed_ret == latest.res_ret:
            a.login_state = "login_pass"
            a.notes.append("登录复现成功，账号授权可用")
        else:
            a.login_state = "login_fail"
            a.notes.append(
                f"登录未能复现业务码(期望{latest.res_ret}，实得{out.replayed_ret})，"
                "授权可能已失效，建议重新抓包"
            )

    def _finalize_status(self, a: AccountHealth) -> None:
        if a.login_state != "login_pass":
            a.status = "login_fail"
        elif a.send_samples == 0:
            a.status = "no_send"
            a.notes.append("有可用登录，但抓包库无对应发红包样本")
        else:
            a.status = "ok"
            a.notes.append("登录可用且有发红包样本（样本时效仍取决于抓包时间）")

    def run(self, probe_login: bool = True) -> dict[str, Any]:
        accounts = self._collect_accounts()
        if probe_login:
            for a in accounts:
                self._probe(a)
        # 发红包样本(mid)关联需在 probe 拿到真实 mid 之后
        orphan_sends = self._link_sends(accounts)
        for a in accounts:
            self._finalize_status(a)

        report = {
            "run_time": time.strftime("%Y-%m-%d %H:%M:%S %z"),
            "probe_login": probe_login,
            "accounts": [a.to_dict() for a in accounts],
            "send_orphans": orphan_sends,
            "summary": {
                "accounts": len(accounts),
                "login_pass": sum(1 for a in accounts if a.login_state == "login_pass"),
                "login_fail": sum(1 for a in accounts if a.login_state == "login_fail"),
                "with_send": sum(1 for a in accounts if a.send_samples > 0),
                "orphan_sends": len(orphan_sends),
            },
        }
        root = Path(self._evidence_root)
        root.mkdir(parents=True, exist_ok=True)
        save = root / "account_health.json"
        save.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        report["output_path"] = str(save)
        return report


def _token_prefix_of(sample) -> str:
    try:
        d = json.loads(sample.req_body_raw)
        return str(d.get("token") or "")[:8]
    except Exception:
        return ""