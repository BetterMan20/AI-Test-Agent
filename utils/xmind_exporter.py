import json
import xml.etree.ElementTree as ET


class XMindExporter:

    @staticmethod
    def export(json_file, opml_file):

        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        project = data.get("project", "测试用例")

        # OPML 根节点
        opml = ET.Element("opml", version="2.0")

        head = ET.SubElement(opml, "head")
        title = ET.SubElement(head, "title")
        title.text = project

        body = ET.SubElement(opml, "body")

        # Root
        root = ET.SubElement(
            body,
            "outline",
            text=project
        )

        # ==================================================
        # Root
        #   └── 模块
        #       └── 用例标题
        #           └── 操作步骤：具体操作
        #               └── 期望结果：具体结果
        # ==================================================

        for module in data.get("modules", []):

            # 第一层：模块
            module_node = ET.SubElement(
                root,
                "outline",
                text=module.get("name", "")
            )

            for testcase in module.get("testcases", []):

                # 第二层：用例标题
                testcase_node = ET.SubElement(
                    module_node,
                    "outline",
                    text=testcase.get("title", "")
                )

                steps = testcase.get("steps", [])
                expected = testcase.get("expected", [])

                # 第三层 + 第四层
                for i, step in enumerate(steps):

                    # 操作步骤节点
                    step_node = ET.SubElement(
                        testcase_node,
                        "outline",
                        text=f"操作步骤：{step}"
                    )

                    # 对应的期望结果
                    if i < len(expected):

                        ET.SubElement(
                            step_node,
                            "outline",
                            text=f"期望结果：{expected[i]}"
                        )

        # 写入 OPML
        tree = ET.ElementTree(opml)

        tree.write(
            opml_file,
            encoding="utf-8",
            xml_declaration=True
        )

        print(f"XMind OPML 已生成：{opml_file}")