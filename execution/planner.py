"""Execution planner — converts document-level TC into executable plan."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 支持 `python execution/planner.py`（脚本方式）与 `python -m execution.planner`（模块方式）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from configs.skills import SKILLS
from utils.skill_loader import load_skill
from utils.llm import ask_llm


@dataclass
class ExecutionStep:
    """单条可执行步骤。"""

    step_id: int
    step_type: str  # api | db | adb | appium | manual
    description: str
    action: dict[str, Any] = field(default_factory=dict)
    assertions: list[dict[str, Any]] = field(default_factory=list)
    evidence_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "type": self.step_type,
            "description": self.description,
            "config": self.action,
            "assertions": self.assertions,
            "evidence_types": self.evidence_types,
        }


@dataclass
class ExecutionPlan:
    """单条 TC 的执行计划。"""

    tc_id: str
    title: str
    steps: list[ExecutionStep] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    test_data: list[str] = field(default_factory=list)
    traceability: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tc_id": self.tc_id,
            "title": self.title,
            "steps": [s.to_dict() for s in self.steps],
            "preconditions": self.preconditions,
            "test_data": self.test_data,
            "traceability": self.traceability,
        }

    @staticmethod
    def traceability_of(tc: dict[str, Any]) -> dict[str, Any]:
        """从文档级 TC 提取回溯引用（意图层 → 计划层的可追溯契约）。"""
        return {
            "test_point_id": tc.get("test_point_id", ""),
            "scenario_ref": tc.get("scenario_ref", ""),
            "source_facts": tc.get("source_facts", []),
            "related_gaps": tc.get("related_gaps", []),
            "priority": tc.get("priority", ""),
        }


class ExecutionPlanner:
    """将文档级 TC 转换为可执行步骤。"""

    EVIDENCE_MAP: dict[str, list[str]] = {
        "api": ["api_response"],
        "db": ["db_snapshot"],
        "adb": ["screenshot", "logcat"],
        "appium": ["appium_snapshot", "screenshot"],
        "manual": [],
    }

    def plan(
        self,
        test_case: dict[str, Any],
        environment: EnvironmentConfig,
    ) -> ExecutionPlan:
        tc_id = test_case.get("id", "")
        title = test_case.get("title", "")
        raw_steps = test_case.get("steps", [])
        expected_results = test_case.get("expected_results", [])

        steps: list[ExecutionStep] = []
        for i, raw in enumerate(raw_steps, 1):
            action_text = raw.get("action", "")
            step_type = self._detect_type(action_text)
            steps.append(
                ExecutionStep(
                    step_id=i,
                    step_type=step_type,
                    description=action_text,
                    action=self._parse_action(step_type, action_text),
                    assertions=self._build_assertions(expected_results),
                    evidence_types=self.EVIDENCE_MAP.get(step_type, []),
                )
            )

        return ExecutionPlan(
            tc_id=tc_id,
            title=title,
            steps=steps,
            preconditions=test_case.get("preconditions", []),
            test_data=test_case.get("test_data", []),
            traceability=ExecutionPlan.traceability_of(test_case),
        )

    def _detect_type(self, action_text: str) -> str:
        """从自然语言动作文本推断步骤类型。当前全部回退为 manual。"""
        return "manual"

    def _parse_action(self, step_type: str, action_text: str) -> dict[str, Any]:
        if step_type == "manual":
            return {"instruction": action_text}
        return {}

    def _build_assertions(self, expected_results: list[str]) -> list[dict[str, Any]]:
        return [
            {"type": "text_contains", "expected": text}
            for text in expected_results
        ]

    @staticmethod
    def plan_from_dict(plan_data: dict[str, Any]) -> ExecutionPlan:
        """Build an ExecutionPlan from a dict matching execution_plan.schema.json."""
        steps_data = plan_data.get("steps", []) or []
        steps: list[ExecutionStep] = []
        for s in steps_data:
            if not isinstance(s, dict):
                step_txt = str(s)
                steps.append(ExecutionStep(
                    step_id=len(steps) + 1, step_type="manual",
                    description=step_txt, action={"instruction": step_txt}))
                continue
            steps.append(
                ExecutionStep(
                    step_id=s.get("step_id") or len(steps) + 1,
                    step_type=s.get("type", "manual"),
                    description=s.get("description", ""),
                    action=s.get("config") or {},
                    assertions=s.get("assertions", []),
                    evidence_types=s.get("evidence_types", []),
                )
            )
        return ExecutionPlan(
            tc_id=plan_data.get("tc_id", ""),
            title=plan_data.get("title", ""),
            steps=steps,
            preconditions=plan_data.get("preconditions", []),
            test_data=plan_data.get("test_data", []),
            traceability=plan_data.get("traceability")
            or ExecutionPlan.traceability_of(plan_data),
        )

    @staticmethod
    def plan_from_test_case(
        test_case: dict[str, Any],
        capability: Any | None = None,
    ) -> ExecutionPlan:
        """LLM 驱动：将文档级 TC（自然语言 steps）转为可执行 ExecutionPlan.

        Args:
            test_case: 文档级 TC dict
            capability: APICapability 实例，提供 API 知识上下文
        """
        skill_path = SKILLS["tc_to_plan"]
        system_prompt = load_skill(skill_path)

        if capability is not None:
            keywords: list[str] = []
            title = test_case.get("title", "")
            steps_text = " ".join(s.get("action", "") for s in test_case.get("steps", []))
            for word in (title + " " + steps_text).replace("/", " ").split():
                if len(word) > 2 and word.isalpha():
                    keywords.append(word.lower())
            api_knowledge = capability.to_prompt(keywords=keywords[:5])
            system_prompt = system_prompt + "\n\n" + api_knowledge

        user_prompt = json.dumps(
            {"test_case": test_case}, ensure_ascii=False, indent=2
        )

        raw = ask_llm(system_prompt, user_prompt)
        plan_data = ExecutionPlanner._extract_plan_json(raw)
        ExecutionPlanner._normalize_plan(plan_data)
        # LLM 有时漏 tc_id/title：用输入 TC 回填，避免下游 KeyError
        plan_data.setdefault("tc_id", test_case.get("id", ""))
        plan_data.setdefault("title", test_case.get("title", ""))
        # 追溯字段以输入 TC 为准（LLM 输出不可信），保证 意图→计划 链路可复核
        plan_data["traceability"] = ExecutionPlan.traceability_of(test_case)

        return ExecutionPlanner.plan_from_dict(plan_data)

    @staticmethod
    def _extract_plan_json(raw: str) -> dict[str, Any]:
        """从 LLM 输出中提取 JSON（兼容 markdown 包裹、//注释、尾随逗号等）。"""
        import re

        text = raw.strip()

        def _clean(candidate: str) -> str:
            candidate = re.sub(r"//[^\n\r]*", "", candidate)
            candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
            candidate = candidate.replace("'", '"')
            return candidate

        def _try_parse(candidate: str) -> dict[str, Any] | None:
            candidate = _clean(candidate)
            try:
                return json.loads(candidate, strict=False)
            except json.JSONDecodeError:
                obj = ExecutionPlanner._extract_first_json_object(candidate)
                if obj:
                    try:
                        return json.loads(obj, strict=False)
                    except json.JSONDecodeError:
                        pass
                return None

        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if match:
            result = _try_parse(match.group(1))
            if result is not None:
                return result

        match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            result = _try_parse(match.group(1))
            if result is not None:
                return result

        obj = ExecutionPlanner._extract_first_json_object(text)
        if obj:
            result = _try_parse(obj)
            if result is not None:
                return result

        return json.loads(_clean(text))

    @staticmethod
    def _extract_first_json_object(text: str) -> str | None:
        """从文本中提取第一个完整的 JSON 对象（通过花括号配对）。"""
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False

        for i in range(start, len(text)):
            ch = text[i]

            if escape:
                escape = False
                continue

            if ch == "\\":
                escape = True
                continue

            if ch == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]

        return None

    @staticmethod
    def _normalize_plan(plan_data: dict[str, Any]) -> None:
        """修复 LLM 输出中的常见问题，确保 config 字段与 step type 匹配。"""
        for step in plan_data.get("steps", []):
            step_type = step.get("type", "manual")
            config = step.get("config")

            if not isinstance(config, dict):
                config = {}
                step["config"] = config

            if step_type == "api":
                config.setdefault("method", "GET")
                config.setdefault("path", "/")
            elif step_type == "db":
                config.setdefault("phase", "verify")
                config.setdefault("query", "SELECT 1")
            elif step_type == "adb":
                if "command" not in config:
                    config["command"] = step.get("description", "")
            elif step_type == "appium":
                # UI 业务操作：至少要有 operation；target/text/desc 依操作而定
                if "operation" not in config:
                    config["operation"] = "page_source"
                operation = config.get("operation")
                if operation in ("tap", "input_text", "find"):
                    config.setdefault("target", "")
                    config.setdefault("timeout", 10)
                elif operation == "tap_by_keyword":
                    config.setdefault("keyword", "")
                    config.setdefault("timeout", 10)
                elif operation in ("swipe",):
                    config.setdefault("swipe", [0, 0, 0, 0, 300])
                elif operation in ("input_text",):
                    config.setdefault("text", "")
                elif operation in ("find_text",):
                    config.setdefault("text", "")
                elif operation in ("find_desc",):
                    config.setdefault("desc", "")
                elif operation in ("tap_point",):
                    config.setdefault("x", 0)
                    config.setdefault("y", 0)
            elif step_type == "manual":
                if "instruction" not in config:
                    config["instruction"] = step.get("description", "")

    @staticmethod
    def plan_from_capture(captured_api) -> ExecutionPlan:
        """从 Whistle 抓包记录生成 ExecutionPlan（直接回放真实 API）。"""
        from tools.whistle_parser import CapturedAPI

        if not isinstance(captured_api, CapturedAPI):
            raise TypeError("plan_from_capture requires a CapturedAPI instance")

        endpoint = captured_api.endpoint
        tc_id = f"TC-CAP-{abs(hash(captured_api.capture_id)) % 100000:05d}"

        plan_data = {
            "tc_id": tc_id,
            "title": f"回放 {captured_api.method} {endpoint}",
            "preconditions": ["从 Whistle 抓包回放", f"原始状态码: {captured_api.status_code}"],
            "test_data": [f"capture_id={captured_api.capture_id}"],
            "steps": [{
                "step_id": 1,
                "type": "api",
                "description": f"{captured_api.method} {endpoint}",
                "config": {
                    "method": captured_api.method,
                    "path": captured_api.path_with_query,
                    "headers": captured_api.req_headers,
                    "body": captured_api.req_body or {},
                },
                "assertions": [
                    {"type": "status_code", "expected": captured_api.status_code},
                ],
                "evidence_types": ["api_response"],
            }],
        }

        if captured_api.res_body and isinstance(captured_api.res_body, dict):
            ret = captured_api.res_body.get("ret")
            if ret is not None:
                plan_data["steps"][0]["assertions"].append(
                    {"type": "json_path", "path": "$.ret", "expected": ret}
                )

        return ExecutionPlanner.plan_from_dict(plan_data)


def _step_action_str(s: dict) -> str:
    """把 config 渲染成一句人读的动作说明。"""
    cfg = s.get("config") or {}
    if s["type"] == "api":
        return f"{cfg.get('method', 'GET')} {cfg.get('path', '/')}"
    if s["type"] == "db":
        return str(cfg.get("query", "SELECT ?")).replace("\n", " ")
    if s["type"] == "adb":
        return str(cfg.get("command", ""))
    if s["type"] == "appium":
        op = cfg.get("operation", "page_source")
        if op in ("tap", "input_text", "find"):
            return f"{op}({cfg.get('target', '')})"
        if op == "swipe":
            return f"swipe{_couple(cfg.get('swipe'))}"
        if op == "find_text":
            return f"find_text({cfg.get('text', '')})"
        if op == "find_desc":
            return f"find_desc({cfg.get('desc', '')})"
        if op == "tap_point":
            return f"tap_point({cfg.get('x', 0)},{cfg.get('y', 0)})"
        if op == "tap_by_keyword":
            return f"tap_by_keyword({cfg.get('keyword', '')})"
        if op == "input_text":
            return f"input_text({cfg.get('target', '')}) = {cfg.get('text', '')}"
        return op
    return str(cfg.get("instruction", "") or s.get("description", ""))


def _couple(lst):
    """把 [x1,y1,x2,y2,dur] 渲染成 '(x1,y1)->(x2,y2)'，容错 None/非列表。"""
    if not isinstance(lst, (list, tuple)) or len(lst) < 4:
        return ""
    x1, y1, x2, y2 = lst[0], lst[1], lst[2], lst[3]
    dur = lst[4] if len(lst) > 4 else ""
    return f"({x1},{y1})->({x2},{y2}){('('+str(dur)+'ms)') if dur else ''}"


def _plan_step_line(s: dict) -> str:
    asserts = "；".join(
        f'{x.get("type")}={x.get("expected")}' for x in s.get("assertions", [])) or "-"
    ev = "，".join(s.get("evidence_types", [])) or "-"
    return (f"#{s['step_id']} [{s['type']}] {s['description']}\n"
            f"   ├ 动作: {_step_action_str(s)}\n"
            f"   ├ 断言: {asserts}\n"
            f"   └ 证据: {ev}")


def _render_plan_md(p: dict, mode: str, out: str) -> str:
    """把 ExecutionPlan 渲成 markdown 人读版。"""
    lines = [f"# 执行计划 {p['tc_id']}",
             "",
             f"- **标题**: {p['title']}",
             f"- **TC→Plan 模式**: {mode}",
             f"- **JSON**: `{out}`",
             ""]
    if p.get("preconditions"):
        lines += ["## 前置条件", ""] + [f"- {x}" for x in p["preconditions"]] + [""]
    if p.get("test_data"):
        lines += ["## 测试数据", ""] + [f"- {x}" for x in p["test_data"]] + [""]
    lines += ["## 步骤", ""]
    for s in p["steps"]:
        lines += [f"{_step_action_str_block(s)}"]
    lines += [""]
    return "\n".join(lines)


def _step_action_str_block(s: dict) -> str:
    return "\n".join([
        f"### S{s['step_id']} · {s['description']}  `[{s['type']}]`",
        "",
        f"- **动作**: {_step_action_str(s)}",
        "- **断言**: " + ("；".join(f"`{x.get('type')}={x.get('expected')}`"
        for x in s.get("assertions", [])) or "-"),
        "- **证据**: " + ("，".join(f"`{x}`" for x in s.get("evidence_types", [])) or "-")])


def _load_tcs(tc_file: str | None) -> tuple[list[dict[str, Any]], str]:
    """加载文档级 TC 列表；tc_file 缺省取 output/test_cases.json。"""
    path = tc_file or os.path.join(_PROJECT_ROOT, "output", "test_cases.json")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tcs = data.get("test_cases") if isinstance(data, dict) and "test_cases" in data else (
        [data] if isinstance(data, dict) else data)
    return (tcs or [], path)


def _main_plan_all(a, planner: "ExecutionPlanner") -> int:
    """汇聚模式：意图层（全部 TC）→ 单一 execution_plan.json（meta + plans）。

    产物分层契约：test_design.json 管意图/风险/覆盖；本文件管 执行器/参数/断言/证据。
    执行层（runner --plan-file）以本文件为直接输入，形成可追溯闭环。
    """
    tcs, src = _load_tcs(a.tc_file)
    if not tcs:
        print("!! 未在输入中找到 TC", flush=True)
        return 2
    print(f">> 汇聚模式：{len(tcs)} 条 TC ← {src}", flush=True)

    capability = None
    if not a.no_llm and os.path.isdir(a.capability_dir):
        try:
            from knowledge.capability import APICapability
            cap = APICapability()
            n = cap.load_from_whistle(a.capability_dir, max_files=200)
            if n:
                capability = cap
                print(f">> 已注入 API 知识: {n} 条(抓包 {a.capability_dir})", flush=True)
        except Exception as e:  # 知识注入失败不影响主流程
            print(f">> 注: API 知识注入跳过({e})", flush=True)

    plans: list[dict[str, Any]] = []
    failed: list[str] = []
    modes: set[str] = set()
    for i, tc in enumerate(tcs, 1):
        tc_id = tc.get("id", f"TC-{i:03d}")
        try:
            if a.no_llm:
                plan = planner.plan(tc, None)
                modes.add("plan(确定性)")
            else:
                plan = ExecutionPlanner.plan_from_test_case(tc, capability=capability)
                modes.add("plan_from_test_case(LLM)")
            plans.append(plan.to_dict())
            print(f"  [{i}/{len(tcs)}] {tc_id} → {len(plan.steps)} 步", flush=True)
        except Exception as e:  # 单条失败不阻断批量，记入 failed 供复核
            failed.append(f"{tc_id}: {e}")
            print(f"  [{i}/{len(tcs)}] {tc_id} !! {e}", flush=True)

    if not plans:
        print("!! 全部 TC 转计划失败", flush=True)
        return 1

    out = a.out or os.path.join(_PROJECT_ROOT, "output", "execution_plan.json")
    try:
        src_rel = os.path.relpath(src, _PROJECT_ROOT)
    except ValueError:  # 跨盘符（如临时目录在 C:，项目在 D:）退化为绝对路径
        src_rel = os.path.abspath(src)
    doc = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": src_rel,
            "count": len(plans),
            "mode": "+".join(sorted(modes)),
            "generator": "execution/planner.py --all",
            **({"failed": failed} if failed else {}),
        },
        "plans": plans,
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 46, flush=True)
    print(f"汇聚计划: {len(plans)} 条（失败 {len(failed)}）", flush=True)
    print(f"JSON: {out}", flush=True)
    return 0 if not failed else 3


def main() -> int:
    """CLI：文档级 TC → 可执行 ExecutionPlan（可独立运行）。

    用法:
        python -m execution.planner                                          # 默认 output/test_cases.json 第一条 TC
        python -m execution.planner --plan-data input/plan.json --out output/plan.json      # 确定性
        python -m execution.planner --tc-file input/test_cases.json --tc-id TC-RP-001       # LLM
        python -m execution.planner --tc-file input/test_cases.json --tc-id TC-RP-001 --no-llm
    """
    import argparse

    ap = argparse.ArgumentParser(description="TC→Plan 桥：文档级 TC 转可执行 ExecutionPlan 并落盘")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--plan-data", dest="plan_data",
                   help="execution_plan.schema.json 结构的 plan dict 文件，走 plan_from_dict(确定性)")
    g.add_argument("--tc-file", dest="tc_file", default=None,
                   help="文档级 TC JSON（可含单 TC 或 {'test_cases':[...]}）；缺省取 output/test_cases.json")
    ap.add_argument("--tc-id", default=None,
                    help="--tc-file 含多个 TC 时按 id 选择其一（默认取第一个）")
    ap.add_argument("--no-llm", action="store_true",
                    help="跳过 LLM：用确定性 plan_from_dict 解析 TC（步骤需已结构化）")
    ap.add_argument("--capability-dir", default="D:/higo-api",
                    help="可选：抓包目录，注入 API 知识给 LLM 做 TC→Plan")
    ap.add_argument("--out", default=None, help="输出 ExecutionPlan JSON 路径")
    ap.add_argument("--all", dest="plan_all", action="store_true",
                    help="汇聚模式：对 --tc-file 中全部 TC 生成计划，落盘单一 output/execution_plan.json")
    a = ap.parse_args()

    planner = ExecutionPlanner()

    if a.plan_all:
        return _main_plan_all(a, planner)

    if a.plan_data:
        plan_data = json.loads(Path(a.plan_data).read_text(encoding="utf-8"))
        plan = ExecutionPlanner.plan_from_dict(plan_data)
        mode = "plan_from_dict(确定性)"
    else:
        if not a.tc_file:
            default_tc = os.path.join(_PROJECT_ROOT, "output", "test_cases.json")
            if os.path.isfile(default_tc):
                a.tc_file = default_tc
                print(f">> 未给输入，默认取 {a.tc_file} 的第一条 TC（--no-llm 可避免触发 LLM）", flush=True)
            else:
                print("!! 未给 --tc-file/--plan-data，且默认 output/test_cases.json 不存在。\n"
                      "   请先跑 `python main.py`（S1–S5 产 TC）或显式传参。", flush=True)
                return 2
        tc_data = json.loads(Path(a.tc_file).read_text(encoding="utf-8"))
        tcs = tc_data.get("test_cases") if isinstance(tc_data, dict) and "test_cases" in tc_data else (
            [tc_data] if isinstance(tc_data, dict) else tc_data)
        if not tcs:
            print("!! 未在输入中找到 TC", flush=True)
            return 2
        tc = next((x for x in tcs if x.get("id") == a.tc_id), None) if a.tc_id else None
        tc = tc or tcs[0]
        print(f">> TC: {tc.get('id')}｜{tc.get('title')}", flush=True)
        if a.no_llm:
            plan = planner.plan(tc, None)
            mode = "plan(确定性, steps按manual)"
        else:
            capability = None
            if os.path.isdir(a.capability_dir):
                try:
                    from knowledge.capability import APICapability
                    cap = APICapability()
                    n = cap.load_from_whistle(a.capability_dir, max_files=200)
                    if n:
                        capability = cap
                        print(f">> 已注入 API 知识: {n} 条(抓包 {a.capability_dir})", flush=True)
                except Exception as e:  # 知识注入失败不影响 LLM 主流程
                    print(f">> 注: API 知识注入跳过({e})", flush=True)
            plan = ExecutionPlanner.plan_from_test_case(tc, capability=capability)
            mode = "plan_from_test_case(LLM)"

    plan_dict = plan.to_dict()
    out = a.out or os.path.join("output", "planner",
                                f"plan_{plan_dict['tc_id']}.json")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(plan_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(out).with_suffix(".md").write_text(
        _render_plan_md(plan_dict, mode, out), encoding="utf-8")

    print("=" * 46, flush=True)
    print(f"模式: {mode}", flush=True)
    print(f"TC  : {plan_dict['tc_id']}｜{plan_dict['title']}", flush=True)
    print(f"步骤: {len(plan_dict['steps'])} 条", flush=True)
    print("-" * 46, flush=True)
    for s in plan_dict["steps"]:
        print(_plan_step_line(s), flush=True)
    print("-" * 46, flush=True)
    print(f"JSON: {out}", flush=True)
    print(f"人读: {Path(out).with_suffix('.md')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
