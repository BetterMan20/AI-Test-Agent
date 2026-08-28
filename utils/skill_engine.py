import json
import re
from pathlib import Path

from jsonschema import validate
from jsonschema.exceptions import ValidationError

from utils.skill_loader import load_skill
from utils.llm import ask_llm
from utils.normalize import normalize_rule_field



class SkillEngine:

    MAX_RETRY = 2

    @staticmethod
    def run(
        skill_path,
        input_data,
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
                input_data
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

                # ===== 新增这里 =====
                data = SkillEngine._normalize(data, schema_path)

                print(
                    "③.5 Normalize 完成"
                )

                # ==================


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
    def _repair_json(text):
        """修复 LLM 输出 JSON 中常见语法错误"""
        # 移除尾随逗号: },] 或 },} 或 ],] 或 ],}
        text = re.sub(r",\s*([}\]])", r"\1", text)
        # 移除 } 前的尾随逗号（单独处理）
        text = re.sub(r",\s*}", "}", text)
        # 移除 ] 前的尾随逗号
        text = re.sub(r",\s*]", "]", text)
        # 修复单引号为双引号
        text = text.replace("'", '"')
        # 移除 JSON 前后的非 JSON 文本
        return text

    @staticmethod
    def _try_parse_json(text):
        """尝试解析 JSON，包含修复步骤"""
        # 1. 直接解析
        try:
            return json.loads(text, strict=False)
        except json.JSONDecodeError:
            pass

        # 2. 修复后解析
        repaired = SkillEngine._repair_json(text)
        try:
            return json.loads(repaired, strict=False)
        except json.JSONDecodeError:
            pass

        # 3. 逐层尝试：从最大范围到最小范围
        # 找所有可能的 JSON 起始位置
        for start in range(len(text)):
            if text[start] == '{':
                end = text.rfind('}')
                if end > start:
                    candidate = text[start:end + 1]
                    try:
                        return json.loads(candidate, strict=False)
                    except json.JSONDecodeError:
                        repaired = SkillEngine._repair_json(candidate)
                        try:
                            return json.loads(repaired, strict=False)
                        except json.JSONDecodeError:
                            continue

        raise ValueError("无法解析 JSON")

    @staticmethod
    def _parse_json(text):

        text = text.strip()

        # 1. Direct JSON
        try:
            return SkillEngine._try_parse_json(text)
        except (json.JSONDecodeError, ValueError):
            pass

        # 2. ```json
        match = re.search(
            r"```json\s*(.*?)\s*```",
            text,
            re.DOTALL | re.IGNORECASE
        )

        if match:
            try:
                return SkillEngine._try_parse_json(match.group(1))
            except (json.JSONDecodeError, ValueError):
                pass

        # 3. ```
        match = re.search(
            r"```\s*(.*?)\s*```",
            text,
            re.DOTALL
        )

        if match:
            try:
                return SkillEngine._try_parse_json(match.group(1))
            except (json.JSONDecodeError, ValueError):
                pass

        # 4. JSON Object - fallback
        start = text.find("{")
        end = text.rfind("}")

        if (
            start != -1
            and end != -1
            and end > start
        ):
            return SkillEngine._try_parse_json(
                text[start:end + 1]
            )

        raise ValueError(
            "无法从 LLM 输出中提取 JSON"
        )

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
            data = SkillEngine._normalize_analysis(data)

        # ===============================
        # Test Design
        # ===============================

        if schema_path and schema_path.endswith(
                "test_design.schema.json"
        ):
            data = SkillEngine._normalize_dimensions(
                data
            )

        # ===============================
        # Validation Result
        # ===============================

        if schema_path and schema_path.endswith(
                "test_case_validation.schema.json"
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

        array_fields = [
            "issues",
            "validated_testcases",
            "uncovered_requirements",
            "uncovered_designs"
        ]

        if isinstance(data, dict):

            for key, value in data.items():

                if key in array_fields:

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

        array_fields = [
            "modules",
            "testcases",
            "steps"
        ]

        if isinstance(data, dict):

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
    def _normalize_analysis(data):

        array_fields = [
            "actors",
            "rules",
            "states",
            "relations",
            "constraints",
            "source_facts",
            "related_analysis"
        ]

        if isinstance(data, dict):

            for key, value in data.items():

                if key in array_fields:

                    if isinstance(value, dict):
                        data[key] = [value]

                    elif isinstance(value, str):
                        data[key] = [value]

                else:

                    SkillEngine._normalize_analysis(value)

        elif isinstance(data, list):

            for item in data:
                SkillEngine._normalize_analysis(item)

        return data