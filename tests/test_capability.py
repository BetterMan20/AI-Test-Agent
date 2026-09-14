"""Test — API Capability 知识库测试."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge.capability import APICapability, APIEndpoint


HIGO_API_DIR = Path(r"D:\higo-api")

_HAS_HIGO_DATA = HIGO_API_DIR.exists() and any(HIGO_API_DIR.glob("*.txt"))


@pytest.fixture()
def capability():
    if not _HAS_HIGO_DATA:
        pytest.skip("No .txt capture files in D:/higo-api")
    cap = APICapability()
    cap.load_from_whistle(HIGO_API_DIR, max_files=5)
    return cap


class TestAPICapabilityLoading:
    """Capability 加载测试."""

    def test_load_from_whistle(self):
        if not _HAS_HIGO_DATA:
            pytest.skip("No .txt capture files in D:/higo-api")
        cap = APICapability()
        count = cap.load_from_whistle(HIGO_API_DIR, max_files=5)
        assert count > 0
        assert len(cap) == count

    def test_endpoints_are_apiendpoint(self, capability):
        for ep in capability.all():
            assert isinstance(ep, APIEndpoint)

    def test_endpoints_have_endpoint_path(self, capability):
        for ep in capability.all():
            assert ep.endpoint.startswith("/")

    def test_endpoints_have_method(self, capability):
        for ep in capability.all():
            assert ep.method in ("GET", "POST", "PUT", "PATCH", "DELETE")

    def test_endpoints_have_source(self, capability):
        for ep in capability.all():
            assert ep.source == "whistle"

    def test_endpoints_have_tags(self, capability):
        tagged = [ep for ep in capability.all() if ep.tags]
        assert len(tagged) > 0

    def test_business_params_filtered(self, capability):
        """h_ 前缀字段被过滤。"""
        for ep in capability.all():
            for key in ep.req_body_schema:
                assert not key.startswith("h_")
                assert key != "token"

    def test_res_sample_parsed(self, capability):
        """至少有一个端点有响应示例。"""
        has_sample = any(ep.res_sample for ep in capability.all())
        assert has_sample


class TestAPICapabilitySearch:
    """Capability 搜索测试."""

    def test_search_by_keyword(self, capability):
        results = capability.search("gift")
        assert len(results) > 0
        for ep in results:
            assert "gift" in ep.endpoint.lower() or "gift" in [t.lower() for t in ep.tags]

    def test_search_returns_empty_for_unknown(self, capability):
        results = capability.search("nonexistent_keyword_xyz")
        assert len(results) == 0

    def test_search_wealth(self, capability):
        results = capability.search("wealth")
        assert len(results) > 0

    def test_get_by_endpoint(self, capability):
        all_eps = capability.all()
        if all_eps:
            ep = capability.get(all_eps[0].endpoint)
            assert ep is not None
            assert ep.endpoint == all_eps[0].endpoint

    def test_get_returns_none_for_unknown(self, capability):
        assert capability.get("/nonexistent") is None


class TestAPICapabilityPrompt:
    """Capability prompt 生成测试."""

    def test_to_prompt_returns_string(self, capability):
        prompt = capability.to_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_to_prompt_contains_endpoints(self, capability):
        prompt = capability.to_prompt(keywords=["gift"])
        assert "POST" in prompt
        assert "/live/" in prompt

    def test_to_prompt_with_no_matches(self, capability):
        prompt = capability.to_prompt(keywords=["nonexistent_xyz"])
        assert "无可用" in prompt

    def test_to_prompt_max_endpoints(self, capability):
        prompt = capability.to_prompt(max_endpoints=3)
        endpoint_count = prompt.count("### ")
        assert endpoint_count <= 3


class TestAPICapabilityExport:
    """Capability 导出测试."""

    def test_to_json(self, capability, tmp_path: Path):
        out = capability.to_json(tmp_path / "api_catalog.json")
        assert out.exists()
        data = json.loads(out.read_text("utf-8"))
        assert len(data) > 0
        for endpoint, spec in data.items():
            assert "method" in spec
            assert "source" in spec


class TestSwaggerLoading:
    """Swagger 加载测试."""

    def test_load_swagger_no_file(self, tmp_path: Path):
        cap = APICapability()
        count = cap.load_from_swagger(tmp_path / "nonexistent.json")
        assert count == 0

    def test_load_swagger_mock(self, tmp_path: Path):
        swagger = {
            "openapi": "3.0.0",
            "servers": [{"url": "https://api.test.com"}],
            "paths": {
                "/live/gift/send_gift": {
                    "post": {
                        "summary": "Send a gift",
                        "tags": ["gift"],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "properties": {
                                            "goods_id": {"type": "integer"},
                                            "cnt": {"type": "integer"},
                                        }
                                    }
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "properties": {
                                                "ret": {"type": "integer"},
                                                "data": {"type": "object"},
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        sw_file = tmp_path / "swagger.json"
        sw_file.write_text(json.dumps(swagger), encoding="utf-8")

        cap = APICapability()
        count = cap.load_from_swagger(sw_file)
        assert count == 1
        ep = cap.get("/live/gift/send_gift")
        assert ep is not None
        assert ep.method == "POST"
        assert ep.description == "Send a gift"
        assert "gift" in ep.tags
        assert ep.source == "swagger"
