#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""secret_scan.py — 敏感信息扫描（提交前拦截 + 事后审计）。

扫描三类目标：
  1. 工作区 / 暂存区里被 Git 跟踪的文本文件；
  2. Git 全历史中每个提交的文本内容（含已删除文件）；
  3. `.env` 里的真实密钥/地址值是否出现在历史的任何文件里（反查泄漏）。

另外会解开历史中的 .zip 报告快照，扫描其内部文本。

用法：
  python scripts/secret_scan.py              # 工作区 + 历史 + .env 反查
  python scripts/secret_scan.py --staged     # 只扫暂存区（pre-commit 用）
  python scripts/secret_scan.py --no-history # 跳过历史，快速自查
  python scripts/secret_scan.py --json

退出码：0 = 未发现；1 = 发现疑似敏感信息；2 = 运行错误。
扫描结果只打印「文件/提交 + 规则名」，不回显命中内容，避免二次泄漏。
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# 规则：(名称, 正则, 等级)；block = 必须阻断，review = 需人工确认
RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"), "block"),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "block"),
    ("aliyun-access-key", re.compile(r"\bLTAI[A-Za-z0-9]{12,}\b"), "block"),
    (
        "url-with-credentials",
        re.compile(r"\b(?:mongodb(?:\+srv)?|redis|rediss|mysql|postgres(?:ql)?|amqp|ftp)://[^:\s/@]+:[^@\s]+@"),
        "block",
    ),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]{24,}"), "block"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "block"),
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9]{24,}\b"), "block"),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "block"),
    (
        "hardcoded-credential",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?key|"
            r"private[_-]?key|client[_-]?secret|auth[_-]?token)\b\s*[:=]\s*['\"][^'\"\s]{6,}['\"]"
        ),
        "review",
    ),
]

SKIP_PARTS = {
    ".git", ".venv", "node_modules", "output", "scratch", "secrets",
    ".idea", ".pytest_cache", "__pycache__", ".mypy_cache", "dist", "build",
}

TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".yaml", ".yml", ".html", ".htm", ".js", ".ts",
    ".ps1", ".sh", ".bat", ".cmd", ".txt", ".xml", ".csv", ".ini", ".cfg",
    ".toml", ".env", ".sql", ".java", ".kt", ".gradle", ".properties",
}

ENV_KEY_HINTS = ("PASS", "SECRET", "KEY", "TOKEN", "HOST", "URL", "DSN", "CONN", "ADDR")


def run(cmd: list[str], input_bytes: bytes | None = None) -> bytes:
    proc = subprocess.run(
        cmd, cwd=REPO, input=input_bytes,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    return proc.stdout


def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def scan_text(text: str, where: str) -> list[dict]:
    findings = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for name, pattern, level in RULES:
            if pattern.search(line):
                findings.append({"rule": name, "level": level, "where": where, "line": lineno})
    return findings


def scan_zip(data: bytes, where: str) -> list[dict]:
    findings = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                suffix = Path(info.filename).suffix.lower()
                if suffix not in TEXT_SUFFIXES:
                    continue
                try:
                    body = zf.read(info).decode("utf-8", "ignore")
                except Exception:
                    continue
                findings.extend(scan_text(body, f"{where}!{info.filename}"))
    except zipfile.BadZipFile:
        pass
    return findings


def tracked_files() -> list[str]:
    out = run(["git", "ls-files", "-z"]).decode("utf-8", "ignore")
    return [p for p in out.split("\0") if p]


def staged_files() -> list[str]:
    out = run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"])
    return [p for p in out.decode("utf-8", "ignore").split("\0") if p]


def scan_worktree(paths: list[str]) -> list[dict]:
    findings = []
    for rel in paths:
        parts = Path(rel).parts
        if any(p in SKIP_PARTS for p in parts):
            continue
        path = REPO / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        if rel.lower().endswith(".zip"):
            findings.extend(scan_zip(data, rel))
            continue
        if is_binary(data):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != ".gitignore":
            continue
        findings.extend(scan_text(data.decode("utf-8", "ignore"), rel))
    return findings


def scan_staged(paths: list[str]) -> list[dict]:
    findings = []
    for rel in paths:
        if any(p in SKIP_PARTS for p in Path(rel).parts):
            continue
        data = run(["git", "show", f":{rel}"])
        if not data:
            continue
        if rel.lower().endswith(".zip"):
            findings.extend(scan_zip(data, rel))
            continue
        if is_binary(data):
            continue
        findings.extend(scan_text(data.decode("utf-8", "ignore"), rel))
    return findings


def scan_history() -> list[dict]:
    commits = run(["git", "rev-list", "--all"]).decode().split()
    if not commits:
        return []
    findings = []
    for name, pattern, level in RULES:
        out = run(["git", "grep", "-I", "-l", "-E", "-e", pattern.pattern, *commits])
        for line in out.decode("utf-8", "ignore").splitlines():
            commit, _, path = line.partition(":")
            if any(p in SKIP_PARTS for p in Path(path).parts):
                continue
            findings.append({"rule": name, "level": level, "where": f"{commit[:8]}:{path}", "line": 0})

    # 历史中的 .zip 快照
    objects = run(["git", "rev-list", "--objects", "--all"]).decode("utf-8", "ignore")
    seen: set[str] = set()
    for line in objects.splitlines():
        sha, _, path = line.partition(" ")
        if not path.lower().endswith(".zip") or not sha:
            continue
        if any(p in SKIP_PARTS for p in Path(path).parts):
            continue
        key = f"{sha}:{path}"
        if key in seen:
            continue
        seen.add(key)
        data = run(["git", "cat-file", "-p", sha])
        findings.extend(scan_zip(data, f"history:{path}"))
    return findings


def env_values() -> list[tuple[str, str]]:
    env = REPO / ".env"
    if not env.exists():
        return []
    values = []
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        # 公开端点（*_BASE_URL / *_URL）按安全策略允许出现在文档与配置示例中，
        # 不参与「已知值泄漏」反查；带账号口令的 URL 仍由 url-with-credentials 规则拦截。
        if key.upper().endswith(("_BASE_URL", "_URL", "_ENDPOINT")):
            continue
        if len(value) < 6 or not any(h in key.upper() for h in ENV_KEY_HINTS):
            continue
        values.append((key, value))
    return values


def scan_known_values() -> list[dict]:
    """反查：.env 里的真实值是否出现在历史文件里。只报告键名与位置。"""
    values = env_values()
    if not values:
        return []
    commits = run(["git", "rev-list", "--all"]).decode().split()
    if not commits:
        return []
    findings = []
    for key, value in values:
        out = run(["git", "grep", "-I", "-l", "-F", "-e", value, *commits])
        for line in out.decode("utf-8", "ignore").splitlines():
            commit, _, path = line.partition(":")
            findings.append({
                "rule": "known-value-leak", "level": "block",
                "where": f"{commit[:8]}:{path}", "line": 0, "key": key,
            })
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="敏感信息扫描")
    parser.add_argument("--staged", action="store_true", help="只扫暂存区")
    parser.add_argument("--no-history", action="store_true", help="跳过历史扫描")
    parser.add_argument("--no-env", action="store_true", help="跳过 .env 值反查")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    findings: list[dict] = []
    scope = []

    if args.staged:
        paths = staged_files()
        findings += scan_staged(paths)
        scope.append(f"staged({len(paths)})")
    else:
        paths = tracked_files()
        findings += scan_worktree(paths)
        scope.append(f"worktree({len(paths)})")

    if not args.staged and not args.no_history:
        findings += scan_history()
        scope.append("history")
        if not args.no_env:
            findings += scan_known_values()
            scope.append("dotenv-backcheck")

    # 去重
    unique = {(f["rule"], f["where"], f.get("key", "")): f for f in findings}
    findings = list(unique.values())

    if args.json:
        print(json.dumps({"scope": scope, "findings": findings}, ensure_ascii=False, indent=2))
    else:
        print(f"scope: {', '.join(scope)}")
        if not findings:
            print("RESULT: clean — 未发现疑似敏感信息")
        else:
            print(f"RESULT: {len(findings)} 项疑似敏感信息")
            for f in sorted(findings, key=lambda x: (x["level"], x["rule"])):
                key = f" [{f['key']}]" if f.get("key") else ""
                print(f"  [{f['level']}] {f['rule']}{key} -> {f['where']}")

    return 1 if findings else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
