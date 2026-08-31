"""Generate missing test designs and test cases for modules C, H, K."""
import json
import sys

sys.path.insert(0, ".")

from agents.test_design import TestDesign
from agents.testcase_generator import TestCaseGenerator
from utils.output import Output


def main():

    missing_letters = {"C", "H", "K"}

    print("=== Loading existing test_design.json ===")
    with open("output/test_design.json", "r", encoding="utf-8") as f:
        design_data = json.load(f)

    existing_designs = []
    for m in design_data.get("modules", []):
        existing_designs.extend(m.get("test_designs", []))

    print(f"Existing designs: {len(existing_designs)}")

    existing_letters = set()
    for d in existing_designs:
        obj = d.get("test_object", "")
        if obj:
            existing_letters.add(obj[0].upper())

    print(f"Existing module letters: {sorted(existing_letters)}")
    print(f"Missing module letters: {sorted(missing_letters - existing_letters)}")

    # Load analysis
    with open("output/analysis.json", "r", encoding="utf-8") as f:
        analysis = json.load(f)

    normalized = TestDesign._normalize_analysis(analysis)

    new_designs = []
    new_blocked = []

    for module in TestDesign.MODULES:
        letter = module["letter"]
        if letter not in missing_letters:
            continue

        if letter in existing_letters:
            print(f"\n--- Module {letter} already exists, skipping ---")
            continue

        print(f"\n--- Generating designs for Module {letter}: {module['name']} ---")

        try:
            designs, blocked = TestDesign._run_module_batch(
                normalized, module
            )
            new_designs.extend(designs)
            if blocked:
                new_blocked.extend(blocked)
            print(f"  Generated {len(designs)} designs")
        except Exception as e:
            print(f"  Module {letter} failed: {e}")

    all_designs = existing_designs + new_designs

    TestDesign._renumber_designs(all_designs)

    result = TestDesign._merge_module_results(
        all_designs, new_blocked
    )

    Output.save("test_design.json", result)
    print(f"\nTotal designs: {len(all_designs)}")

    # Now generate test cases for the missing modules
    print("\n=== Generating test cases for missing modules ===")

    with open("output/test_cases.json", "r", encoding="utf-8") as f:
        cases_data = json.load(f)

    existing_cases = []
    for m in cases_data.get("modules", []):
        existing_cases.extend(m.get("testcases", []))

    print(f"Existing test cases: {len(existing_cases)}")

    module_groups = TestCaseGenerator._group_designs_by_module(result)

    new_cases = []

    for module in TestDesign.MODULES:
        letter = module["letter"]
        if letter not in missing_letters:
            continue

        designs = module_groups.get(letter, [])
        if not designs:
            print(f"\n--- Module {letter}: no designs, skipping ---")
            continue

        print(f"\n--- Generating cases for Module {letter}: {module['name']} ({len(designs)} designs) ---")

        try:
            cases = TestCaseGenerator._run_module_batch(
                designs, module
            )
            new_cases.extend(cases)
            print(f"  Generated {len(cases)} cases")
        except Exception as e:
            print(f"  Module {letter} failed: {e}")

    all_cases = existing_cases + new_cases

    final = TestCaseGenerator._merge_results(all_cases)

    Output.save("test_cases.json", final)
    print(f"\nTotal test cases: {len(all_cases)}")

    from collections import Counter
    cats = Counter(c.get("category", "?") for c in all_cases)
    for k, v in sorted(cats.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
