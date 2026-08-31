import json
import re
from pathlib import Path

from jsonschema import validate
from jsonschema.exceptions import ValidationError

from utils.skill_loader import load_skill
from utils.llm import ask_llm
from utils.normalize import normalize_rule_field



class SkillEngine:

    MAX_RETRY = 3

    @staticmethod
    def run(
        skill_path,
        user_input,
        schema_path=None,
        output_mode="text"
    ):

        print("=" * 50)
        print("SkillEngine 启动")
        print(f"Skill 路径：{skill_path}")
        print(f"Output Mode：{output_mode}")

        # ==================================================
        # 1. 参数检查
        # ==================================================

        if output_mode not in ("text", "json"):
            raise ValueError(
                f"不支持的 output_mode: {output_mode}"
            )

        if output_mode == "json" and not schema_path:
            raise ValueError(
                "JSON 模式必须提供 schema_path"
            )

        # ==================================================
        # 2. Load Skill
        # ==================================================

        print("① 开始加载 Skill...")

        system_prompt = load_skill(
            skill_path
        )

        print("① Skill 加载完成")

        # ==================================================
        # 3. Load Schema
        # ==================================================

        schema = None

        if output_mode == "json":

            schema = SkillEngine._load_schema(
                schema_path
            )

            print(
                f"Schema：{schema_path}"
            )

        # ==================================================
        # 4. 原始输入
        # ==================================================

        original_input = (
            SkillEngine._serialize_input(
                user_input
            )
        )

        current_input = original_input

        # ==================================================
        # 5. Retry
        # ==================================================

        for attempt in range(
            1,
            SkillEngine.MAX_RETRY + 1
        ):

            print(
                f"② 开始调用 LLM... "
                f"(attempt {attempt})"
            )

            result = ask_llm(
                system_prompt,
                current_input
            )

            print(
                "LLM 输出长度：",
                len(result)
            )

            # ==================================================
            # TEXT MODE
            # ==================================================

            if output_mode == "text":

                if not result.strip():

                    raise ValueError(
                        "LLM 返回内容为空"
                    )

                print(
                    "③ Text 输出校验通过"
                )

                print(
                    "⑤ SkillEngine 完成"
                )

                print("=" * 50)

                return result.strip()

            # ==================================================
            # JSON MODE
            # ==================================================

            try:

                data = SkillEngine._parse_json(
                    result
                )

                print(
                    "③ JSON 解析成功"
                )

                data = SkillEngine._normalize(data, schema_path)

                data = SkillEngine._fill_defaults(data, schema)

                print(
                    "③.5 Normalize 完成"
                )


            except Exception as e:

                print(
                    "③ JSON 解析失败：",
                    e
                )

                if attempt >= SkillEngine.MAX_RETRY:
                    raise ValueError(
                        f"LLM 输出无法解析为合法 JSON：{e}"
                    )

                current_input = (
                    SkillEngine
                    ._build_json_retry_prompt(
                        original_input=original_input,
                        error=str(e)
                    )
                )

                continue

            # ==================================================
            # Schema Validate
            # ==================================================

            try:

                validate(
                    instance=data,
                    schema=schema
                )

                print(
                    "④ Schema 校验通过"
                )

            except ValidationError as e:

                print(
                    "④ Schema 校验失败：",
                    e.message
                )

                if attempt >= SkillEngine.MAX_RETRY:

                    raise ValueError(
                        "Schema 校验失败："
                        + SkillEngine
                        ._format_validation_error(e)
                    )

                current_input = (
                    SkillEngine
                    ._build_schema_retry_prompt(
                        original_input=original_input,
                        error=(
                            SkillEngine
                            ._format_validation_error(e)
                        )
                    )
                )

                continue

            # ==================================================
            # Success
            # ==================================================

            print(
                "⑤ SkillEngine 完成"
            )

            print("=" * 50)

            return data

        raise RuntimeError(
            "SkillEngine 执行失败"
        )

    # ======================================================
    # Schema Loader
    # ======================================================

    @staticmethod
    def _load_schema(schema_path):

        path = Path(schema_path)

        if not path.exists():

            raise FileNotFoundError(
                f"Schema 不存在：{path.resolve()}"
            )

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    # ======================================================
    # Serialize
    # ======================================================

    @staticmethod
    def _serialize_input(data):

        if isinstance(data, (dict, list)):

            return json.dumps(
                data,
                ensure_ascii=False,
                indent=2
            )

        return str(data)

    # ======================================================
    # JSON Parser
    # ======================================================

    @staticmethod
    def _clean_json_text(text):
        result = []
        i = 0
        n = len(text)
        in_string = False
        escaped = False

        while i < n:
            ch = text[i]

            if in_string:
                if escaped:
                    result.append(ch)
                    escaped = False
                    i += 1
                elif ch == '\\':
                    result.append(ch)
                    escaped = True
                    i += 1
                elif ch == '"':
                    result.append(ch)
                    in_string = False
                    i += 1
                elif ch == '\n':
                    result.append('\\n')
                    i += 1
                elif ch == '\r':
                    result.append('\\r')
                    i += 1
                elif ch == '\t':
                    result.append('\\t')
                    i += 1
                else:
                    result.append(ch)
                    i += 1
            else:
                if ch == '/' and i + 1 < n and text[i + 1] == '/':
                    while i < n and text[i] != '\n':
                        i += 1
                elif ch == '/' and i + 1 < n and text[i + 1] == '*':
                    i += 2
                    while i + 1 < n and not (
                        text[i] == '*' and text[i + 1] == '/'
                    ):
                        i += 1
                    i += 2
                elif ch == '"':
                    result.append(ch)
                    in_string = True
                    i += 1
                else:
                    result.append(ch)
                    i += 1

        text = ''.join(result)

        text = re.sub(
            r',\s*\.\.\.\s*(?=[\]\) }])', '', text
        )
        text = re.sub(
            r'\[\s*\.\.\.\s*\]', '[]', text
        )
        text = re.sub(
            r',\s*\.\.\.', '', text
        )
        text = re.sub(
            r'\.\.\.,?', '', text
        )
        text = re.sub(
            r',\s*([}\]])', r'\1', text
        )
        return text

    @staticmethod
    def _parse_json(text):

        text = text.strip()

        # 1. Direct JSON
        try:

            return json.loads(text)

        except json.JSONDecodeError:

            pass

        # 2. ```json blocks - collect ALL and merge if multiple
        json_blocks = []
        for match in re.finditer(
            r"```json\s*(.*?)\s*```",
            text,
            re.DOTALL | re.IGNORECASE
        ):
            cleaned = SkillEngine._clean_json_text(
                match.group(1)
            )
            try:
                parsed = json.loads(cleaned)
                json_blocks.append(parsed)
            except json.JSONDecodeError:
                pass

        if len(json_blocks) == 1:
            return json_blocks[0]

        if len(json_blocks) > 1:
            merged = SkillEngine._merge_json_blocks(
                json_blocks
            )
            if merged is not None:
                return merged

        # 3. ``` blocks - collect ALL and merge if multiple
        json_blocks = []
        for match in re.finditer(
            r"```\s*(.*?)\s*```",
            text,
            re.DOTALL
        ):
            cleaned = SkillEngine._clean_json_text(
                match.group(1)
            )
            try:
                parsed = json.loads(cleaned)
                json_blocks.append(parsed)
            except json.JSONDecodeError:
                pass

        if len(json_blocks) == 1:
            return json_blocks[0]

        if len(json_blocks) > 1:
            merged = SkillEngine._merge_json_blocks(
                json_blocks
            )
            if merged is not None:
                return merged

        # 4. JSON Object - try first { to last }
        start = text.find("{")
        end = text.rfind("}")

        if (
            start != -1
            and end != -1
            and end > start
        ):
            cleaned = SkillEngine._clean_json_text(
                text[start:end + 1]
            )
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

        # 5. Try each { position from end to find valid JSON
        brace_positions = [
            i for i, ch in enumerate(text) if ch == "{"
        ]

        best_result = None
        best_len = 0

        for pos in reversed(brace_positions):
            end_pos = text.rfind("}", pos)
            if end_pos == -1 or end_pos <= pos:
                continue

            candidate = text[pos:end_pos + 1]

            cleaned = SkillEngine._clean_json_text(candidate)

            try:
                result = json.loads(cleaned)
                if isinstance(result, dict):
                    result_len = len(candidate)
                    if result_len > best_len:
                        best_result = result
                        best_len = result_len
            except json.JSONDecodeError:
                continue

        if best_result is not None:
            return best_result

        raise ValueError(
            "无法从 LLM 输出中提取 JSON"
        )

    @staticmethod
    def _merge_json_blocks(blocks):

        if not blocks:
            return None

        has_design_id = all(
            isinstance(b, dict) and "design_id" in b
            for b in blocks
        )

        if has_design_id:
            return {
                "schema_version": "1.0",
                "project": "",
                "modules": [
                    {
                        "name": "default",
                        "test_designs": blocks
                    }
                ],
                "blocked_designs": []
            }

        has_title = all(
            isinstance(b, dict) and "title" in b
            for b in blocks
        )

        if has_title:
            return {
                "project": "",
                "modules": [
                    {
                        "name": "default",
                        "testcases": blocks
                    }
                ]
            }

        first = blocks[0]
        if isinstance(first, dict):
            for b in blocks[1:]:
                if isinstance(b, dict):
                    for k, v in b.items():
                        if k in first:
                            if isinstance(first[k], list):
                                first[k].extend(
                                    v if isinstance(v, list) else [v]
                                )
                            elif isinstance(first[k], dict) and isinstance(v, dict):
                                first[k].update(v)
                        else:
                            first[k] = v
            return first

        return blocks[0]

    # ======================================================
    # Validation Error
    # ======================================================

    @staticmethod
    def _format_validation_error(error):

        path = "root"

        for item in error.absolute_path:

            if isinstance(item, int):

                path += f"[{item}]"

            else:

                path += f".{item}"

        return (
            f"字段路径：{path}\n"
            f"错误类型：{error.validator}\n"
            f"错误信息：{error.message}\n"
            f"Schema要求：{error.validator_value}"
        )

    # ======================================================
    # JSON Retry
    # ======================================================

    @staticmethod
    def _build_json_retry_prompt(
        original_input,
        error
    ):

        return f"""
你上一轮输出没有通过 JSON 解析。

错误：
{error}

请基于下面的原始输入重新执行当前 Skill：

===== 原始输入 =====
{original_input}
===== 原始输入结束 =====

要求：

1. 只输出合法 JSON。
2. 不输出 Markdown。
3. 不输出 ```json。
4. 不输出解释。
5. 完整执行当前 Skill。
6. 不得遗漏 required 字段。
7. 不得创造原始需求中不存在的业务规则。

只输出最终 JSON。
"""

    # ======================================================
    # Schema Retry
    # ======================================================

    @staticmethod
    def _build_schema_retry_prompt(
        original_input,
        error
    ):

        return f"""
你上一轮输出虽然是合法 JSON，
但是没有通过当前 Skill 的 JSON Schema。

Schema 错误：

{error}

请重新基于下面的原始输入执行当前 Skill：

===== 原始输入 =====
{original_input}
===== 原始输入结束 =====

要求：

1. 修复 Schema 错误。
2. 完整输出 JSON。
3. 不遗漏 required 字段。
4. 字段类型必须符合 Schema。
5. 不删除已经正确的业务信息。
6. 不创造原始需求中不存在的业务规则。
7. 不输出 Markdown。
8. 不输出 ```json。
9. 不输出解释。

只输出最终 JSON。
"""


    @staticmethod
    def _clean_value(data):
        if isinstance(data, str):
            return data.strip()
        if isinstance(data, dict):
            return {
                k: SkillEngine._clean_value(v)
                for k, v in data.items()
            }
        if isinstance(data, list):
            return [
                SkillEngine._clean_value(item)
                for item in data
            ]
        return data

    @staticmethod
    def _normalize(data, schema_path=None):

        # ===============================
        # 基础递归清理
        # ===============================

        data = SkillEngine._clean_value(data)

        # ===============================
        # Requirement Analysis
        # ===============================

        if schema_path and schema_path.endswith(
                "requirement_analysis.schema.json"
        ):
            data = SkillEngine._normalize_rules(
                data
            )

        # ===============================
        # Test Design
        # ===============================

        if schema_path and schema_path.endswith(
                "test_design.schema.json"
        ):
            data = SkillEngine._normalize_dimensions(
                data
            )
            data = SkillEngine._normalize_test_design(
                data
            )

        # ===============================
        # Validation Result
        # ===============================

        if schema_path and schema_path.endswith(
                "validation_result.schema.json"
        ):
            data = SkillEngine._normalize_validation(data)

        # ===============================
        # Test Case
        # ===============================

        if schema_path and schema_path.endswith(
                "test_case.schema.json"
        ):
            data = SkillEngine._normalize_test_cases(data)

        return data

    @staticmethod
    def _fill_defaults(data, schema):
        if not isinstance(data, dict) or not isinstance(schema, dict):
            return data
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        for field in required:
            if field not in data:
                field_schema = properties.get(field, {})
                if field_schema.get("type") == "array":
                    data[field] = []
        return data

    @staticmethod
    def _normalize_test_design(data):
        if isinstance(data, list):
            items = [
                d for d in data
                if isinstance(d, dict) and "design_id" in d
            ]
            if items:
                data = {
                    "schema_version": "1.0",
                    "project": "",
                    "modules": [
                        {
                            "name": "default",
                            "test_designs": items
                        }
                    ]
                }

        if not isinstance(data, dict):
            return data

        if "design_id" in data and "modules" not in data:
            design = data
            data = {
                "schema_version": "1.0",
                "project": "",
                "design_summary": "",
                "coverage": {
                    "requirement_rules": 0,
                    "covered_rules": 0,
                    "coverage_rate": 0,
                    "uncovered_rules": []
                },
                "modules": [
                    {
                        "name": "default",
                        "test_designs": [design]
                    }
                ],
                "blocked_designs": []
            }

        if not data.get("project"):
            data["project"] = "unnamed_project"

        if not data.get("schema_version"):
            data["schema_version"] = "1.0"

        if not data.get("design_summary"):
            modules = data.get("modules", [])
            module_name = ""
            if isinstance(modules, list) and modules:
                first = modules[0]
                if isinstance(first, dict):
                    module_name = first.get("name", "")
            data["design_summary"] = (
                module_name + "测试设计"
                if module_name
                else "测试设计"
            )

        if not isinstance(data.get("coverage"), dict):
            data["coverage"] = {
                "requirement_rules": 0,
                "covered_rules": 0,
                "coverage_rate": 0,
                "uncovered_rules": []
            }

        coverage = data.get("coverage")
        if isinstance(coverage, dict):
            rate = coverage.get("coverage_rate")
            if isinstance(rate, (int, float)) and rate > 1:
                coverage["coverage_rate"] = rate / 100.0
            if "requirement_rules" not in coverage:
                coverage["requirement_rules"] = 0
            if "covered_rules" not in coverage:
                coverage["covered_rules"] = 0
            if "coverage_rate" not in coverage:
                coverage["coverage_rate"] = 0
            if "uncovered_rules" not in coverage:
                coverage["uncovered_rules"] = []

        top_blocked = data.get("blocked_designs", [])
        if not isinstance(top_blocked, list):
            top_blocked = [top_blocked] if top_blocked else []

        modules = data.get("modules", [])
        if isinstance(modules, list):
            for module in modules:
                if isinstance(module, dict) and "blocked_designs" in module:
                    nested = module.pop("blocked_designs")
                    if isinstance(nested, list):
                        top_blocked.extend(nested)
                    elif isinstance(nested, dict):
                        top_blocked.append(nested)

        data["blocked_designs"] = top_blocked

        if isinstance(modules, list):
            for module in modules:
                if not isinstance(module, dict):
                    continue
                test_designs = module.get("test_designs", [])
                if isinstance(test_designs, dict):
                    test_designs = [test_designs]
                    module["test_designs"] = test_designs
                if isinstance(test_designs, list):
                    for td in test_designs:
                        if isinstance(td, dict):
                            SkillEngine._normalize_test_design_item(td)

        covered_refs = set()
        if isinstance(modules, list):
            for module in modules:
                if not isinstance(module, dict):
                    continue
                for td in module.get("test_designs", []):
                    if isinstance(td, dict):
                        for ref in td.get("requirement_refs", []):
                            covered_refs.add(ref)

        coverage = data.get("coverage")
        if isinstance(coverage, dict):
            if coverage.get("requirement_rules", 0) == 0:
                coverage["requirement_rules"] = len(covered_refs)
            if coverage.get("covered_rules", 0) == 0:
                coverage["covered_rules"] = len(covered_refs)
            req_rules = coverage.get("requirement_rules", 0)
            cov_rules = coverage.get("covered_rules", 0)
            if req_rules > 0:
                coverage["coverage_rate"] = min(
                    cov_rules / req_rules, 1.0
                )
            else:
                coverage["coverage_rate"] = 0

        return data

    @staticmethod
    def _normalize_test_design_item(td):
        if "test_object" in td and isinstance(td["test_object"], list):
            td["test_object"] = ", ".join(
                str(x) for x in td["test_object"]
            )

        required_arrays = [
            "conditions",
            "data_dimensions",
            "time_dimensions",
            "state_dimensions",
            "source_dimensions",
            "test_methods",
            "expected_behavior",
            "coverage_targets",
            "requirement_refs"
        ]
        for field in required_arrays:
            if field not in td:
                td[field] = []

        if "scenario" not in td or not td.get("scenario"):
            td["scenario"] = td.get(
                "test_goal", "验证业务规则"
            )

        if "test_methods" in td and isinstance(td["test_methods"], list):
            td["test_methods"] = [
                SkillEngine._map_test_method(m)
                if isinstance(m, str) else m
                for m in td["test_methods"]
            ]
            if not td["test_methods"]:
                td["test_methods"] = ["normal_flow"]

        if "conditions" in td and isinstance(td["conditions"], list):
            normalized = []
            for item in td["conditions"]:
                if isinstance(item, str):
                    normalized.append({
                        "name": item,
                        "value": item,
                        "type": "precondition"
                    })
                elif isinstance(item, dict):
                    if "name" not in item:
                        item["name"] = item.get("value", "condition")
                    if "value" not in item:
                        item["value"] = item.get("name", "")
                    if "type" not in item:
                        item["type"] = "precondition"
                    normalized.append(item)
            td["conditions"] = normalized

        for dim_key in ("data_dimensions", "time_dimensions", "source_dimensions"):
            if dim_key in td and isinstance(td[dim_key], list):
                normalized = []
                for item in td[dim_key]:
                    if isinstance(item, str):
                        normalized.append({
                            "name": item,
                            "values": [item]
                        })
                    elif isinstance(item, dict):
                        if "name" not in item:
                            item["name"] = "dimension"
                        if "values" not in item:
                            item["values"] = [item.get("name", "")]
                        normalized.append(item)
                td[dim_key] = normalized

        if "state_dimensions" in td and isinstance(td["state_dimensions"], list):
            normalized = []
            for item in td["state_dimensions"]:
                if isinstance(item, str):
                    parts = item.split("→") if "→" in item else item.split("->")
                    if len(parts) == 2:
                        normalized.append({
                            "from": parts[0].strip(),
                            "to": parts[1].strip()
                        })
                    else:
                        normalized.append({
                            "from": item,
                            "to": item
                        })
                elif isinstance(item, dict):
                    if "from" not in item:
                        item["from"] = "start"
                    if "to" not in item:
                        item["to"] = "end"
                    normalized.append(item)
            td["state_dimensions"] = normalized

        if "coverage_targets" in td:
            ct = td["coverage_targets"]
            if isinstance(ct, str):
                ct = [ct]
            elif isinstance(ct, dict):
                ct = [ct]
            if isinstance(ct, list):
                normalized = []
                for item in ct:
                    if isinstance(item, str):
                        type_val = SkillEngine._map_coverage_type(
                            item
                        )
                        normalized.append(
                            {"type": type_val, "target": item}
                        )
                    elif isinstance(item, dict):
                        if "type" in item:
                            item["type"] = SkillEngine._map_coverage_type(item["type"])
                        if "type" in item and "target" not in item:
                            item["target"] = item.get("type", "")
                        normalized.append(item)
                td["coverage_targets"] = normalized

        if "expected_behavior" in td and isinstance(
            td["expected_behavior"], str
        ):
            td["expected_behavior"] = [td["expected_behavior"]]

    @staticmethod
    def _map_coverage_type(value):

        valid_types = {
            "requirement_rule", "business_rule", "state",
            "boundary", "condition", "data", "time",
            "source", "cross_module", "risk", "scenario"
        }

        if value in valid_types:
            return value

        mapping = {
            "source_coverage": "source",
            "source_rule": "source",
            "requirement": "requirement_rule",
            "precondition_rule": "requirement_rule",
            "precondition": "requirement_rule",
            "constraint_rule": "condition",
            "constraint": "condition",
            "business": "business_rule",
            "state_rule": "state",
            "time_rule": "time",
            "data_rule": "data",
            "condition_rule": "condition",
            "boundary_rule": "boundary",
            "risk_rule": "risk",
            "scenario_rule": "scenario",
            "cross module": "cross_module",
            "cross-module": "cross_module",
        }

        result = mapping.get(value)

        if result:
            return result

        lower = value.lower().strip()
        result = mapping.get(lower)
        if result:
            return result

        if "business" in lower or "业务" in value:
            return "business_rule"
        if "state" in lower or "状态" in value:
            return "state"
        if "time" in lower or "时间" in value:
            return "time"
        if "source" in lower or "来源" in lower or "渠道" in value:
            return "source"
        if "data" in lower or "数据" in value:
            return "data"
        if "condition" in lower or "条件" in value or "约束" in value:
            return "condition"
        if "boundary" in lower or "边界" in value:
            return "boundary"
        if "risk" in lower or "风险" in value:
            return "risk"
        if "scenario" in lower or "场景" in value:
            return "scenario"
        if "cross" in lower or "跨" in value:
            return "cross_module"
        if "requirement" in lower or "需求" in value or "规则" in value:
            return "requirement_rule"

        return "requirement_rule"

    @staticmethod
    def _map_test_method(value):

        valid_methods = {
            "normal_flow", "equivalence_partitioning",
            "boundary_value", "state_transition",
            "decision_table", "cause_effect",
            "condition_combination", "error_guessing",
            "scenario", "data_combination",
            "time_boundary", "state_time",
            "state_condition", "source_condition",
            "cross_module"
        }

        if value in valid_methods:
            return value

        mapping = {
            "time_dimension": "time_boundary",
            "time_coverage": "time_boundary",
            "time_validation": "time_boundary",
            "timing": "time_boundary",
            "timing_validation": "time_boundary",
            "state_rule": "state_transition",
            "source_rule": "source_condition",
            "source_validation": "source_condition",
            "data_dimension": "data_combination",
            "data_coverage": "data_combination",
            "data_transaction": "data_combination",
            "functional": "normal_flow",
            "validation": "normal_flow",
            "operation_validation": "normal_flow",
            "display_check": "scenario",
            "ui_validation": "scenario",
            "comparison": "source_condition",
            "reward_check": "data_combination",
            "limit_validation": "boundary_value",
            "concurrency": "error_guessing",
            "comprehensive": "cross_module",
            "cause_effect": "cause_effect",
        }
        result = mapping.get(value.lower().strip(), "normal_flow")
        return result

    @staticmethod
    def _normalize_dimensions(data):

        fields = [
            "data_dimensions",
            "time_dimensions",
            "source_dimensions",
            "state_dimensions",
            "conditions",
            "coverage_targets",
            "expected_behavior",
            "requirement_refs",
            "test_methods"
        ]

        if isinstance(data, dict):

            for key, value in data.items():

                if key in fields:

                    if isinstance(value, dict):
                        data[key] = [value]

                    elif isinstance(value, str):
                        data[key] = [value]

                else:

                    SkillEngine._normalize_dimensions(
                        value
                    )


        elif isinstance(data, list):

            for item in data:
                SkillEngine._normalize_dimensions(
                    item
                )

        return data

    @staticmethod
    def _normalize_validation(data):

        quality_status_fields = {
            "traceability",
            "correctness",
            "completeness",
            "executability",
            "verifiability",
            "extrapolation",
            "duplication",
            "requirement_compliance",
            "design_compliance"
        }

        status_map = {
            "n/a": "FAIL",
            "na": "FAIL",
            "not_applicable": "FAIL",
            "not applicable": "FAIL",
            "skip": "FAIL",
            "skipped": "FAIL",
            "none": "FAIL",
            "todo": "FAIL",
            "pending": "FAIL",
            "blocked": "PARTIAL",
        }

        overall_status_map = {
            "n/a": "FAIL",
            "na": "FAIL",
            "not_applicable": "FAIL",
            "not applicable": "FAIL",
            "skip": "FAIL",
            "skipped": "FAIL",
            "none": "FAIL",
            "todo": "FAIL",
            "pending": "FAIL",
            "blocked": "BLOCKED",
            "partial": "FAIL",
        }

        issue_type_map = {
            "test_case_missing": "design_not_implemented",
            "requirement_missing": "requirement_missing",
            "missing_requirement": "requirement_missing",
        }

        valid_issue_types = {
            "requirement_extrapolation",
            "requirement_missing",
            "requirement_traceability_failure",
            "design_traceability_failure",
            "design_not_implemented",
            "incorrect_test_condition",
            "incorrect_expected_result",
            "missing_expected_result",
            "unexecutable_step",
            "ambiguous_step",
            "ambiguous_expected_result",
            "boundary_missing",
            "state_coverage_missing",
            "condition_coverage_missing",
            "data_coverage_missing",
            "time_coverage_missing",
            "source_coverage_missing",
            "cross_module_coverage_missing",
            "duplicate_testcase",
            "duplicate_design",
            "invalid_test_method",
            "invalid_test_data",
            "invalid_state",
            "invalid_time",
            "schema_violation",
            "blocked_by_requirement_ambiguity",
            "other",
        }

        array_fields = [
            "issues",
            "validated_testcases",
            "uncovered_requirements",
            "uncovered_designs"
        ]

        if isinstance(data, dict):

            for key, value in data.items():

                if key in quality_status_fields and isinstance(
                    value, str
                ):
                    mapped = status_map.get(
                        value.lower().strip()
                    )
                    if mapped:
                        data[key] = mapped
                    elif value.upper().strip() not in (
                        "PASS", "FAIL", "PARTIAL"
                    ):
                        data[key] = "FAIL"

                elif key == "status" and isinstance(
                    value, str
                ):
                    mapped = overall_status_map.get(
                        value.lower().strip()
                    )
                    if mapped:
                        data[key] = mapped
                    elif value.upper().strip() not in (
                        "PASS", "FAIL", "BLOCKED"
                    ):
                        data[key] = "FAIL"

                elif key == "type" and isinstance(
                    value, str
                ):
                    if value not in valid_issue_types:
                        mapped = issue_type_map.get(
                            value.lower().strip(), "other"
                        )
                        data[key] = mapped

                elif key in (
                    "requirement_coverage_rate",
                    "design_coverage_rate"
                ) and isinstance(value, (int, float)):
                    if value > 1:
                        data[key] = value / 100.0

                elif key in array_fields:

                    if isinstance(value, dict):
                        data[key] = [value]

                    elif isinstance(value, str):
                        data[key] = [value]

                else:

                    SkillEngine._normalize_validation(value)

        elif isinstance(data, list):

            for item in data:
                SkillEngine._normalize_validation(item)

        return data

    @staticmethod
    def _normalize_test_cases(data):

        if isinstance(data, list):
            items = [
                d for d in data
                if isinstance(d, dict) and "title" in d
            ]
            if items:
                data = {
                    "project": "",
                    "modules": [
                        {
                            "name": "default",
                            "testcases": items
                        }
                    ]
                }

        if not isinstance(data, dict):
            return data

        if "title" in data and "modules" not in data:
            tc = data
            data = {
                "project": "",
                "modules": [
                    {
                        "name": "default",
                        "testcases": [tc]
                    }
                ]
            }

        array_fields = [
            "modules",
            "testcases",
            "steps"
        ]

        if isinstance(data, dict):

            if "title" in data and (
                "action" in data or "expected" in data
            ):
                if "steps" not in data:
                    step = {}
                    if "action" in data:
                        step["action"] = data.pop("action")
                    if "expected" in data:
                        step["expected"] = data.pop("expected")
                    data["steps"] = [step]

            for key, value in data.items():

                if key in array_fields:

                    if isinstance(value, dict):
                        data[key] = [value]

                    elif isinstance(value, str):
                        data[key] = [value]

                else:

                    SkillEngine._normalize_test_cases(value)

        elif isinstance(data, list):

            for item in data:
                SkillEngine._normalize_test_cases(item)

        return data

    @staticmethod
    def _normalize_rules(data):

        rule_item_fields = {
            "business_context",
            "preconditions",
            "business_rules",
            "state_rules",
            "data_rules",
            "time_rules",
            "source_rules",
            "constraints"
        }

        if isinstance(data, dict):

            for key, value in data.items():

                if key in rule_item_fields and isinstance(
                    value, list
                ):
                    data[key] = [
                        SkillEngine._normalize_rule_item(
                            item
                        )
                        for item in value
                    ]

                elif key == "rules" and isinstance(
                    value, list
                ):
                    data[key] = "\n".join(
                        value
                    )

                else:

                    SkillEngine._normalize_rules(
                        value
                    )


        elif isinstance(data, list):

            for item in data:
                SkillEngine._normalize_rules(
                    item
                )

        return data

    @staticmethod
    def _normalize_rule_item(obj):
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            if "object" in obj or "states" in obj or "transitions" in obj:
                return obj
            if "source" in obj and "rule" in obj:
                return obj
            source = obj.get(
                "source", obj.get("type", "")
            )
            rule = (
                obj.get("rule")
                or obj.get("description")
                or obj.get("content")
                or ""
            )
            if not rule and "from" in obj and "to" in obj:
                rule = (
                    f"{obj['from']} → {obj['to']}"
                )
                if "condition" in obj:
                    rule += f"：{obj['condition']}"
            if not source and not rule:
                rule = ", ".join(
                    str(v) for v in obj.values()
                )
            return {
                "source": source,
                "rule": rule
            }
        return str(obj)