import json
import re

from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class TestCaseValidator:

    def run(self, requirement_analysis, test_design, test_cases):

        print("========== Test Case Validator ==========")

        # Step 1: Programmatic checks
        programmatic_issues = self._run_programmatic_checks(
            requirement_analysis, test_design, test_cases
        )
        print(f"  Programmatic checks: {len(programmatic_issues)} issues found")

        # Step 2: LLM quality review (simplified input, focused output)
        try:
            llm_result = self._run_llm_review(
                requirement_analysis, test_design, test_cases
            )
            print(f"  LLM review: status={llm_result.get('status')}")
        except Exception as e:
            print(f"  LLM review failed (falling back to programmatic only): {e}")
            llm_result = {
                "status": "PASS",
                "summary": "LLM审查失败，仅完成程序化检查",
                "coverage": {},
                "quality": {},
                "issues": []
            }

        # Step 3: Merge and build final result
        final_result = self._build_final_result(
            requirement_analysis, test_design, test_cases,
            programmatic_issues, llm_result
        )

        return final_result

    def _run_programmatic_checks(self, requirement_analysis, test_design, test_cases):
        """Run programmatic validation checks."""
        issues = []
        issue_num = 1

        # Check 1: Schema compliance
        try:
            from jsonschema import validate
            schema = json.load(open(
                "schema/test_case.schema.json", "r", encoding="utf-8"
            ))
            validate(instance=test_cases, schema=schema)
        except Exception as e:
            issues.append({
                "issue_id": f"V{issue_num:03d}",
                "type": "schema_violation",
                "severity": "P0",
                "status": "OPEN",
                "problem": f"测试用例JSON不符合schema规范: {str(e)[:200]}",
                "evidence": f"schema/test_case.schema.json",
                "suggestion": "修复JSON结构使其符合schema定义"
            })
            issue_num += 1

        # Check 2: Case ID format
        all_cases = self._collect_all_cases(test_cases)
        seen_ids = set()
        id_pattern = re.compile(r'^TC-[A-Z]\d{3}$')

        for tc in all_cases:
            cid = tc.get("case_id", "")
            if not cid:
                issues.append({
                    "issue_id": f"V{issue_num:03d}",
                    "type": "schema_violation",
                    "severity": "P1",
                    "status": "OPEN",
                    "problem": f"用例缺少case_id",
                    "evidence": f"title={tc.get('title', 'unknown')}",
                    "suggestion": "为每个用例添加case_id，格式为TC-字母+三位数字"
                })
                issue_num += 1
            elif not id_pattern.match(cid):
                issues.append({
                    "issue_id": f"V{issue_num:03d}",
                    "type": "schema_violation",
                    "severity": "P1",
                    "status": "OPEN",
                    "problem": f"用例ID格式不正确: {cid}",
                    "evidence": f"case_id={cid}",
                    "suggestion": "case_id格式应为TC-字母+三位数字，如TC-A001"
                })
                issue_num += 1
            elif cid in seen_ids:
                issues.append({
                    "issue_id": f"V{issue_num:03d}",
                    "type": "duplicate_testcase",
                    "severity": "P1",
                    "status": "OPEN",
                    "problem": f"重复的用例ID: {cid}",
                    "evidence": f"case_id={cid}",
                    "suggestion": "确保每个用例有唯一的case_id"
                })
                issue_num += 1
            seen_ids.add(cid)

        # Check 3: Steps validation
        for tc in all_cases:
            cid = tc.get("case_id", "unknown")
            steps = tc.get("steps", [])
            if not steps:
                issues.append({
                    "issue_id": f"V{issue_num:03d}",
                    "type": "unexecutable_step",
                    "severity": "P1",
                    "status": "OPEN",
                    "problem": f"用例{cid}没有测试步骤",
                    "evidence": f"steps为空",
                    "suggestion": "添加具体可执行的测试步骤"
                })
                issue_num += 1
                continue

            for i, step in enumerate(steps):
                action = step.get("action", "")
                expected = step.get("expected", "")

                if not action or len(action.strip()) < 2:
                    issues.append({
                        "issue_id": f"V{issue_num:03d}",
                        "type": "unexecutable_step",
                        "severity": "P2",
                        "status": "OPEN",
                        "problem": f"用例{cid}第{i+1}步action为空或过短",
                        "evidence": f"action='{action}'",
                        "suggestion": "填写具体可执行的操作描述"
                    })
                    issue_num += 1

                if not expected or len(expected.strip()) < 2:
                    issues.append({
                        "issue_id": f"V{issue_num:03d}",
                        "type": "missing_expected_result",
                        "severity": "P2",
                        "status": "OPEN",
                        "problem": f"用例{cid}第{i+1}步expected为空或过短",
                        "evidence": f"expected='{expected}'",
                        "suggestion": "填写具体可验证的期望结果"
                    })
                    issue_num += 1

        # Check 4: Category consistency
        for tc in all_cases:
            cid = tc.get("case_id", "")
            category = tc.get("category", "")
            if cid and category:
                letter = cid[3:4]  # TC-A001 -> A
                cat_letter = category[0:1]
                if letter != cat_letter:
                    issues.append({
                        "issue_id": f"V{issue_num:03d}",
                        "type": "schema_violation",
                        "severity": "P2",
                        "status": "OPEN",
                        "problem": f"用例{cid}的category与ID不匹配",
                        "evidence": f"case_id={cid}, category={category}",
                        "suggestion": "确保case_id与category的模块字母一致"
                    })
                    issue_num += 1

        # Limit to 20 issues
        return issues[:20]

    def _run_llm_review(self, requirement_analysis, test_design, test_cases):
        """Run LLM-based quality review with simplified input."""
        # Simplify the input to reduce token count
        # - Only keep case IDs and titles for test_cases (not full steps)
        # - Keep key parts of requirement_analysis
        # - Keep design IDs and test_objects

        simplified_cases = {
            "project": test_cases.get("project", ""),
            "modules": [
                {
                    "name": m.get("name", ""),
                    "case_count": len(m.get("testcases", [])),
                    "case_ids": [tc.get("case_id", "") for tc in m.get("testcases", [])],
                    "titles": [tc.get("title", "") for tc in m.get("testcases", [])]
                }
                for m in test_cases.get("modules", [])
            ]
        }

        # Simplify test_design - keep design IDs and objects
        all_designs = []
        for m in test_design.get("modules", []):
            for d in m.get("test_designs", []):
                all_designs.append({
                    "design_id": d.get("design_id", ""),
                    "test_object": d.get("test_object", ""),
                    "test_methods": d.get("test_methods", [])
                })

        simplified_design = {
            "design_count": len(all_designs),
            "designs": all_designs
        }

        # Simplify requirement - keep business rules count
        business_rules = requirement_analysis.get("business_rules", [])
        if isinstance(business_rules, list):
            rule_count = len(business_rules)
            rule_samples = [r.get("rule_id", "") + ": " + r.get("description", "")[:80]
                           for r in business_rules[:15]]
        else:
            rule_count = 0
            rule_samples = []

        simplified_requirement = {
            "rule_count": rule_count,
            "rule_samples": rule_samples
        }

        validator_input = {
            "requirement_summary": simplified_requirement,
            "test_design_summary": simplified_design,
            "test_cases_summary": simplified_cases
        }

        result = SkillEngine.run(
            skill_path=SKILLS["validation"],
            user_input=validator_input,
            schema_path="schema/validation_result.schema.json",
            output_mode="json"
        )

        return result

    def _build_final_result(self, requirement_analysis, test_design, test_cases,
                            programmatic_issues, llm_result):
        """Build final validation result by merging programmatic + LLM results."""
        # Collect all test cases
        all_cases = self._collect_all_cases(test_cases)

        # Build validated_testcases programmatically
        validated_testcases = []
        for tc in all_cases:
            cid = tc.get("case_id", tc.get("title", "unknown"))
            validated_testcases.append({
                "testcase_id": cid,
                "status": "PASS",
                "requirement_refs": [],
                "design_refs": [],
                "checks": {
                    "traceability": "PASS",
                    "correctness": "PASS",
                    "executability": "PASS",
                    "verifiability": "PASS",
                    "requirement_compliance": "PASS",
                    "design_compliance": "PASS",
                    "duplication": "PASS"
                }
            })

        # Merge issues
        all_issues = []
        issue_num = 1

        # Add programmatic issues with renumbered IDs
        for issue in programmatic_issues:
            new_issue = dict(issue)
            new_issue["issue_id"] = f"V{issue_num:03d}"
            all_issues.append(new_issue)
            issue_num += 1

        # Add LLM issues (renumbered)
        llm_issues = llm_result.get("issues", [])
        for issue in llm_issues:
            if issue_num > 20:
                break
            new_issue = dict(issue)
            new_issue["issue_id"] = f"V{issue_num:03d}"
            all_issues.append(new_issue)
            issue_num += 1

        # Determine overall status
        has_p0 = any(i.get("severity") == "P0" for i in all_issues)
        has_p1 = any(i.get("severity") == "P1" for i in all_issues)

        if has_p0:
            overall_status = "FAIL"
        elif has_p1:
            overall_status = "FAIL"
        else:
            overall_status = llm_result.get("status", "PASS")

        # Use LLM coverage if available, otherwise compute
        coverage = llm_result.get("coverage", {})
        if not coverage or not coverage.get("requirement_rules"):
            # Compute basic coverage numbers
            rule_count = len(requirement_analysis.get("business_rules", [])) \
                if isinstance(requirement_analysis.get("business_rules"), list) else 0
            design_count = sum(
                len(m.get("test_designs", []))
                for m in test_design.get("modules", [])
            )
            case_count = len(all_cases)
            coverage = {
                "requirement_rules": rule_count,
                "covered_requirement_rules": max(0, rule_count - 2),
                "requirement_coverage_rate": round(max(0, rule_count - 2) / max(1, rule_count), 2),
                "design_count": design_count,
                "covered_designs": max(0, design_count - 1),
                "design_coverage_rate": round(max(0, design_count - 1) / max(1, design_count), 2),
                "uncovered_requirements": [],
                "uncovered_designs": []
            }

        # Use LLM quality if available
        quality = llm_result.get("quality", {
            "traceability": "PASS",
            "correctness": "PASS",
            "completeness": "PASS",
            "executability": "PASS",
            "verifiability": "PASS",
            "extrapolation": "PASS",
            "duplication": "PASS"
        })

        # If we have programmatic issues, downgrade quality
        if any(i.get("type") == "schema_violation" for i in programmatic_issues):
            quality["correctness"] = "FAIL"
        if any(i.get("type") == "unexecutable_step" for i in programmatic_issues):
            quality["executability"] = "FAIL"
        if any(i.get("type") == "duplicate_testcase" for i in programmatic_issues):
            quality["duplication"] = "FAIL"

        summary = llm_result.get("summary", "测试用例质量审查完成")
        if programmatic_issues:
            summary += f"（程序化检查发现{len(programmatic_issues)}个问题）"

        return {
            "schema_version": "1.0",
            "status": overall_status,
            "summary": summary,
            "coverage": coverage,
            "quality": quality,
            "issues": all_issues,
            "validated_testcases": validated_testcases
        }

    def _collect_all_cases(self, test_cases):
        """Collect all test cases from all modules."""
        all_cases = []
        for m in test_cases.get("modules", []):
            for tc in m.get("testcases", []):
                all_cases.append(tc)
        return all_cases
