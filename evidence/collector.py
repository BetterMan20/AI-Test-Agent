"""Evidence collector — orchestrates evidence capture during execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evidence.models import Evidence, EvidenceType
from evidence.store import EvidenceStore


class EvidenceCollector:
    """在执行步骤后采集截图、API 响应、DB 快照、logcat 等证据。"""

    def __init__(self, store: EvidenceStore):
        self._store = store

    def collect_screenshot(
        self, adb_client: Any, tc_id: str, step_id: int
    ) -> Evidence:
        tc_dir = self._store.base_dir / tc_id
        tc_dir.mkdir(parents=True, exist_ok=True)
        path = str(tc_dir / f"step{step_id}_screenshot.png")
        adb_client.screenshot(path)
        ev = Evidence(
            type=EvidenceType.SCREENSHOT,
            path=path,
            tc_id=tc_id,
            step_id=step_id,
            metadata={"artifact": "screenshot"},
        )
        self._store.save(ev)
        return ev

    def collect_api_evidence(
        self,
        request_config: dict[str, Any],
        response: Any,
        tc_id: str,
        step_id: int,
        execution_meta: dict[str, Any] | None = None,
    ) -> list[Evidence]:
        """Save 4 evidence artifacts: request.json, response.json, headers.json, execution.json."""
        tc_dir = self._store.base_dir / tc_id
        tc_dir.mkdir(parents=True, exist_ok=True)
        meta = execution_meta or {}

        # request.json — what was sent
        request_path = str(tc_dir / f"step{step_id}_request.json")
        request_data = {
            "method": request_config.get("method", "GET"),
            "path": request_config.get("path", ""),
            "headers": request_config.get("headers") or {},
            "body": request_config.get("body"),
            "params": request_config.get("params") or {},
        }
        Path(request_path).write_text(
            json.dumps(request_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ev_request = Evidence(
            type=EvidenceType.API_RESPONSE,
            path=request_path,
            tc_id=tc_id,
            step_id=step_id,
            metadata={"artifact": "request"},
        )
        self._store.save(ev_request)

        # response.json — response body
        response_path = str(tc_dir / f"step{step_id}_response.json")
        body_text = getattr(response, "text", "")
        try:
            body_json = response.json()
            response_data = body_json
        except Exception:
            response_data = body_text
        Path(response_path).write_text(
            json.dumps(response_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ev_response = Evidence(
            type=EvidenceType.API_RESPONSE,
            path=response_path,
            tc_id=tc_id,
            step_id=step_id,
            metadata={"artifact": "response", "status_code": getattr(response, "status_code", None)},
        )
        self._store.save(ev_response)

        # headers.json — response headers
        headers_path = str(tc_dir / f"step{step_id}_headers.json")
        headers_data = dict(getattr(response, "headers", {}))
        Path(headers_path).write_text(
            json.dumps(headers_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ev_headers = Evidence(
            type=EvidenceType.API_RESPONSE,
            path=headers_path,
            tc_id=tc_id,
            step_id=step_id,
            metadata={"artifact": "headers"},
        )
        self._store.save(ev_headers)

        # execution.json — execution metadata
        execution_path = str(tc_dir / f"step{step_id}_execution.json")
        execution_data = {
            "tc_id": tc_id,
            "step_id": step_id,
            "step_type": "api",
            "status_code": getattr(response, "status_code", None),
            "duration_ms": meta.get("duration_ms", 0),
            "status": meta.get("status", ""),
            "assertions_passed": meta.get("assertions_passed", 0),
            "assertions_failed": meta.get("assertions_failed", 0),
            "timestamp": meta.get("timestamp", ""),
        }
        Path(execution_path).write_text(
            json.dumps(execution_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ev_execution = Evidence(
            type=EvidenceType.API_RESPONSE,
            path=execution_path,
            tc_id=tc_id,
            step_id=step_id,
            metadata={"artifact": "execution"},
        )
        self._store.save(ev_execution)

        return [ev_request, ev_response, ev_headers, ev_execution]

    def collect_db_evidence(
        self,
        db_config: dict[str, Any],
        rows: list[dict[str, Any]],
        tc_id: str,
        step_id: int,
        execution_meta: dict[str, Any] | None = None,
    ) -> list[Evidence]:
        """Save 3 DB evidence artifacts: db_query.json, db_snapshot.json, db_execution.json."""
        tc_dir = self._store.base_dir / tc_id
        tc_dir.mkdir(parents=True, exist_ok=True)
        meta = execution_meta or {}

        # db_query.json — what was executed
        query_path = str(tc_dir / f"step{step_id}_db_query.json")
        query_data = {
            "phase": db_config.get("phase", "verify"),
            "query": db_config.get("query", ""),
            "params": db_config.get("params"),
        }
        Path(query_path).write_text(
            json.dumps(query_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ev_query = Evidence(
            type=EvidenceType.DB_SNAPSHOT,
            path=query_path,
            tc_id=tc_id,
            step_id=step_id,
            metadata={"artifact": "db_query"},
        )
        self._store.save(ev_query)

        # db_snapshot.json — query results
        snapshot_path = str(tc_dir / f"step{step_id}_db_snapshot.json")
        Path(snapshot_path).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ev_snapshot = Evidence(
            type=EvidenceType.DB_SNAPSHOT,
            path=snapshot_path,
            tc_id=tc_id,
            step_id=step_id,
            metadata={"artifact": "db_snapshot", "row_count": len(rows)},
        )
        self._store.save(ev_snapshot)

        # db_execution.json — execution metadata
        db_exec_path = str(tc_dir / f"step{step_id}_db_execution.json")
        db_exec_data = {
            "tc_id": tc_id,
            "step_id": step_id,
            "step_type": "db",
            "phase": db_config.get("phase", "verify"),
            "row_count": len(rows),
            "duration_ms": meta.get("duration_ms", 0),
            "status": meta.get("status", ""),
            "assertions_passed": meta.get("assertions_passed", 0),
            "assertions_failed": meta.get("assertions_failed", 0),
            "timestamp": meta.get("timestamp", ""),
        }
        Path(db_exec_path).write_text(
            json.dumps(db_exec_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ev_db_exec = Evidence(
            type=EvidenceType.DB_SNAPSHOT,
            path=db_exec_path,
            tc_id=tc_id,
            step_id=step_id,
            metadata={"artifact": "db_execution"},
        )
        self._store.save(ev_db_exec)

        return [ev_query, ev_snapshot, ev_db_exec]

    def collect_adb_evidence(
        self,
        adb_config: dict[str, Any],
        output: Any,
        tc_id: str,
        step_id: int,
        execution_meta: dict[str, Any] | None = None,
    ) -> list[Evidence]:
        """Save 3 ADB evidence artifacts: adb_command.json, adb_output.json, adb_execution.json."""
        tc_dir = self._store.base_dir / tc_id
        tc_dir.mkdir(parents=True, exist_ok=True)
        meta = execution_meta or {}

        # adb_command.json — what was executed
        cmd_path = str(tc_dir / f"step{step_id}_adb_command.json")
        cmd_data = {
            "command": adb_config.get("command", ""),
            "args": adb_config.get("args", []),
        }
        Path(cmd_path).write_text(
            json.dumps(cmd_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ev_cmd = Evidence(
            type=EvidenceType.TEXT,
            path=cmd_path,
            tc_id=tc_id,
            step_id=step_id,
            metadata={"artifact": "adb_command"},
        )
        self._store.save(ev_cmd)

        # adb_output.json — shell output
        out_path = str(tc_dir / f"step{step_id}_adb_output.json")
        out_data = {
            "output": str(output) if not isinstance(output, str) else output,
        }
        Path(out_path).write_text(
            json.dumps(out_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ev_out = Evidence(
            type=EvidenceType.TEXT,
            path=out_path,
            tc_id=tc_id,
            step_id=step_id,
            metadata={"artifact": "adb_output"},
        )
        self._store.save(ev_out)

        # adb_execution.json — execution metadata
        exec_path = str(tc_dir / f"step{step_id}_adb_execution.json")
        exec_data = {
            "tc_id": tc_id,
            "step_id": step_id,
            "step_type": "adb",
            "duration_ms": meta.get("duration_ms", 0),
            "status": meta.get("status", ""),
            "assertions_passed": meta.get("assertions_passed", 0),
            "assertions_failed": meta.get("assertions_failed", 0),
            "timestamp": meta.get("timestamp", ""),
        }
        Path(exec_path).write_text(
            json.dumps(exec_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ev_exec = Evidence(
            type=EvidenceType.TEXT,
            path=exec_path,
            tc_id=tc_id,
            step_id=step_id,
            metadata={"artifact": "adb_execution"},
        )
        self._store.save(ev_exec)

        return [ev_cmd, ev_out, ev_exec]

    def collect_logcat(
        self,
        adb_client: Any,
        tc_id: str,
        step_id: int,
        filter_spec: str = "",
    ) -> Evidence:
        tc_dir = self._store.base_dir / tc_id
        tc_dir.mkdir(parents=True, exist_ok=True)
        path = str(tc_dir / f"step{step_id}_logcat.txt")
        output = adb_client.logcat(filter_spec)
        Path(path).write_text(output, encoding="utf-8")
        ev = Evidence(
            type=EvidenceType.LOGCAT,
            path=path,
            tc_id=tc_id,
            step_id=step_id,
            metadata={"artifact": "logcat"},
        )
        self._store.save(ev)
        return ev

    def collect_text(
        self, text: str, tc_id: str, step_id: int, filename: str = ""
    ) -> Evidence:
        tc_dir = self._store.base_dir / tc_id
        tc_dir.mkdir(parents=True, exist_ok=True)
        name = filename or f"step{step_id}_text.txt"
        path = str(tc_dir / name)
        Path(path).write_text(text, encoding="utf-8")
        ev = Evidence(
            type=EvidenceType.TEXT,
            path=path,
            tc_id=tc_id,
            step_id=step_id,
            metadata={"artifact": "text"},
        )
        self._store.save(ev)
        return ev
