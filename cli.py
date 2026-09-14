"""CLI — AI-Test-Agent 命令行工具.

用法:

  # 入口 A: 从 Test Case 执行
  python cli.py run --tc output/test_cases.json
  python cli.py run --tc output/test_cases.json --tc-id TC-EXPCARD-001

  # 入口 B: 从 Whistle 抓包目录执行
  python cli.py run --capture-dir D:/higo-api --keywords gift,wealth,sign_in

  # 入口 B: 从单个抓包文件执行
  python cli.py run --capture-file D:/higo-api/1788753297107_10.txt

  # 通用参数
  --api-base-url https://api-chat-test.youyisia.com
  --evidence-dir output/evidence
  --report output/report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from engine import TestEngine


def cmd_run(args: argparse.Namespace) -> int:
    """执行测试."""
    capability = None
    if args.capability_dir:
        from knowledge.capability import APICapability

        capability = APICapability()
        count = capability.load_from_whistle(args.capability_dir)
        print(f"Loaded {count} API endpoints from {args.capability_dir}")
        if args.swagger:
            sw_count = capability.load_from_swagger(args.swagger)
            print(f"Loaded {sw_count} API endpoints from {args.swagger}")
    elif args.swagger:
        from knowledge.capability import APICapability

        capability = APICapability()
        sw_count = capability.load_from_swagger(args.swagger)
        print(f"Loaded {sw_count} API endpoints from {args.swagger}")

    engine = TestEngine(
        api_base_url=args.api_base_url,
        evidence_dir=args.evidence_dir,
        db_host=args.db_host,
        db_port=args.db_port,
        db_user=args.db_user,
        db_password=args.db_password,
        db_name=args.db_name,
        adb_device_serial=args.adb_serial,
        capability=capability,
        validate_plans=not args.no_validate,
    )

    results = []

    # 入口 A: Test Case
    if args.tc:
        tc_path = Path(args.tc)
        if not tc_path.exists():
            print(f"Error: TC file not found: {tc_path}")
            return 1

        tc_data = json.loads(tc_path.read_text(encoding="utf-8"))
        if isinstance(tc_data, list):
            if args.tc_id:
                tc_data = next((t for t in tc_data if t.get("id") == args.tc_id), None)
                if tc_data is None:
                    print(f"Error: TC ID '{args.tc_id}' not found in {tc_path}")
                    return 1
            else:
                print(f"Found {len(tc_data)} test cases in {tc_path}")
                for tc in tc_data:
                    print(f"  Running: {tc.get('id', '?')} - {tc.get('title', '')[:50]}")
                    result = engine.run_test_case(tc)
                    results.append(result)
                    _print_result(result)
        else:
            result = engine.run_test_case(tc_data)
            results.append(result)
            _print_result(result)

    # 入口 B: Capture directory
    if args.capture_dir:
        capture_dir = Path(args.capture_dir)
        if not capture_dir.exists():
            print(f"Error: Capture directory not found: {capture_dir}")
            return 1

        keywords = args.keywords.split(",") if args.keywords else None
        print(f"Scanning captures in: {capture_dir}")
        if keywords:
            print(f"  Filtering by keywords: {keywords}")

        result = engine.run_captures_from_dir(
            capture_dir,
            keywords=keywords,
            max_count=args.max_count,
        )
        _print_batch_result(result)
        if args.report:
            engine.save_report(result, args.report)

    # 入口 B: Capture single file
    if args.capture_file:
        capture_file = Path(args.capture_file)
        if not capture_file.exists():
            print(f"Error: Capture file not found: {capture_file}")
            return 1

        keywords = args.keywords.split(",") if args.keywords else None
        print(f"Replaying captures from: {capture_file}")
        if keywords:
            print(f"  Filtering by keywords: {keywords}")
        result = engine.run_capture_file(capture_file, keywords=keywords)
        _print_batch_result(result)
        if args.report:
            engine.save_report(result, args.report)

    engine.close()

    # Summary
    total = len(results)
    if total > 0:
        passed = sum(1 for r in results if r.status == "pass")
        failed = sum(1 for r in results if r.status == "fail")
        errored = sum(1 for r in results if r.status == "error")
        print(f"\n{'=' * 50}")
        print(f"Summary: {passed} PASS / {failed} FAIL / {errored} ERROR / {total} TOTAL")

    return 0


def _print_result(result) -> None:
    status_icon = {"pass": "PASS", "fail": "FAIL", "error": "ERROR", "skip": "SKIP"}
    icon = status_icon.get(result.status, result.status.upper())
    print(f"  [{icon}] {result.tc_id}: {result.title[:60]}")
    for sr in result.step_results:
        print(f"    Step {sr.step_id} ({sr.step_type}): {sr.status} "
              f"({sr.assertions_passed} passed, {sr.assertions_failed} failed, "
              f"{len(sr.evidence_refs)} evidence files)")
        if sr.error:
            print(f"      Error: {sr.error[:100]}")


def _print_batch_result(result) -> None:
    for r in result.results:
        _print_result(r)
    print(f"\n{'=' * 50}")
    print(f"Batch Summary: {result.passed} PASS / {result.failed} FAIL / "
          f"{result.errored} ERROR / {result.total} TOTAL "
          f"({result.duration_ms}ms)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI-Test-Agent: AI-driven test automation engine",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run command
    run_parser = subparsers.add_parser("run", help="Execute tests")
    run_parser.add_argument("--tc", help="Test Case JSON file path")
    run_parser.add_argument("--tc-id", help="Specific TC ID to run (if TC file is a list)")
    run_parser.add_argument("--capture-dir", help="Whistle capture directory")
    run_parser.add_argument("--capture-file", help="Single Whistle capture file")
    run_parser.add_argument("--keywords", help="Comma-separated keywords to filter captures")
    run_parser.add_argument("--max-count", type=int, help="Max number of captures to run")
    run_parser.add_argument("--api-base-url", default="", help="API base URL")
    run_parser.add_argument("--evidence-dir", default="output/evidence", help="Evidence output directory")
    run_parser.add_argument("--report", help="Save JSON report to this path")
    run_parser.add_argument("--db-host", default="", help="MySQL host")
    run_parser.add_argument("--db-port", type=int, default=3306, help="MySQL port")
    run_parser.add_argument("--db-user", default="", help="MySQL user")
    run_parser.add_argument("--db-password", default="", help="MySQL password")
    run_parser.add_argument("--db-name", default="", help="MySQL database name")
    run_parser.add_argument("--adb-serial", default="", help="ADB device serial")
    run_parser.add_argument("--capability-dir", help="Whistle capture dir for API capability")
    run_parser.add_argument("--swagger", help="Swagger/OpenAPI JSON file path")
    run_parser.add_argument("--no-validate", action="store_true", help="Skip Plan validation")

    args = parser.parse_args()

    if args.command == "run":
        sys.exit(cmd_run(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
