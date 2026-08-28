from workflow.qa_workflow import QAWorkflow
from utils.file_reader import FileReader
from utils.xmind_exporter import XMindExporter


def main():

    print("=" * 60)
    print("AI Test Agent")
    print("=" * 60)


    # ==========================================================
    # 1. Read Requirement
    # ==========================================================

    requirement_path = "input/requirement.txt"


    print(
        f"\nReading requirement: {requirement_path}"
    )


    requirement = FileReader.read(
        requirement_path
    )


    if not requirement:

        raise ValueError(
            "Requirement is empty."
        )


    print(
        f"Requirement loaded: {len(requirement)} characters"
    )


    # ==========================================================
    # 2. Start QA Workflow
    # ==========================================================

    workflow = QAWorkflow()


    result = workflow.run(
        requirement
    )


    # ==========================================================
    # 3. Final Result
    # ==========================================================

    print("\n" + "=" * 60)
    print("AI Test Agent Finished")
    print("=" * 60)


    # ----------------------------------------------------------
    # Release Gate
    # ----------------------------------------------------------

    gate = result.get("release_gate", {})

    gate_decision = gate.get("gate", "UNKNOWN")
    reasons = gate.get("reasons", [])

    symbols = {
        "PASS": "[PASS]",
        "CONDITIONAL": "[CONDITIONAL]",
        "BLOCK": "[BLOCK]",
    }

    print(f"\nRelease Gate: {symbols.get(gate_decision, '[UNKNOWN]')} {gate_decision}")

    for reason in reasons:
        print(f"  - {reason}")

    # ----------------------------------------------------------
    # Show issues if any
    # ----------------------------------------------------------

    quality_review = result.get("quality_review", {})
    issues = quality_review.get("issues", [])

    if issues:
        print(f"\nIssues ({len(issues)}):")
        for issue in issues:
            print("\n--------------------------------")
            print(f"Severity: {issue.get('severity', 'UNKNOWN')}")
            print(f"Type: {issue.get('type', 'UNKNOWN')}")
            print(f"Problem: {issue.get('problem', '')}")
            print(f"Suggestion: {issue.get('suggestion', '')}")

    # ==========================================================
    # Export OPML
    # ==========================================================

    print("\n" + "=" * 60)
    print("Exporting OPML files")
    print("=" * 60)




    XMindExporter.export_all()

    return result



if __name__ == "__main__":

    main()