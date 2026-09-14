"""账号健康度巡检 CLI：
按账号回放登录样本判定授权可用性，并把发红包样本(mid)与可续登录账号关联。

用法:
  python run_account_health.py [capture_dir] [--dry-run]
    --dry-run 仅汇总账号/样本结构，不回放登录(无副作用)
"""
import argparse
import json
import sys

from replay.account_health import AccountHealthChecker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HIGO 账号健康度巡检")
    parser.add_argument("capture_dir", nargs="?", default="D:/higo-api")
    parser.add_argument("--dry-run", action="store_true",
                        help="只汇总账号结构，不回放登录")
    args = parser.parse_args(argv)

    checker = AccountHealthChecker(args.capture_dir)
    report = checker.run(probe_login=not args.dry_run)

    print("== 账号健康度巡检 ==")
    s = report["summary"]
    print(f"  账号数={s['accounts']}  登录通过={s['login_pass']}  "
          f"登录失败={s['login_fail']}  有发红包样本={s['with_send']}  "
          f"孤儿发送(mid无对应账号)={s['orphan_sends']}")
    print("-- 明细(账号/状态/登录ret/发送样本数/token前缀) --")
    for a in report["accounts"]:
        print("  %-13s %-10s ret=%-4s send=%d  token=%s…" % (
            a["phone"], a["status"], a["login_ret"],
            a["send_samples"], a["new_token_prefix"] or a.get("example_token", ""),
        ))
    for o in report["send_orphans"][:10]:
        print("   [孤儿] mid=%s 发红包样本x%d" % (o["mid"], o["send_samples"]))
    print("输出:", report["output_path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())