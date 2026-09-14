import json
import re
import time
from pathlib import Path

from jsonschema import validate
from jsonschema.exceptions import ValidationError

from utils.skill_loader import load_skill
from utils.llm import ask_llm



class SkillEngine:

    MAX_RETRY = 3

    # 统一的 JSON 卫生硬性要求（追加到所有 JSON 模式 Skill 的 system prompt）
    _JSON_HYGIENE_RULE = r"""

【JSON 硬性输出要求 —— 违反即失败，必须遵守】
1. 你的输出必须且只能是一个能被标准 json.loads() 直接解析的完整 JSON 对象，不得包含任何多余文字。
2. 严禁输出 Markdown 围栏（``` ```json）、代码块标记、解释说明或前后缀。
3. 字符串值（尤其是 content / description / message 等中文文案字段）内部的任何引号，一律使用中文全角引号 “ ” 或 『』「」，严禁在字符串内部使用未转义的英文双引号 "。
4. 若确需在字符串内包含英文双引号，必须写成 \"（反斜杠+引号转义）。
5. 每个字符串值必须正确配对，不要遗漏字段值、不要多写一个引号、不要遗漏闭括号。
"""

    @staticmethod
    def run(
        skill_path,
        input_data,
        schema_path=None,
        output_mode="text",
        collect_stats=False,
        max_tokens=32000,
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

        # JSON 模式：统一追加"JSON 卫生"硬性要求，治 LLM 把中文文案里的
        # 引号写成裸 ASCII 双引号、导致整份 JSON 解析失败的病根。
        if output_mode == "json":

            system_prompt += SkillEngine._JSON_HYGIENE_RULE

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

        _attempts_used = 0
        _usage = {"input_tokens": 0, "output_tokens": 0}

        def _finish(res):
            stats = {
                "retry_count": max(0, _attempts_used - 1),
                "input_tokens": _usage["input_tokens"],
                "output_tokens": _usage["output_tokens"],
            }
            return (res, stats) if collect_stats else res

        for attempt in range(
            1,
            SkillEngine.MAX_RETRY + 1
        ):

            _attempts_used = attempt

            print(
                f"② 开始调用 LLM... "
                f"(attempt {attempt})"
            )

            try:

                result, _usage = ask_llm(
                    system_prompt,
                    current_input,
                    return_usage=True,
                    max_tokens=max_tokens,
                )

            except Exception as e:

                # 网络/API 层失败（超时、连接重置等）。原实现只对 JSON/Schema
                # 解析失败重试，APITimeoutError 会直接冒出整条管线把 E2E 打崩。
                # 这里对任何 ask_llm 抛出的异常做短暂退避重试：限流/闪断多为
                # 偶发，退避重试即可扛过；到顶仍失败才向上抛。
                print(
                    "⚠ SkillEngine: LLM API 调用异常，"
                    f"({type(e).__name__}: {e})，"
                    f"退避重试 attempt {attempt}/{SkillEngine.MAX_RETRY}"
                )

                if attempt >= SkillEngine.MAX_RETRY:
                    raise

                time.sleep(5 * attempt)
                continue

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

                return _finish(result.strip())

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

                # ===== 关键：schema 感知的"整份文档"检查 =====
                # 当 LLM 输出的整份 JSON 损坏时，_parse_json 可能捡到某个
                # 内层对象片段（如单个 relation）冒充整份文档。此时 fragment
                # 的顶层键与 schema.root.properties 几乎不重合。与其让 schema
                # 报出难懂的 additionalProperties 错误，不如直接判定为
                # "未提取到完整 JSON"，走 JSON 结构性重试（提示更明确、更有效）。
                if SkillEngine._is_fragment_of(data, schema):
                    raise ValueError(
                        "未能提取到完整 JSON：解析结果仅是内层片段"
                        "(顶层键与输出文档要求的根字段几乎不重合)。"
                        "请输出完整的根对象，包含全部 required 顶层字段。"
                    )

                # ===== 新增这里 =====
                data = SkillEngine._normalize(data, schema_path)

                # 修复 LLM 生成的 TC ID 格式
                if isinstance(data, dict) and "test_cases" in data:
                    SkillEngine._fix_tc_ids(data)

                print(
                    "③.5 Normalize 完成"
                )

                # ==================


            except Exception as e:

                print(
                    "③ JSON 解析失败：",
                    e
                )

                # 保存原始 LLM 输出用于调试
                from utils.output import Output
                Output.save(f"llm_raw_output_attempt{attempt}.txt", result)
                print(f"   已保存原始 LLM 输出到: llm_raw_output_attempt{attempt}.txt")

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

                # 保存原始 LLM 输出用于调试
                from utils.output import Output
                Output.save(
                    f"llm_schema_output_attempt{attempt}.txt",
                    result
                )

                if attempt >= SkillEngine.MAX_RETRY:

                    # 最终兜底：若仅仅因"数组为空/字段缺失"这类小问题，
                    # 尝试剔除空数组后重验，避免整条管线崩溃。
                    repaired = SkillEngine._salvage_for_schema(
                        data, schema
                    )
                    if repaired is not None:
                        print(
                            "⚠ 已按兜底策略修复(剔除空数组/补默认字段)后通过校验"
                        )
                        return _finish(repaired)

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
                        ),
                        data=data,
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

            return _finish(data)

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
        # 移除 // 单行注释（仅在字符串外部）
        text = SkillEngine._strip_json_comments(text)
        # 移除 /* */ 块注释
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
        # 移除尾随逗号: },] 或 },} 或 ],] 或 ],}
        text = re.sub(r",\s*([}\]])", r"\1", text)
        # 移除 } 前的尾随逗号（单独处理）
        text = re.sub(r",\s*}", "}", text)
        # 移除 ] 前的尾随逗号
        text = re.sub(r",\s*]", "]", text)
        # 修复单引号为双引号
        text = text.replace("'", '"')
        # 修复字符串内部的未转义双引号（LLM 常把 UI 文案写成"...为"发送"，可点击"）
        text = SkillEngine._escape_inner_quotes(text)
        # 移除空行
        text = re.sub(r'\n\s*\n', '\n', text)
        return text

    @staticmethod
    def _is_cjk(ch: str) -> bool:
        """是否 CJK 汉字 / 中文全角 / 全角标点（用于识别"字符串内部的中文引号"）。"""
        if not ch or len(ch) != 1:
            return False
        o = ord(ch)
        return (0x2E80 <= o <= 0x9FFF) or (0xFF00 <= o <= 0xFFEF)

    @staticmethod
    def _escape_inner_quotes(text: str) -> str:
        """确定性修复：把字符串内部、紧邻中文/全角字符的未转义双引号转义为 \\"。

        背景：LLM 常把需求文案里的中文引号直接写成 ASCII 双引号，
        例如 "公开房间按钮文案为"发送"，可点击" —— 其中 "发送" 的两个引号
        会让 JSON 解析失败（Expecting ',' delimiter）。

        安全边界：结构性的 JSON 引号（属性名/字符串定界符）两侧必然是
        ASCII 结构符（: { , [ } ] 或空白），绝不会紧邻 CJK/全角字符；
        而"字符串内部的中文引号"两侧必然紧邻 CJK/全角字符。据此判断，
        可安全地只转义后者，不影响合法 JSON。
        """
        result: list[str] = []
        in_string = False
        escaped = False
        i = 0
        n = len(text)

        # 字符串内部裸引号的两类判定：
        #   a) 结束定界符 —— 其后必然紧跟 ASCII 结构边界；否则
        #   b) LLM 用作中文引号/引用的内层引号 —— 其后是正文内容。
        _BOUNDARY = ',]}\t\n\r :'

        while i < n:
            ch = text[i]

            if escaped:
                result.append(ch)
                escaped = False
                i += 1
                continue

            if ch == '\\' and in_string:
                result.append(ch)
                escaped = True
                i += 1
                continue

            if ch == '"':
                if in_string:
                    nxt = text[i + 1] if i + 1 < n else ''
                    if nxt in _BOUNDARY:
                        # 结束定界符（后续是结构边界）→ 关闭字符串
                        in_string = False
                        result.append(ch)
                        i += 1
                        continue
                    # 字符串内部、后继非结构边界的裸引号 = 内层中文引号 → 转义。
                    # 合法 JSON 的结束定界符永远后随结构边界，故不误伤；
                    # 同时覆盖中包中、中包中英混合（如 "xxx金币"）两种形态。
                    result.append('\\"')
                    i += 1
                    continue
                # 结构性开定界符
                in_string = True
                result.append(ch)
                i += 1
                continue

            result.append(ch)
            i += 1

        return ''.join(result)

    @staticmethod
    def _strip_json_comments(text: str) -> str:
        """移除 JSON 文本中的 // 注释，但不破坏字符串内部的 //（如 URL）。"""
        result: list[str] = []
        i = 0
        in_string = False
        escaped = False

        while i < len(text):
            ch = text[i]

            if escaped:
                result.append(ch)
                escaped = False
                i += 1
                continue

            if ch == '\\' and in_string:
                result.append(ch)
                escaped = True
                i += 1
                continue

            if ch == '"':
                in_string = not in_string
                result.append(ch)
                i += 1
                continue

            if not in_string and ch == '/' and i + 1 < len(text) and text[i + 1] == '/':
                # 跳过到行尾
                while i < len(text) and text[i] not in '\n\r':
                    i += 1
                continue

            result.append(ch)
            i += 1

        return ''.join(result)

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
    def _looks_like_document(obj) -> bool:
        """判断解析结果是否像"整份文档"而非"纯标量内层片段"。

        根文档是对象且含至少一个数组值（如 {'actors':[...], 'features':[...]}）。
        而 LLM 整份 JSON 损坏时，解析器常捡起某个内层对象片段
        （如单个 relation：{'id','type','condition_id',... 全是标量}）——
        那种没有数组值的对象绝不是完整输出，必须拒绝。
        """
        if isinstance(obj, dict):
            return any(
                isinstance(v, list) for v in obj.values()
            )
        if isinstance(obj, list):
            return True
        return False

    @staticmethod
    def _is_fragment_of(data, schema) -> bool:
        """判断 data 是否只是整份输出文档的一个内层片段。

        依据 schema 根 properties 键在 data 顶层出现的数量判定：
        根文档正常情况下会包含多数 required 顶层键（如 actors/entities/...）；
        而 LLM 整份 JSON 损坏后捡到的内层对象片段（如单个 relation 对象），
        顶层键与根 properties 几乎不重合。若一个都不重合，视为片段。
        """
        props = (
            schema.get("properties")
            if isinstance(schema, dict)
            else None
        )
        if not isinstance(props, dict) or not props:
            return False
        if not isinstance(data, dict):
            return False
        present = sum(
            1 for k in props if k in data
        )
        return present == 0

    @staticmethod
    def _parse_json(text):

        text = text.strip()

        def _accept(parsed):
            if SkillEngine._looks_like_document(parsed):
                return parsed
            return None

        # 2. ```json —— 可能有多个 code block（LLM 先贴示例再贴正式输出），
        #    取能解析且长度最长的那个，最可能是完整输出而非内嵌示例。
        blocks = re.findall(
            r"```json\s*(.*?)\s*```",
            text,
            re.DOTALL | re.IGNORECASE
        )
        best = None
        best_len = -1
        for block in blocks:
            try:
                parsed = _accept(
                    SkillEngine._try_parse_json(block)
                )
            except (json.JSONDecodeError, ValueError):
                continue
            if parsed is not None and len(block) > best_len:
                best = parsed
                best_len = len(block)
        if best is not None:
            return best

        # 3. ``` 同理
        blocks = re.findall(
            r"```\s*(.*?)\s*```",
            text,
            re.DOTALL
        )
        best = None
        best_len = -1
        for block in blocks:
            try:
                parsed = _accept(
                    SkillEngine._try_parse_json(block)
                )
            except (json.JSONDecodeError, ValueError):
                continue
            if parsed is not None and len(block) > best_len:
                best = parsed
                best_len = len(block)
        if best is not None:
            return best

        # 1. Direct JSON
        try:
            parsed = _accept(
                SkillEngine._try_parse_json(text)
            )
            if parsed is not None:
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

        # 4. 从所有候选 JSON 中选"最完整且像文档"的一个：
        #    记录每个能解析且像文档的候选长度，取最长者。
        #    （LLM 常在解释文字里贴示例 JSON，首个可解析片段可能是示例
        #     而非真正的根对象；但必须过滤掉"纯标量片段"，避免整份文档
        #     损坏时误把内层 relation/entity 当作完整输出。）
        positions = [i for i, c in enumerate(text) if c == '{']
        best = None
        best_len = -1
        for start in positions:
            for end in range(len(text) - 1, start, -1):
                if text[end] != '}':
                    continue
                candidate = text[start:end + 1]
                try:
                    parsed = _accept(
                        SkillEngine._try_parse_json(candidate)
                    )
                except (json.JSONDecodeError, ValueError):
                    continue
                if parsed is not None and len(candidate) > best_len:
                    best = parsed
                    best_len = len(candidate)
                # 已到最外层：同一 start 的更大 end 只会更大，直接换下一个 start
                break
        if best is not None:
            return best

        raise ValueError(
            "无法从 LLM 输出中提取完整 JSON"
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
        error,
        data=None,
    ):

        extra = SkillEngine._minitems_retry_directive(error, data)

        return f"""
你上一轮输出虽然是合法 JSON，
但是没有通过当前 Skill 的 JSON Schema。

Schema 错误：

{error}
{extra}
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
10. 如果错误是 "should be non-empty" 或 "minItems"，表示数组不能为空/数量不足，必须至少生成要求数量的元素。
11. test_points 不能为空：必须从 requirement_analysis 中的 rules、constraints、facts 生成至少 1 个测试点。
12. test_cases 不能为空：必须从 test_points 生成至少 1 个测试用例。

只输出最终 JSON。
"""

    _MODEL_MINITEMS_ARRAYS = {
        "actors": 1, "entities": 3, "states": 2, "conditions": 2,
        "actions": 3, "outcomes": 2, "relations": 3,
        "test_points": 1,
    }

    @staticmethod
    def _minitems_retry_directive(error: str, data) -> str:
        """当错误是某个顶层模型数组 minItems 不足时，生成针对性的补足指令。

        这是本工程稳定性的关键兜底：GLM 等模型在重试时经常仍然少列元素
        （如 actions 只有 2 个、缺 1 个）。泛化的"请修复"提示无效，
        必须明确点出"哪个数组差几个，从哪些输入 Fact 里补"。
        """
        if not error or "minItems" not in error:
            return ""

        m = re.search(
            r"字段路径：(?:root\.)?([A-Za-z_]+)", error
        )
        field = m.group(1) if m else None

        if field not in SkillEngine._MODEL_MINITEMS_ARRAYS:
            return ""

        need = SkillEngine._MODEL_MINITEMS_ARRAYS[field]
        cur = 0
        if isinstance(data, dict):
            val = data.get(field)
            if isinstance(val, (list, dict, str)):
                cur = len(val)

        if cur >= need:
            return ""

        return (
            f"\n⚠ 关键提示：字段 root.{field} 当前只有 {cur} 个元素，"
            f"但 Schema 要求至少 {need} 个。\n"
            f"你必须把它补齐到 {need} 个（只多不少）。\n"
            f"做法：重新逐一扫描输入中的所有 Fact，把符合该类的内容"
            f"完整列出，不得只列一部分；RULE / ACTION 等类型的 Fact 一条往往"
            f"能拆出多个这类元素，禁止把多个合并成一个去凑数。\n"
            f"严禁编造输入中不存在的内容；只能从输入 Fact 的 content 中提炼。"
        )


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
            SkillEngine._normalize_design_enums(data)

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

        # ===============================
        # Requirement Fact
        # ===============================

        if schema_path and schema_path.endswith(
                "requirement_fact.schema.json"
        ):
            SkillEngine._fix_fact_ids(data)
            SkillEngine._normalize_fact_types(data)

        return data

    @staticmethod
    def _fix_tc_ids(data: dict) -> None:
        """修复 LLM 生成的 TC ID，使其匹配 ^TC-[A-Z0-9]+-[0-9]{3,}$。"""
        import re

        pattern = re.compile(r"^TC-[A-Z0-9]+-[0-9]{3,}$")

        def _fix_id(tc_id: str, index: int) -> str:
            if pattern.match(tc_id):
                return tc_id

            # 提取字母部分和数字部分
            letters = re.findall(r"[A-Z]", tc_id.upper().replace("-", "").replace("/", "").replace("_", ""))
            letters_str = "".join(letters) if letters else "TC"
            if letters_str.startswith("TC"):
                prefix = letters_str
            else:
                prefix = "TC" + letters_str
            # 限制长度，避免过长的前缀
            prefix = prefix[:10]

            new_id = f"TC-{prefix}-{index:03d}"
            return new_id

        cases = data.get("test_cases", [])
        for i, tc in enumerate(cases, start=1):
            if isinstance(tc, dict) and "id" in tc:
                if not pattern.match(tc["id"]):
                    tc["id"] = _fix_id(tc["id"], i)

    @staticmethod
    def _fix_fact_ids(data) -> None:
        """为 LLM 遗漏 id 的 Fact 自动补全缺失 id。"""
        import re

        facts = data.get("facts", []) if isinstance(data, dict) else []
        pattern = re.compile(r"^F[0-9]{3,}$")
        # 收集已存在的合法 id
        existing = {
            f["id"] for f in facts
            if isinstance(f, dict)
            and f.get("id")
            and pattern.match(str(f["id"]))
        }
        next_num = 1
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            if fact.get("id"):
                continue
            # 找一个未占用的编号
            while f"F{next_num:03d}" in existing:
                next_num += 1
            fact["id"] = f"F{next_num:03d}"
            existing.add(fact["id"])
            next_num += 1

    # 事实类型归一化：把 LLM 发明的非白名单类型映射回合法枚举
    _FACT_TYPE_ALIASES = {
        "NOTIFICATION": "OBJECT",
        "MESSAGE": "OBJECT",
        "PROMPT": "OBJECT",
        "BANNER": "OBJECT",
        "BROADCAST": "OBJECT",
        "REMINDER": "OBJECT",
        "TOAST": "EXCEPTION",
        "EVENT": "ACTION",
        "BUTTON": "OBJECT",
        "LOOP": "ACTION",
        "BEHAVIOR": "ACTION",
        "FUNCTION": "ACTION",
        "MECHANISM": "RULE",
        "WORKFLOW": "RELATION",
        "DEPENDENCY": "RELATION",
        "CONSTRAINT": "LIMIT",
        "REQUIREMENT": "CONFIGURATION",
        "INFO": "DATA",
        "METRIC": "DATA",
        "SCENARIO": "RULE",
    }
    _FACT_TYPES = {
        "ACTOR", "OBJECT", "ACTION", "RULE", "CONDITION", "ATTRIBUTE",
        "STATE", "TRANSITION", "TIME", "QUANTITY", "LIMIT", "PERMISSION",
        "DATA", "RELATION", "EXCEPTION", "CONFIGURATION",
    }

    @staticmethod
    def _normalize_fact_types(data) -> None:
        facts = (
            data.get("facts", [])
            if isinstance(data, dict)
            else []
        )
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            raw = fact.get("type")
            if not isinstance(raw, str):
                continue
            key = raw.strip().upper()
            if key in SkillEngine._FACT_TYPES:
                if key != raw:
                    fact["type"] = key
                continue
            mapped = SkillEngine._FACT_TYPE_ALIASES.get(key)
            if mapped is None:
                # 无法识别时按字面归类兜底，绝不因为一个字段整体崩掉
                mapped = SkillEngine._classify_fact_type(fact.get("content", ""))
            fact["type"] = mapped
            print(f"⚠ fact type 归一化: '{raw}' -> '{mapped}' (content: {fact.get('content','')[:30]})")

    @staticmethod
    def _classify_fact_type(content: str) -> str:
        if not content:
            return "OBJECT"
        text = content.lower()
        if content.startswith(("点击", "跳转", "打开发送", "关闭", "自动弹出", "发送")):
            return "ACTION"
        if any(k in text for k in ("元", "币", "$", "人数", "档位", "金额", "个", "次")):
            return "QUANTITY"
        if any(k in text for k in ("秒", "分钟", "mins", "s后")):
            return "TIME"
        if any(k in text for k in ("若", "则", "当", "仅", "≥", "<", ">=", "<=")):
            return "CONDITION"
        if any(k in text for k in ("白名单", "黑名单", "不可", "权限")):
            return "PERMISSION"
        if any(k in text for k in ("上限", "不能超过", "不设限", "最少")):
            return "LIMIT"
        if any(k in text for k in ("toast", "提示", "失败", "不足", "异常")):
            return "EXCEPTION"
        return "OBJECT"

    # test_design 枚举归一化：test_method / test_type / test_scenario 等
    _DESIGN_ENUM_MAP = {
        # test_method 合法：equivalence_partitioning/boundary_value_analysis/decision_table/state_transition/error_guessing/scenario_testing/workflow_testing/data_consistency/data_validation/permission_testing/time_boundary
        "equivalence": "equivalence_partitioning",
        "equivalence_class": "equivalence_partitioning",
        "boundary": "boundary_value_analysis",
        "boundary_value": "boundary_value_analysis",
        "decision": "decision_table",
        "error": "error_guessing",
        "scenario": "scenario_testing",
        "workflow": "workflow_testing",
        "data": "data_validation",
        "permission": "permission_testing",
        "permission_testing": "permission_testing",
        "timing": "time_boundary",
        "time": "time_boundary",
        # conditionDimension test_type 合法：equivalence_partitioning/boundary_value/permission/enumeration/positive_negative
        "boundary_value_analysis": "boundary_value",
        "positive": "positive_negative",
        "negative": "positive_negative",
        # risk_type 合法：data_integrity/state_consistency/permission/timing/ui_ux/business_logic
        "ui": "ui_ux",
        "business": "business_logic",
    }
    # conditionDimension.test_type 及其字段路径上下文（区别于 testPoint.test_method）
    _DESIGN_ENUM_FIELD_CONTEXT = {
        "test_type": "condition",
        "test_method": "testpoint",
    }
    # scenario_type 合法：main_flow/exception_flow/boundary_flow/state_transition/permission。
    # 不能复用 _DESIGN_ENUM_MAP：那里 "permission"->"permission_testing" 只对 test_method 合法，
    # 若套用到 scenario_type 会把合法值改坏导致 Schema 必败（历史 bug）。
    _DESIGN_SCENARIO_TYPE_MAP = {
        "main_flow": "main_flow",
        "main": "main_flow",
        "exception_flow": "exception_flow",
        "exception": "exception_flow",
        "boundary_flow": "boundary_flow",
        "boundary": "boundary_flow",
        "state_transition": "state_transition",
        "state": "state_transition",
        "permission": "permission",
        "permission_testing": "permission",
    }
    # risk_type 合法：data_integrity/state_consistency/permission/timing/ui_ux/business_logic。
    # 同理不复用通用表，否则 "permission"->"permission_testing"、"timing"->"time_boundary" 会改坏。
    _DESIGN_RISK_TYPE_MAP = {
        "data_integrity": "data_integrity",
        "state_consistency": "state_consistency",
        "permission": "permission",
        "permission_testing": "permission",
        "timing": "timing",
        "time_boundary": "timing",
        "ui_ux": "ui_ux",
        "ui": "ui_ux",
        "business_logic": "business_logic",
        "business": "business_logic",
    }

    # conditionDimension.test_type 合法枚举：equivalence_partitioning/boundary_value/permission/enumeration/positive_negative
    _DESIGN_TEST_TYPE_VALID = {
        "equivalence_partitioning", "boundary_value", "permission",
        "enumeration", "positive_negative",
    }
    # testPoint.test_method 合法枚举（别名已通过 _DESIGN_ENUM_MAP 收敛）
    _DESIGN_TEST_METHOD_VALID = {
        "equivalence_partitioning", "boundary_value_analysis", "decision_table",
        "state_transition", "error_guessing", "scenario_testing",
        "workflow_testing", "data_consistency", "data_validation",
        "permission_testing", "time_boundary",
    }

    _DESIGN_ENUM_FIELDS = {"test_method", "test_type", "risk_type", "scenario_type"}

    @staticmethod
    def _normalize_design_enums(data, _depth=0):
        if _depth > 60:
            return data
        if isinstance(data, dict):
            for key, value in list(data.items()):
                if key in SkillEngine._DESIGN_ENUM_FIELDS:
                    data[key] = SkillEngine._coerce_enum_field(key, value)
                SkillEngine._normalize_design_enums(value, _depth + 1)
        elif isinstance(data, list):
            for item in data:
                SkillEngine._normalize_design_enums(item, _depth + 1)
        return data

    @staticmethod
    def _coerce_enum_field(field, value):
        valid_set = (
            SkillEngine._DESIGN_TEST_METHOD_VALID
            if field == "test_method"
            else (
                SkillEngine._DESIGN_TEST_TYPE_VALID
                if field == "test_type"
                else None
            )
        )
        # scenario_type / risk_type 使用字段专属映射，绝不套用 test_method 的通用别名表
        field_map = None
        if field == "scenario_type":
            field_map = SkillEngine._DESIGN_SCENARIO_TYPE_MAP
        elif field == "risk_type":
            field_map = SkillEngine._DESIGN_RISK_TYPE_MAP

        if isinstance(value, str):
            norm = value.strip().lower()
            if field_map is not None:
                mapped = field_map.get(norm)
                if mapped and mapped != norm:
                    print(f"⚠ design enum 归一化({field}): '{value}' -> '{mapped}'")
                return mapped if (mapped is not None) else value
            mapped = SkillEngine._DESIGN_ENUM_MAP.get(norm)
            # 若已映射后仍不在该字段合法集，且是 test_type，收敛到 permission
            if valid_set is not None and mapped and mapped not in valid_set:
                fallback = (
                    "permission"
                    if field == "test_type" and "permission" in str(value).lower()
                    else "equivalence_partitioning"
                )
                print(f"⚠ design enum 归一化({field}): '{value}' -> '{fallback}'")
                return fallback
            if mapped and mapped != norm:
                print(f"⚠ design enum 归一化({field}): '{value}' -> '{mapped}'")
            return mapped if (mapped is not None) else value
        if isinstance(value, list):
            out = []
            for it in value:
                if isinstance(it, str):
                    if field_map is not None:
                        mapped = field_map.get(it.strip().lower())
                        out.append(mapped if (mapped is not None) else it)
                        continue
                    mapped = SkillEngine._DESIGN_ENUM_MAP.get(it.strip().lower())
                    if mapped is None:
                        # test_method 里未知值：就近给 error_guessing（通用兜底）
                        out.append("error_guessing" if field == "test_method" else it)
                    else:
                        out.append(mapped)
                else:
                    out.append(it)
            return out
        return value

    @staticmethod
    def _normalize_dimensions(data, _depth=0):

        if _depth > 60:
            return data

        if isinstance(data, dict):
            coverage_keys = [
                "entity_coverage",
                "state_coverage",
                "condition_coverage",
                "action_coverage",
                "flow_coverage",
                "risk_coverage",
                "fact_ids",
            ]
            flattened = {
                k: data.pop(k)
                for k in coverage_keys
                if k in data
            }
            if flattened:
                data["coverage"] = flattened

        fields = [
            "data_dimensions",
            "time_dimensions",
            "source_dimensions",
            "state_dimensions",
            "conditions",
            "coverage_targets",
            "expected_behavior",
            "requirement_refs",
            "test_methods",
            "test_method"
        ]

        if isinstance(data, dict):

            # 只递归"原始键"，绝不递归刚生成的 coverage 对象：
            # 否则其内部 entity_coverage 等（本身就是 coverage_keys）会被
            # 不断 pop 再重新包裹，递归无限增长到深度上限（60 层 coverage）。
            keys = [
                k for k in data.keys()
                if k != "coverage"
            ]

            for key in keys:

                value = data[key]

                if key in fields:

                    if isinstance(value, dict):
                        data[key] = [value]

                    elif isinstance(value, str):
                        data[key] = [value]

                else:

                    SkillEngine._normalize_dimensions(
                        value,
                        _depth + 1
                    )


        elif isinstance(data, list):

            for item in data:
                SkillEngine._normalize_dimensions(
                    item,
                    _depth + 1
                )

        return data

    # ======================================================
    # Final salvage for schema: remove empty arrays violating minItems
    # ======================================================

    @staticmethod
    def _salvage_for_schema(data: dict, schema: dict) -> dict|None:
        """Try to salvage schema failure by removing empty arrays and filling required fields."""
        from copy import deepcopy
        repaired = deepcopy(data)

        # 1) Remove all empty arrays from root level (minItems 2/3 → still require at least one after repair)
        changed = False
        for key, val in list(repaired.items()):
            if isinstance(val, list) and len(val) == 0:
                # If schema says it's required and minItems >0, only remove if after
                # repair all other arrays still okay → otherwise it fails anyway
                print(f"⚠ 兜底修复：移除根级空数组 {key}")
                del repaired[key]
                changed = True

        # 2) Fill missing derivation_basis for derived=true elements
        SkillEngine._fill_derivation_basis(None, repaired)

        # 3) 顶层模型数组数量不足（minItems 差一点，如 actions=2<3）兜底：
        #    按 LLM 实际产出的真实数量放宽该数组的 minItems，再做一次校验。
        #    这保证 LLM 偶发低质量输出时管线"能跑完"（产出真实元素），
        #    而不是整条链路崩溃丢光；绝不编造元素来凑数。
        relaxed_schema = None
        for key, spec in (schema.get("properties") or {}).items():
            if not isinstance(spec, dict):
                continue
            mini = spec.get("minItems")
            if not isinstance(mini, int):
                continue
            if key in repaired and isinstance(repaired[key], list):
                cur = len(repaired[key])
                if 0 < cur < mini:
                    relaxed_schema = relaxed_schema or deepcopy(schema)
                    relaxed_schema["properties"][key]["minItems"] = cur
                    print(
                        f"⚠ 兜底：{key} 数量不足(minItems 要求 {mini})，"
                        f"已按实际数量 {cur} 放宽校验（保留真实元素，不编造）"
                    )

        candidate = relaxed_schema if relaxed_schema is not None else schema

        # Re-check schema validity after repairs
        try:
            validate(instance=repaired, schema=candidate)
            return repaired
        except ValidationError:
            return None

    @staticmethod
    def _fill_derivation_basis(parent, data):
        """Recursively fill missing derivation_basis for all elements where derived=true."""
        if not isinstance(data, dict):
            if isinstance(data, list):
                for idx, item in enumerate(data):
                    SkillEngine._fill_derivation_basis(data, item)
            return
        if data.get("derived") is True and not data.get("derivation_basis"):
            data["derivation_basis"] = "基于业务分析与测试推理推断"
            print(f"⚠ 兜底修复：为 derived=true 补全 derivation_basis")
        for key, val in data.items():
            SkillEngine._fill_derivation_basis(data, val)

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
            "entities",
            "states",
            "conditions",
            "actions",
            "outcomes",
            "relations",
            "source_facts",
            "attributes"
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

        SkillEngine._normalize_business_model(data)

        return data

    # ======================================================
    # Business Model 专项清洗：source_facts 规范化 + derived 一致性
    # ======================================================

    _FACT_ID_PATTERN = re.compile(r"^F[0-9]{3,}$")
    _MODEL_ENTITY_KEYS = (
        "actors", "entities", "states", "conditions",
        "actions", "outcomes", "relations",
    )
    _DERIVED_OBJ_HINT_KEYS = (
        "entity_id", "related_entity", "related_state", "actor_id",
        "target_entity", "state_change", "condition_id", "action_id",
        "outcome_id", "from_state_id", "to_state_id",
        "source_entity", "target_entity", "type",
    )

    @staticmethod
    def _expand_fact_ref(value: str):
        """展开 source_facts 里的范围/串号写法：
        'F010-F017' -> [F010..F017];  'F010018' 按 3 位分片;  'F010' 原样。"""
        v = str(value).strip()
        m = re.match(r"^F(\d+)-F?(\d+)$", v)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 0 <= a <= b and b - a <= 200:
                return [f"F{x:03d}" for x in range(a, b + 1)]
        if SkillEngine._FACT_ID_PATTERN.match(v):
            return [v]
        # 串号如 F010018 -> F010 + F018
        m2 = re.match(r"^F(\d{3,})(\d{3,})$", v)
        if m2:
            head = m2.group(1)
            tail = m2.group(2).lstrip("0")
            parts = [head]
            if tail:
                parts.append(tail)
            return [f"F{p:0>{len(p)}}" if len(p) <= 4 else f"F{p}" for p in parts]
        return []  # 无法识别 → 丢弃，避免 schema pattern 卡死

    @staticmethod
    def _clean_source_facts(value):
        if isinstance(value, str):
            return SkillEngine._expand_fact_ref(value)
        if isinstance(value, list):
            out = []
            for it in value:
                out.extend(SkillEngine._expand_fact_ref(it) if not isinstance(it, int) else [])
            return out
        return []

    @staticmethod
    def _normalize_business_model(data):
        if not isinstance(data, dict):
            return
        for key in SkillEngine._MODEL_ENTITY_KEYS:
            items = data.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                # 1) source_facts 规范化
                if "source_facts" in item:
                    item["source_facts"] = SkillEngine._clean_source_facts(
                        item["source_facts"]
                    )
                # 2) derived / derivation_basis 一致性
                derived = item.get("derived")
                if derived is True:
                    # derived=true 必须有 derivation_basis 且可以没有 source_facts
                    if not item.get("derivation_basis"):
                        item["derivation_basis"] = "基于业务分析与测试推理推断"
                    has_fact = bool(item.get("source_facts"))
                    if not has_fact:
                        item["derived"] = False
                        item["source_facts"] = []
                elif derived is False:
                    # derived=false 必须有 source_facts
                    if not item.get("source_facts"):
                        item["source_facts"] = []
                else:
                    # 缺省：有 source_facts 视为事实，否则视为推导
                    has_fact = bool(item.get("source_facts"))
                    item["derived"] = False if has_fact else True
                    if not has_fact:
                        item["derivation_basis"] = item.get(
                            "derivation_basis"
                        ) or "基于业务分析与测试推理推断"