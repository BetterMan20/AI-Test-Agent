# -*- coding: utf-8 -*-
"""app.cli — AI-Test-Agent 统一执行入口（argparse 子命令 + 交互菜单）。"""
from __future__ import annotations

import sys
from pathlib import Path

from core.config import loader

# 确保项目根在 sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.drivers import capture, stability, case  # noqa: E402
from core.adapters import registry  # noqa: E402


def resolve(project: str | None, env: str | None) -> tuple[str, str]:
    """project 未指定时取唯一项目；env 未指定时取该项目默认 env。"""
    if project:
        proj = loader.load_project(project)
    else:
        projects = loader.list_projects()
        if not projects:
            raise RuntimeError("无可用项目：config/projects/ 下没有 *.yaml")
        if len(projects) > 1:
            raise SystemExit(f"多项目并存，须显式 --project：{projects}")
        project = projects[0]
        proj = loader.load_project(project)
    return project, (env or proj.default_env)


def dispatch(strategy: str, **kw) -> int:
    """按 strategy 路由到对应驱动（代码只认能力 key，不认具体项目）。"""
    if strategy == "api":
        return capture.run(
            kw["project"], kw["env"], keyword=kw.get("keyword"),
            max_count=kw.get("max_count", 0),
            evidence_dir=kw.get("evidence_dir"), mode=kw.get("mode"),
        )
    if strategy == "random":
        return stability.run(
            kw["project"], kw["env"], events=kw.get("events", 100000),
            evidence_dir=kw.get("evidence_dir"),
        )
    if strategy == "case":
        return case.run(
            kw["project"], kw["env"], kw.get("case") or kw.get("value") or "",
            tc_file=kw.get("tc_file"), evidence_dir=kw.get("evidence_dir"),
        )
    if strategy in ("adapter", "business"):
        return run_action(kw["project"], kw["env"], kw.get("action") or kw.get("value") or "",
                          kw.get("evidence_dir"))
    raise SystemExit(f"未知 strategy: {strategy}（支持: api/random/case/adapter）")


def run_action(project: str, env: str, action: str, evidence_dir: str | None = None) -> int:
    """经适配器注册表执行一个业务动作（Core 不知道具体业务）。"""
    adapter = registry.load_adapter(project, env=env, evidence_dir=evidence_dir or "")
    print(f"  适配器: {type(adapter).__name__} 动作: {action}", flush=True)
    res = adapter.execute_action(action)
    print(f"  ↳ {action}: {res.status}" + (f" ({res.error})" if res.error else ""), flush=True)
    return 0 if res.ok else 1


def run_cmd(project: str | None, env: str | None, strategy: str,
            case: str | None, events: int | None, keyword: str | None,
            max_count: int, mode: str | None, evidence_dir: str | None,
            tc_file: str | None) -> int:
    project, env = resolve(project, env)
    if strategy == "case" and not case:
        raise SystemExit("--strategy case 须带 --case TC-xxx")
    print(f"== 项目={project} 环境={env} 策略={strategy}"
          f"{' mode='+mode if mode else ''} ==", flush=True)
    return dispatch(strategy, project=project, env=env, case=case,
                    events=events, keyword=keyword, max_count=max_count,
                    mode=mode, evidence_dir=evidence_dir, tc_file=tc_file)


def build_parser():
    import argparse
    p = argparse.ArgumentParser(
        prog="app", description="AI-Test-Agent 统一执行入口",
        formatter_class=argparse.RawTextHelpFormatter)

    # 顶层可选参数（不限于 run），方便 python -m app --project higo run ...
    p.add_argument("--project", help="项目名（config/projects/<name>.yaml）")
    p.add_argument("--env", help="环境名（config/environments/<proj>-<env>.yaml）")
    p.add_argument("--mode", help="模式 smoke/regression/nightly")
    p.add_argument("--strategy", choices=["api", "random", "case", "adapter"],
                   help="测试策略")
    p.add_argument("--action", help="业务动作（经项目适配器执行，如 send_red_packet）")
    p.add_argument("--events", type=int, help="随机稳定性事件数")
    p.add_argument("--case", help="指定用例 ID")
    p.add_argument("--keyword", help="抓包关键词过滤")
    p.add_argument("--max-count", type=int, default=0, help="抓包回放上限")
    p.add_argument("--evidence-dir", help="证据输出目录")
    p.add_argument("--tc-file", help="指定用例文件(默认 output/test_cases.json)")
    p.add_argument("--from-config", action="store_true",
                   help="strategy 未指定时读取项目 capabilities 逐个执行")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else list(sys.argv[1:])

    # 兼容 `python -m app run ...`：剥掉子命令占位符 run
    if argv and argv[0].lower() == "run":
        argv = argv[1:]

    args = build_parser().parse_args(argv)

    # 业务动作 → 经适配器注册表执行（最强解耦：不指定 strategy，直接给 --action）
    if args.action:
        project, env = resolve(args.project, args.env)
        print(f"== 项目={project} 环境={env} 动作={args.action} ==", flush=True)
        return run_action(project, env, args.action, args.evidence_dir)

    if args.strategy or args.from_config:
        if args.from_config and not args.strategy:
            project, env = resolve(args.project, args.env)
            proj = loader.load_project(project)
            rc = 0
            for cap in proj.capabilities:
                key = cap.get("key")
                rc |= dispatch(key, project=project, env=env, case=args.case,
                               events=args.events, keyword=args.keyword,
                               max_count=args.max_count, mode=args.mode,
                               evidence_dir=args.evidence_dir, tc_file=args.tc_file)
            return rc
        return run_cmd(args.project, args.env, args.strategy, args.case,
                       args.events, args.keyword, args.max_count,
                       args.mode, args.evidence_dir, args.tc_file)

    # 无参数 → 交互菜单
    from app.menu import run_menu
    return run_menu(args)


if __name__ == "__main__":
    raise SystemExit(main())