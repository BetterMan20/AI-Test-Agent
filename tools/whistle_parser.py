"""Whistle capture file parser — extracts API calls from Whistle proxy txt files."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs


@dataclass
class CapturedAPI:
    """A single captured API call from a Whistle proxy log."""

    url: str
    method: str
    req_headers: dict[str, str]
    req_body: dict[str, Any] | None
    status_code: int
    res_headers: dict[str, str]
    res_body: dict[str, Any] | str | None
    timestamp: int
    capture_id: str
    source_file: str
    req_body_raw: str | None = None
    res_ret: Any = None
    res_data_status: Any = None

    @property
    def base_url(self) -> str:
        parsed = urlparse(self.url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @property
    def path_with_query(self) -> str:
        parsed = urlparse(self.url)
        path = parsed.path
        if parsed.query:
            path += f"?{parsed.query}"
        return path

    @property
    def endpoint(self) -> str:
        parsed = urlparse(self.url)
        return parsed.path

    @property
    def query_params(self) -> dict[str, str]:
        parsed = urlparse(self.url)
        return {k: v[0] for k, v in parse_qs(parsed.query).items()}

    @property
    def is_success(self) -> bool:
        """启发式判定业务成功：HTTP<400 且 ret 非负、且（若含 data.status）为 0。

        注意：不同接口的成功码不同（本接口 ret=1 成功，ret=-1/-101 失败），
        因此这里只做“非业务错误码”的保守判定，绝不硬编码 0/1。
        """
        if self.status_code >= 400:
            return False
        ret = self.res_ret
        if ret is None:
            return True
        if isinstance(ret, (int, float)) and ret < 0:
            return False
        if isinstance(self.res_data_status, (int, float)) and self.res_data_status != 0:
            return False
        return True


SKIP_ENDPOINTS = {
    "/live/account/socialize_heartbeat",
    "/stat/action",
    "/stat/log",
    "/stat/track",
}


class WhistleParser:
    """Parse Whistle proxy capture files (.txt) into CapturedAPI objects."""

    @staticmethod
    def parse_file(file_path: str | Path) -> list[CapturedAPI]:
        """Parse a single Whistle capture file."""
        path = Path(file_path)
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, list):
            data = [data]

        results: list[CapturedAPI] = []
        for entry in data:
            parsed = WhistleParser._parse_entry(entry, str(path))
            if parsed is not None:
                results.append(parsed)
        return results

    @staticmethod
    def parse_directory(
        dir_path: str | Path,
        skip_endpoints: bool = True,
        max_files: int | None = None,
    ) -> list[CapturedAPI]:
        """Parse all .txt files in a directory."""
        path = Path(dir_path)
        txt_files = sorted(path.glob("*.txt"))
        if max_files:
            txt_files = txt_files[:max_files]

        results: list[CapturedAPI] = []
        for tf in txt_files:
            try:
                entries = WhistleParser.parse_file(tf)
                if skip_endpoints:
                    entries = [
                        e for e in entries
                        if e.endpoint not in SKIP_ENDPOINTS
                    ]
                results.extend(entries)
            except Exception:
                pass
        return results

    @staticmethod
    def find_endpoints(
        dir_path: str | Path,
        keywords: list[str] | None = None,
    ) -> dict[str, list[CapturedAPI]]:
        """Find and group API endpoints by path, optionally filtered by keywords."""
        all_entries = WhistleParser.parse_directory(dir_path)
        grouped: dict[str, list[CapturedAPI]] = {}

        for entry in all_entries:
            ep = entry.endpoint
            if keywords:
                ep_lower = ep.lower()
                if not any(kw.lower() in ep_lower for kw in keywords):
                    continue
            grouped.setdefault(ep, []).append(entry)

        return grouped

    @staticmethod
    def _parse_entry(entry: dict[str, Any], source: str) -> CapturedAPI | None:
        """Parse a single Whistle entry dict."""
        try:
            url = entry.get("url", "")
            if not url:
                return None

            req = entry.get("req", {})
            res = entry.get("res", {})

            method = req.get("method", "GET").upper()
            req_headers = req.get("headers", {})
            req_headers = WhistleParser._clean_headers(req_headers)

            req_body = WhistleParser._extract_body(req)
            res_body = WhistleParser._extract_body(res)

            status_code = res.get("statusCode", 0)

            # 业务码：响应 JSON 的顶层 ret 与（可选的）data.status；
            # 保留 req_body_raw 原始字符串，sign 是按原始字节计算的，回放须原样。
            res_ret = res_data_status = None
            if isinstance(res_body, dict):
                res_ret = res_body.get("ret")
                _data = res_body.get("data")
                if isinstance(_data, dict):
                    res_data_status = _data.get("status")

            return CapturedAPI(
                url=url,
                method=method,
                req_headers=req_headers,
                req_body=req_body,
                status_code=status_code,
                res_headers=res.get("headers", {}),
                res_body=res_body,
                timestamp=entry.get("startTime", 0),
                capture_id=entry.get("id", ""),
                source_file=source,
                req_body_raw=req.get("body"),
                res_ret=res_ret,
                res_data_status=res_data_status,
            )
        except Exception:
            return None

    @staticmethod
    def _skip_endpoints() -> set[str]:
        return SKIP_ENDPOINTS

    @staticmethod
    def _clean_headers(headers: dict[str, str]) -> dict[str, str]:
        """Remove proxy-specific headers that shouldn't be replayed."""
        skip = {"proxy-authorization", "connection", "content-length"}
        return {
            k: v for k, v in headers.items()
            if k.lower() not in skip
        }

    @staticmethod
    def _extract_body(container: dict[str, Any]) -> dict[str, Any] | None:
        """Extract and parse the body from a request or response container."""
        body_str = container.get("body")
        if not body_str:
            return None

        try:
            return json.loads(body_str)
        except (json.JSONDecodeError, TypeError):
            b64 = container.get("base64")
            if b64:
                try:
                    decoded = base64.b64decode(b64).decode("utf-8")
                    return json.loads(decoded)
                except Exception:
                    return None
            return body_str
