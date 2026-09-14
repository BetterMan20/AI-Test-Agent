# -*- coding: utf-8 -*-
"""app.menu — 交互式菜单（python -m app 无参数时进入）。"""
from __future__ import annotations

from core.config import loader


def _print_banner(leftw: int = 42):
    print("=" * 60)
    print("       AI-Test-Agent")
    print("=" * 60)


def run_business_actions(project: str, env: str) -> int:
    """经适配器注册表枚举并执行选定业务动作（Core 不知道具体业务是什么）。"""
    from core.adapters import registry
    actions = registry.list_actions(project)
    if not actions:
        print("该项目未声明业务动作")
        return 0
    print("业务动作:")
    for i, a in enumerate(actions, 1):
        print(f"  {i}. {a}")
    print("  q. 返回")
    try:
        c = input("选择: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return 0
    if c == "q":
        return 0
    try:
        action = actions[int(c) - 1]
    except (ValueError, IndexError):
        print("无效选择")
        return 1
    return registry.load_adapter(project, env=env).execute_action(action).__bool__() and 0 or 1


def _pick_project() -> str:
    projects = loader.list_projects()
    if not projects:
        raise SystemExit("无可用项目：config/projects/ 下没有 *.yaml")
    if len(projects) == 1:
        print(f"  项目: {projects[0]}")
        return projects[0]
    print("选择项目:")
    for i, p in enumerate(projects, 1):
        print(f"  {i}. {p}")
    while True:
        try:
            n = int(input("> ").strip())
            return projects[n - 1]
        except (ValueError, IndexError):
            print("  输入无效，重试")


def _pick_env(project: str) -> str:
    proj = loader.load_project(project)
    return proj.default_env


def run_menu(_args) -> int:
    _print_banner()
    print("  1. 需求分析")
    print("  2. 测试用例生成")
    print("  3. 批量执行")
    print("  4. 随机稳定性测试")
    print("  5. 指定用例执行")
    print("  6. 查看测试结果")
    print("  7. 退出")
    print("=" * 60)

    try:
        choice = input("请选择 (1-7): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n退出")
        return 0

    project = _pick_project()
    env = _pick_env(project)
    from app.cli import dispatch

    if choice == "3":
        print("\n[批量执行/业务动作]")
        return run_business_actions(project, env)
    if choice == "4":
        events = int(input("事件数(默认100000): ").strip() or "100000")
        return dispatch("random", project=project, env=env, events=events)
    if choice == "5":
        cid = input("用例 ID: ").strip()
        return dispatch("case", project=project, env=env, case=cid)
    if choice in ("1", "2", "6"):
        print(f"\n[待接入] 选项 {choice}：该能力属 Core 管线(S1-S5)，后续由 qa_workflow 承接。")
        return 0
    if choice == "7":
        print("退出")
        return 0
    print("无效选择")
    return 1