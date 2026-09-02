"""MySQL client for test execution."""

from __future__ import annotations

from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from execution.exceptions import ToolError


class DBClient:
    """基于 PyMySQL 的数据库客户端，支持上下文管理器。"""

    def __init__(
        self,
        host: str = "",
        port: int = 3306,
        user: str = "",
        password: str = "",
        database: str = "",
    ):
        self._config: dict[str, Any] = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
            "cursorclass": DictCursor,
            "autocommit": False,
            "charset": "utf8mb4",
        }
        self._conn: pymysql.connections.Connection | None = None

    def __enter__(self) -> "DBClient":
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def connect(self) -> None:
        try:
            self._conn = pymysql.connect(**self._config)
        except pymysql.Error as e:
            raise ToolError("db", f"Connection failed: {e}", e)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def query(self, sql: str, params: Any | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        try:
            with self._conn.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())
        except pymysql.Error as e:
            raise ToolError("db", f"Query failed: {e}", e)

    def execute(self, sql: str, params: Any | None = None) -> int:
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        try:
            with self._conn.cursor() as cursor:
                rows = cursor.execute(sql, params)
                self._conn.commit()
                return rows
        except pymysql.Error as e:
            self._conn.rollback()
            raise ToolError("db", f"Execute failed: {e}", e)

    def execute_many(self, sql: str, params_list: list[Any]) -> int:
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        try:
            with self._conn.cursor() as cursor:
                rows = cursor.executemany(sql, params_list)
                self._conn.commit()
                return rows
        except pymysql.Error as e:
            self._conn.rollback()
            raise ToolError("db", f"Execute many failed: {e}", e)
