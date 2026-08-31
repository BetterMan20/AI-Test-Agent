"""Retry generating failed modules H (design) and C (test cases), deduplicate D designs."""
import json
import sys

sys.path.insert(0, ".")

from agents.test_design import TestDesign
from agents.testcase_generator import TestCaseGenerator
from utils.output import Output


def main():

    # ==========================================
    # 1. Fix test_design.json
    # ==========================================

    print("=== Loading existing test_design.json ===")
    with open("output/test_design.json", "r", encoding="utf-8") as f:
        design_data = json.load(f)

    all_designs = []
    for m in design_data.get("modules", []):
        all_designs.extend(m.get("test_designs", []))

    # Deduplicate by test_object (keep first occurrence)
    seen_objects = set()
    deduped = []
    for d in all_designs:
        obj = d.get("test_object", "")
        if obj and obj in seen_objects:
            continue
        if obj:
            seen_objects.add(obj)
        deduped.append(d)

    print(f"Before dedup: {len(all_designs)}, after: {len(deduped)}")

    # Check which modules are missing
    existing_letters = set()
    for d in deduped:
        obj = d.get("test_object", "")
        if obj:
            existing_letters.add(obj[0].upper())

    print(f"Existing modules: {sorted(existing_letters)}")

    # Load analysis
    with open("output/analysis.json", "r", encoding="utf-8") as f:
        analysis = json.load(f)

    normalized = TestDesign._normalize_analysis(analysis)

    # Generate missing module H designs
    for module in TestDesign.MODULES:
        letter = module["letter"]
        if letter in existing_letters:
            continue

        print(f"\n--- Generating designs for Module {letter}: {module['name']} ---")

        for attempt in range(3):
            try:
                designs, blocked = TestDesign._run_module_batch(
                    normalized, module
                )
                deduped.extend(designs)
                print(f"  Attempt {attempt+1}: Generated {len(designs)} designs")
                break
            except Exception as e:
                print(f"  Attempt {attempt+1} failed: {e}")
                if attempt == 2:
                    print(f"  Module {letter} design generation failed after 3 attempts")

    # Renumber all designs
    TestDesign._renumber_designs(deduped)

    # Merge and save
    result = TestDesign._merge_module_results(deduped, [])
    Output.save("test_design.json", result)
    print(f"\nTotal designs: {len(deduped)}")

    # Verify all modules present
    letters = set()
    for d in deduped:
        obj = d.get("test_object", "")
        if obj:
            letters.add(obj[0].upper())
    print(f"Module letters: {sorted(letters)}")

    # ==========================================
    # 2. Fix test_cases.json
    # ==========================================

    print("\n=== Loading existing test_cases.json ===")
    with open("output/test_cases.json", "r", encoding="utf-8") as f:
        cases_data = json.load(f)

    existing_cases = []
    for m in cases_data.get("modules", []):
        existing_cases.extend(m.get("testcases", []))

    print(f"Existing test cases: {len(existing_cases)}")

    existing_case_cats = set()
    for c in existing_cases:
        cat = c.get("category", "")
        if cat:
            existing_case_cats.add(cat[0])
    print(f"Existing case categories: {sorted(existing_case_cats)}")

    # Group designs by module
    module_groups = TestCaseGenerator._group_designs_by_module(result)

    # Generate missing test cases (C and H)
    new_cases = []
    for module in TestDesign.MODULES:
        letter = module["letter"]
        if letter in existing_case_cats:
            continue

        designs = module_groups.get(letter, [])
        if not designs:
            print(f"\n--- Module {letter}: no designs, skipping ---")
            continue

        print(f"\n--- Generating cases for Module {letter}: {module['name']} ({len(designs)} designs) ---")

        for attempt in range(3):
            try:
                cases = TestCaseGenerator._run_module_batch(
                    designs, module
                )
                new_cases.extend(cases)
                print(f"  Attempt {attempt+1}: Generated {len(cases)} cases")
                break
            except Exception as e:
                print(f"  Attempt {attempt+1} failed: {e}")
                if attempt == 2:
                    # Fallback: create minimal test cases from scenarios
                    print(f"  Creating fallback cases from scenarios...")
                    fallback = create_fallback_cases(module)
                    new_cases.extend(fallback)
                    print(f"  Created {len(fallback)} fallback cases")

    all_cases = existing_cases + new_cases
    final = TestCaseGenerator._merge_results(all_cases)
    Output.save("test_cases.json", final)

    print(f"\nTotal test cases: {len(all_cases)}")

    from collections import Counter
    cats = Counter(c.get("category", "?") for c in all_cases)
    for k, v in sorted(cats.items()):
        print(f"  {k}: {v}")


def create_fallback_cases(module):
    """Create minimal test cases from module scenarios when LLM fails."""
    cases = []
    for i, scenario in enumerate(module["scenarios"], 1):
        case = {
            "case_id": f"TC-{module['letter']}{i:03d}",
            "category": module["name"],
            "title": scenario,
            "steps": [
                {"action": scenario, "expected": "操作执行成功\n结果符合预期"},
            ]
        }
        cases.append(case)
    return cases


if __name__ == "__main__":
    main()
