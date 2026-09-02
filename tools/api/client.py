"""HTTP API client for test execution."""

from __future__ import annotations

from typing import Any

import requests
from requests import Response

from execution.exceptions import ToolError


class APIClient:
    """基于 requests.Session 的 HTTP 客户端。"""

    def __init__(
        self,
        base_url: str = "",
        default_headers: dict[str, str] | None = None,
        timeout: int = 30,
    ):
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        if default_headers:
            self._session.headers.update(default_headers)
        self._timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
        data: Any | None = None,
    ) -> Response:
        url = f"{self._base_url}/{path.lstrip('/')}" if self._base_url else path
        try:
            resp = self._session.request(
                method,
                url,
                headers=headers,
                json=json,
                params=params,
                data=data,
                timeout=self._timeout,
            )
            return resp
        except requests.RequestException as e:
            raise ToolError("api", f"{method} {path}: {e}", e)

    def get(self, path: str, **kwargs: Any) -> Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Response:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Response:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Response:
        return self.request("DELETE", path, **kwargs)

    def close(self) -> None:
        self._session.close()
