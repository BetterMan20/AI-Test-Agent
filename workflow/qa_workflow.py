from agents.requirement_parser import RequirementParser
from agents.requirement_analysis import RequirementAnalysis
from agents.testcase_generator import TestCaseGenerator

from utils.output import Output
from utils.xmind_exporter import XMindExporter


class QAWorkflow:

    def run(self, requirement):

        print("========== QA Workflow ==========")

        # Step1 Parser
        print("========== parser ==========")

        parsed = RequirementParser().run(requirement)

        Output.save(
            "parsed.md",
            parsed
        )

        # Step2 Analysis
        print("========== analysis ==========")

        analysis = RequirementAnalysis().run(parsed)

        Output.save(
            "analysis.md",
            analysis
        )

        # Step3 Test Case Generator
        print("========== testcase generator ==========")

        testcase = TestCaseGenerator().run(analysis)

        # testcase_generator.py
        # 已经负责保存 output/content.json

        # Step4 XMind Export
        print("========== XMind Export ==========")

        XMindExporter.export(
            "output/content.json",
            "output/test.opml"
        )

        return testcase