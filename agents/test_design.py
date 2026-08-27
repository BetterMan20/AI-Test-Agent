import json

from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class TestDesign:

    def run(self, analysis):

        print("========== Test Design ==========")

        # ==================================================
        # Step 1: Normalize Requirement Analysis
        # ==================================================

        normalized_analysis = self._normalize_analysis(
            analysis
        )

        print(
            "Test Design Normalize 后输入长度：",
            len(
                json.dumps(
                    normalized_analysis,
                    ensure_ascii=False
                )
            )
        )

        # ==================================================
        # Step 2: Test Design
        # ==================================================

        result = SkillEngine.run(
            skill_path=SKILLS["design"],
            user_input=normalized_analysis,
            schema_path="schema/test_design.schema.json",
            output_mode="json"
        )

        print(
            "Test Design 输出完成"
        )

        return result

    # ======================================================
    # Lightweight Normalize
    # ======================================================

    @staticmethod
    def _normalize_analysis(analysis):
        """
        对 Requirement Analysis 做轻量标准化。

        目的：
        1. 保证输入类型稳定
        2. 如果上游返回 JSON 字符串，转换为 dict
        3. 清理 None / 空字符串
        4. 保留业务事实
        5. 不进行任何业务推理
        6. 不修改业务规则
        """

        # --------------------------------------------------
        # 1. JSON String -> dict
        # --------------------------------------------------

        if isinstance(analysis, str):

            text = analysis.strip()

            if not text:
                raise ValueError(
                    "Requirement Analysis 为空"
                )

            try:

                analysis = json.loads(text)

            except json.JSONDecodeError as e:

                raise ValueError(
                    "Requirement Analysis 不是合法 JSON"
                ) from e

        # --------------------------------------------------
        # 2. 必须是 Object
        # --------------------------------------------------

        if not isinstance(analysis, dict):

            raise TypeError(
                "Requirement Analysis 必须是 JSON Object"
            )

        # --------------------------------------------------
        # 3. Recursive normalize
        # --------------------------------------------------

        normalized = TestDesign._clean_value(
            analysis
        )

        # --------------------------------------------------
        # 4. 基础结构保护
        # --------------------------------------------------

        if not isinstance(normalized, dict):

            raise ValueError(
                "Normalize 后 Requirement Analysis 必须是 Object"
            )

        return normalized

    # ======================================================
    # Recursive Cleaner
    # ======================================================

    @staticmethod
    def _clean_value(value):

        # --------------------------------------------------
        # dict
        # --------------------------------------------------

        if isinstance(value, dict):

            result = {}

            for key, item in value.items():

                # 不修改 key
                normalized_value = (
                    TestDesign._clean_value(item)
                )

                # 只清理 None
                if normalized_value is None:
                    continue

                # 清理空字符串
                if (
                    isinstance(
                        normalized_value,
                        str
                    )
                    and not normalized_value.strip()
                ):
                    continue

                result[key] = normalized_value

            return result

        # --------------------------------------------------
        # list
        # --------------------------------------------------

        if isinstance(value, list):

            result = []

            for item in value:

                normalized_item = (
                    TestDesign._clean_value(item)
                )

                if normalized_item is None:
                    continue

                if (
                    isinstance(
                        normalized_item,
                        str
                    )
                    and not normalized_item.strip()
                ):
                    continue

                result.append(
                    normalized_item
                )

            return result

        # --------------------------------------------------
        # scalar
        # --------------------------------------------------

        return value
