"""API Capability — API 知识库.

统一 Whistle 抓包 + Swagger 文档为单一 API 目录,
为 TC→Plan 转换器提供 API 知识上下文.

用法:
    cap = APICapability()
    cap.load_from_whistle("D:/higo-api")
    cap.load_from_swagger("knowledge/swagger/higo.json")

    # 查询
    endpoints = cap.search("gift")
    ep = cap.get("/live/gift/send_gift")

    # 给 LLM 用
    prompt_fragment = cap.to_prompt(keywords=["gift", "wallet"])
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass
class APIEndpoint:
    """单个 API 端点的完整知识."""

    endpoint: str
    method: str = "POST"
    description: str = ""
    base_url: str = ""

    # 请求知识
    req_params: dict[str, Any] = field(default_factory=dict)
    req_body_schema: dict[str, Any] = field(default_factory=dict)
    req_sample: dict[str, Any] | None = None
    req_headers: dict[str, str] = field(default_factory=dict)

    # 响应知识
    res_status_code: int = 200
    res_body_schema: dict[str, Any] = field(default_factory=dict)
    res_sample: dict[str, Any] | None = None

    # 元数据
    tags: list[str] = field(default_factory=list)
    source: str = "unknown"
    capture_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "method": self.method,
            "description": self.description,
            "base_url": self.base_url,
            "req_params": self.req_params,
            "req_body_schema": self.req_body_schema,
            "req_sample": self.req_sample,
            "res_status_code": self.res_status_code,
            "res_body_schema": self.res_body_schema,
            "res_sample": self.res_sample,
            "tags": self.tags,
            "source": self.source,
            "capture_count": self.capture_count,
        }

    def to_prompt(self) -> str:
        """生成给 LLM 的知识片段。"""
        lines = [
            f"### {self.method} {self.endpoint}",
        ]
        if self.description:
            lines.append(f"描述: {self.description}")
        if self.tags:
            lines.append(f"标签: {', '.join(self.tags)}")

        if self.req_body_schema:
            fields = list(self.req_body_schema.keys())
            lines.append(f"请求字段: {', '.join(fields[:15])}")
        if self.req_sample:
            sample_keys = list(self.req_sample.keys())[:10]
            lines.append(f"请求示例字段: {', '.join(sample_keys)}")

        if self.res_sample:
            lines.append(f"响应示例: {json.dumps(self.res_sample, ensure_ascii=False)[:200]}")

        lines.append("")
        return "\n".join(lines)


class APICapability:
    """API 知识库 — 统一 Whistle + Swagger."""

    def __init__(self) -> None:
        self._endpoints: dict[str, APIEndpoint] = {}

    # ── 加载 ──────────────────────────────────────────────

    def load_from_whistle(
        self,
        capture_dir: str | Path,
        max_files: int | None = None,
    ) -> int:
        """从 Whistle 抓包目录加载 API 知识。返回加载数量。"""
        from tools.whistle_parser import WhistleParser

        grouped = WhistleParser.find_endpoints(capture_dir)

        count = 0
        for endpoint, entries in grouped.items():
            cap = entries[0]
            req_body = cap.req_body or {}

            business_params = self._extract_business_params(req_body)
            res_body = cap.res_body if isinstance(cap.res_body, dict) else {}

            ep = APIEndpoint(
                endpoint=endpoint,
                method=cap.method,
                base_url=cap.base_url,
                req_params={},
                req_body_schema=business_params,
                req_sample=req_body,
                req_headers=cap.req_headers,
                res_status_code=cap.status_code,
                res_body_schema=self._infer_schema(res_body),
                res_sample=res_body,
                tags=self._infer_tags(endpoint, req_body),
                source="whistle",
                capture_count=len(entries),
            )
            self._endpoints[endpoint] = ep
            count += 1

        return count

    def load_from_swagger(self, swagger_path: str | Path) -> int:
        """从 Swagger/OpenAPI JSON 文件加载 API 知识。返回加载数量。"""
        path = Path(swagger_path)
        if not path.exists():
            return 0

        data = json.loads(path.read_text(encoding="utf-8"))
        base_url = ""
        servers = data.get("servers", [])
        if servers:
            base_url = servers[0].get("url", "")

        paths = data.get("paths", {})
        count = 0

        for path_str, methods in paths.items():
            for method, spec in methods.items():
                method = method.upper()
                endpoint = path_str

                req_body_schema = {}
                req_body = spec.get("requestBody", {})
                if req_body:
                    content = req_body.get("content", {})
                    json_spec = content.get("application/json", {})
                    req_body_schema = json_spec.get("schema", {}).get("properties", {})

                res_schema = {}
                responses = spec.get("responses", {})
                ok_resp = responses.get("200", {})
                if ok_resp:
                    content = ok_resp.get("content", {})
                    json_spec = content.get("application/json", {})
                    res_schema = json_spec.get("schema", {}).get("properties", {})

                tags = spec.get("tags", [])
                description = spec.get("summary", "") or spec.get("description", "")

                existing = self._endpoints.get(endpoint)
                if existing:
                    existing.description = description or existing.description
                    existing.req_body_schema = {
                        **existing.req_body_schema,
                        **req_body_schema,
                    }
                    existing.res_body_schema = {
                        **existing.res_body_schema,
                        **res_schema,
                    }
                    existing.tags = list(set(existing.tags + tags))
                    existing.source = "whistle+swagger" if existing.source == "whistle" else "swagger"
                else:
                    self._endpoints[endpoint] = APIEndpoint(
                        endpoint=endpoint,
                        method=method,
                        description=description,
                        base_url=base_url,
                        req_body_schema=req_body_schema,
                        res_body_schema=res_schema,
                        tags=tags,
                        source="swagger",
                    )
                count += 1

        return count

    # ── 查询 ──────────────────────────────────────────────

    def get(self, endpoint: str) -> APIEndpoint | None:
        return self._endpoints.get(endpoint)

    def search(self, keyword: str) -> list[APIEndpoint]:
        kw = keyword.lower()
        results = []
        for ep in self._endpoints.values():
            if (
                kw in ep.endpoint.lower()
                or any(kw in t.lower() for t in ep.tags)
                or kw in ep.description.lower()
            ):
                results.append(ep)
        return results

    def all(self) -> list[APIEndpoint]:
        return list(self._endpoints.values())

    def by_tag(self, tag: str) -> list[APIEndpoint]:
        tag_lower = tag.lower()
        return [ep for ep in self._endpoints.values() if tag_lower in [t.lower() for t in ep.tags]]

    # ── 导出 ──────────────────────────────────────────────

    def to_prompt(self, keywords: list[str] | None = None, max_endpoints: int = 30) -> str:
        """生成给 LLM TC→Plan 用的 API 知识 prompt 片段。"""
        if keywords:
            seen = set()
            selected = []
            for kw in keywords:
                for ep in self.search(kw):
                    if ep.endpoint not in seen:
                        seen.add(ep.endpoint)
                        selected.append(ep)
        else:
            selected = self.all()

        selected = selected[:max_endpoints]

        if not selected:
            return "（无可用 API 知识）\n"

        lines = ["## 可用 API 知识库\n"]
        for ep in selected:
            lines.append(ep.to_prompt())

        return "\n".join(lines)

    def to_json(self, path: str | Path) -> Path:
        """导出为 JSON 目录文件。"""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        data = {ep.endpoint: ep.to_dict() for ep in self._endpoints.values()}
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return out

    def __len__(self) -> int:
        return len(self._endpoints)

    # ── 内部工具 ──────────────────────────────────────────

    @staticmethod
    def _extract_business_params(body: dict[str, Any]) -> dict[str, Any]:
        """从请求 body 中提取业务字段（过滤掉 h_ 前缀的设备信息）。"""
        return {
            k: type(v).__name__
            for k, v in body.items()
            if not k.startswith("h_") and k != "token"
        }

    @staticmethod
    def _infer_schema(body: dict[str, Any]) -> dict[str, Any]:
        """从响应 body 推断 schema（字段名 → 类型名）。"""
        result: dict[str, Any] = {}
        for k, v in body.items():
            if isinstance(v, dict):
                result[k] = {sk: type(sv).__name__ for sk, sv in list(v.items())[:10]}
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                result[k] = [{"...": "object"}]
            else:
                result[k] = type(v).__name__
        return result

    @staticmethod
    def _infer_tags(endpoint: str, body: dict[str, Any]) -> list[str]:
        """从 endpoint 路径推断标签。"""
        parts = endpoint.strip("/").split("/")
        tags = []
        for p in parts:
            if p not in ("live", "api", "v1", "v2"):
                tags.append(p)

        if "gift" in endpoint:
            tags.append("gift")
        if "account" in endpoint or "wealth" in endpoint:
            tags.append("wallet")
        if "sign_in" in endpoint or "check_in" in endpoint:
            tags.append("engagement")
        if "room" in endpoint:
            tags.append("room")
        if "socialize" in endpoint:
            tags.append("social")

        return list(dict.fromkeys(tags))
