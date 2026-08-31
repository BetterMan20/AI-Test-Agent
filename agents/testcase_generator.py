import json

from configs.skills import SKILLS
from utils.skill_engine import SkillEngine
from agents.test_design import TestDesign


class TestCaseGenerator:

    def run(self, design):

        print("========== Test Case Generator ==========")

        all_cases = []

        module_groups = self._group_designs_by_module(design)

        for module in TestDesign.MODULES:

            letter = module["letter"]
            name = module["name"]

            designs = module_groups.get(letter, [])

            if not designs:
                print(
                    f"\n--- Module {letter}: {name} ---"
                    f" (无设计，跳过)"
                )
                continue

            print(
                f"\n--- Module {letter}: {name} ---"
                f" ({len(designs)} designs)"
            )

            try:

                cases = self._run_module_batch(
                    designs, module
                )

                all_cases.extend(cases)

                print(
                    f"  Generated {len(cases)} cases"
                )

            except Exception as e:

                print(
                    f"  Module {letter} failed: {e}"
                )

        result = self._merge_results(all_cases)

        print(
            f"\nTest Case Generator 完成，"
            f"共 {self._count_cases(result)} 条用例"
        )

        return result

    # ======================================================
    # Group Designs by Module
    # ======================================================

    @staticmethod
    def _group_designs_by_module(design):

        groups = {}

        if not isinstance(design, dict):
            return groups

        for module in design.get("modules", []):
            if not isinstance(module, dict):
                continue

            for td in module.get("test_designs", []):
                if not isinstance(td, dict):
                    continue

                obj = td.get("test_object", "")
                letter = TestCaseGenerator._extract_module_letter(obj)

                if letter not in groups:
                    groups[letter] = []

                groups[letter].append(td)

        return groups

    @staticmethod
    def _extract_module_letter(test_object):

        if not isinstance(test_object, str):
            return "X"

        if len(test_object) >= 2 and test_object[1] == "-":
            return test_object[0].upper()

        if len(test_object) >= 3 and test_object[1] == " " and test_object[2] == "-":
            return test_object[0].upper()

        for letter in "ABCDEFGHIJK":
            if test_object.startswith(letter):
                return letter

        return "X"

    # ======================================================
    # Run Module Batch
    # ======================================================

    @staticmethod
    def _run_module_batch(designs, module):

        enhanced_input = (
            TestCaseGenerator._build_module_input(
                designs, module
            )
        )

        print(
            "  增强输入长度：",
            len(
                json.dumps(
                    enhanced_input,
                    ensure_ascii=False
                )
            )
        )

        result = SkillEngine.run(
            skill_path=SKILLS["generation"],
            user_input=enhanced_input,
            schema_path="schema/test_case.schema.json",
            output_mode="json"
        )

        cases = []

        for m in result.get("modules", []):
            if isinstance(m, dict):
                tcs = m.get("testcases", [])
                if isinstance(tcs, list):
                    cases.extend(tcs)

        for tc in cases:
            if isinstance(tc, dict):
                if "case_id" not in tc or not tc["case_id"]:
                    continue
                if "category" not in tc or not tc["category"]:
                    tc["category"] = module["name"]

        return cases

    # ======================================================
    # Build Module Input
    # ======================================================

    @staticmethod
    def _build_module_input(designs, module):

        scenarios_text = "\n".join(
            f"  {i+1}. {s}"
            for i, s in enumerate(module["scenarios"])
        )

        min_cases = module["min_designs"]

        enhanced = {
            "instruction": (
                f"你正在为「{module['name']}」模块"
                f"生成测试用例。\n\n"
                f"必须覆盖以下 {len(module['scenarios'])} 个测试场景，"
                f"每个场景至少1条用例：\n"
                f"{scenarios_text}\n\n"
                f"共有 {len(designs)} 个 Test Design。"
                f"最少需要生成 {min_cases} 条测试用例。\n\n"
                "case_id 格式：TC-{letter}{序号:03d}，"
                f"例如 TC-{module['letter']}001, TC-{module['letter']}002\n"
                f"category 必须为：{module['name']}\n\n"
                "步骤必须具体可执行，期望结果必须具体可验证，"
                "多个验证点用\\n分隔。\n"
                "复杂操作必须拆分为多个独立步骤。\n\n"
                "只输出合法 JSON。"
                "JSON 必须以 { 开头，以 } 结尾。"
                "不输出 Markdown、解释、分析过程。"
            ),
            "min_test_cases": min_cases,
            "module_letter": module["letter"],
            "module_name": module["name"],
            "scenarios": module["scenarios"],
            "test_design": {
                "schema_version": "1.0",
                "project": "svip体验卡管理系统测试设计",
                "modules": [
                    {
                        "name": module["name"],
                        "test_designs": designs
                    }
                ]
            }
        }

        return enhanced

    # ======================================================
    # Merge Results
    # ======================================================

    @staticmethod
    def _merge_results(testcases):

        seen_ids = set()
        unique = []
        for tc in testcases:
            if isinstance(tc, dict):
                cid = tc.get("case_id", "")
                title = tc.get("title", "")
                key = cid if cid else title
                if key and key not in seen_ids:
                    seen_ids.add(key)
                    unique.append(tc)

        return {
            "project": "svip体验卡管理系统测试设计",
            "modules": [
                {
                    "name": "svip体验卡后台管理",
                    "testcases": unique
                }
            ]
        }

    # ======================================================
    # Count Cases
    # ======================================================

    @staticmethod
    def _count_cases(result):

        if not isinstance(result, dict):
            return 0

        count = 0
        for module in result.get("modules", []):
            if isinstance(module, dict):
                tcs = module.get("testcases", [])
                if isinstance(tcs, list):
                    count += len(tcs)
        return count
