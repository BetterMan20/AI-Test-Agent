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
    # Get Validation Result
    # ----------------------------------------------------------

    validation = result.get("validation", {})

    status = validation.get("status", "UNKNOWN")
    quality = validation.get("quality", {})
    issues = validation.get("issues", [])

    print(f"\nValidation Status: {status}")

    if quality:
        print("\nQuality Dimensions:")
        for dim, result in quality.items():
            print(f"  {dim}: {result}")

    # ----------------------------------------------------------
    # PASS
    # ----------------------------------------------------------

    if status == "PASS":

        print("\n✓ Test cases passed validation.")
        print("✓ Final output: output/validation_result.json")

    # ----------------------------------------------------------
    # FAIL
    # ----------------------------------------------------------

    elif status == "FAIL":

        print("\n✗ Test cases failed validation.")
        print(f"Found {len(issues)} issue(s).")

        for issue in issues:

            print("\n--------------------------------")
            print(f"Severity: {issue.get('severity', 'UNKNOWN')}")
            print(f"Type: {issue.get('type', 'UNKNOWN')}")
            print(f"Problem: {issue.get('problem', '')}")
            print(f"Suggestion: {issue.get('suggestion', '')}")

    # ----------------------------------------------------------
    # UNKNOWN / BLOCKED
    # ----------------------------------------------------------

    else:

        print(f"\n? Validation status: {status}")
        print("Please check output/validation_result.json")

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