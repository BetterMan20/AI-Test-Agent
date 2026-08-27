import json
import os
import re
import xml.etree.ElementTree as ET


class XMindExporter:

    @staticmethod
    def _load_json(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            raw = f.read()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try ```json ... ``` code block
        m = re.search(r"```json\s*\n(.*?)\n```", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

        # Try { ... } extraction
        first = raw.find("{")
        last = raw.rfind("}")
        if first >= 0 and last > first:
            try:
                return json.loads(raw[first:last + 1])
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def _write_opml(opml_file, title, root_text, children):
        opml = ET.Element("opml", version="2.0")
        head = ET.SubElement(opml, "head")
        t = ET.SubElement(head, "title")
        t.text = title

        body = ET.SubElement(opml, "body")
        root = ET.SubElement(body, "outline", text=root_text)
        XMindExporter._build_tree(root, children)

        tree = ET.ElementTree(opml)
        tree.write(opml_file, encoding="utf-8", xml_declaration=True)
        print(f"OPML 已生成：{opml_file}")

    @staticmethod
    def _build_tree(parent, children):
        for child in children:
            if isinstance(child, dict):
                node = ET.SubElement(parent, "outline", text=child.get("text", ""))
                if "children" in child:
                    XMindExporter._build_tree(node, child["children"])
            elif isinstance(child, str):
                ET.SubElement(parent, "outline", text=child)

    @staticmethod
    def _norm(item):
        if isinstance(item, dict):
            return item.get("rule", item.get("source", str(item)))
        return str(item)

    # ==============================================================
    # 1. parsed.json (markdown text)
    # ==============================================================
    @staticmethod
    def export_parsed(json_file, opml_file):
        with open(json_file, "r", encoding="utf-8") as f:
            text = f.read()
        # parsed.json is markdown text, not JSON - use directly

        lines = text.split("\n")
        root_text = "需求文档"
        root_children = []
        current_top = None
        current_sub = None
        current_detail = None

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("# "):
                root_text = stripped[2:].strip()
                continue
            if re.match(r"^\d+\.\s", stripped):
                current_top = {"text": re.sub(r"^\d+\.\s", "", stripped), "children": []}
                root_children.append(current_top)
                current_sub = None
                current_detail = None
            elif re.match(r"^[a-z]\.\s", stripped):
                current_sub = {"text": re.sub(r"^[a-z]\.\s", "", stripped), "children": []}
                if current_top:
                    current_top["children"].append(current_sub)
                current_detail = None
            elif re.match(r"^[ivx]+\.\s", stripped):
                current_detail = {"text": re.sub(r"^[ivx]+\.\s", "", stripped), "children": []}
                if current_sub:
                    current_sub["children"].append(current_detail)
                elif current_top:
                    current_top["children"].append(current_detail)
            elif re.match(r"^\d+\.\s", stripped):
                pass
            else:
                if current_detail:
                    current_detail["children"].append(stripped)
                elif current_sub:
                    current_sub["children"].append(stripped)
                elif current_top:
                    current_top["children"].append(stripped)
                else:
                    root_children.append(stripped)

        XMindExporter._write_opml(opml_file, root_text, root_text, root_children)

    # ==============================================================
    # 2. analysis.json
    # ==============================================================
    @staticmethod
    def export_analysis(json_file, opml_file):
        data = XMindExporter._load_json(json_file)
        if data is None:
            print(f"跳过（无法解析 JSON）：{json_file}")
            return

        root_text = data.get("summary", "需求分析")[:50]
        modules = []

        for mod in data.get("modules", []):
            mod_node = {"text": mod.get("name", ""), "children": []}

            field_labels = [
                ("business_context", "业务上下文"),
                ("preconditions", "前置条件"),
                ("business_rules", "业务规则"),
                ("state_rules", "状态规则"),
                ("data_rules", "数据规则"),
                ("time_rules", "时间规则"),
                ("source_rules", "来源规则"),
                ("constraints", "约束"),
                ("ambiguities", "歧义"),
            ]

            for field, label in field_labels:
                items = mod.get(field, [])
                if not items:
                    continue
                field_node = {"text": label, "children": []}
                for item in items:
                    if isinstance(item, dict):
                        if item.get("question"):
                            field_node["children"].append({
                                "text": item["question"],
                                "children": [item.get("context", "")]
                            })
                        else:
                            field_node["children"].append(XMindExporter._norm(item))
                    else:
                        field_node["children"].append(str(item))
                mod_node["children"].append(field_node)

            modules.append(mod_node)

        XMindExporter._write_opml(opml_file, "需求分析", root_text, modules)

    # ==============================================================
    # 3. test_design.json
    # ==============================================================
    @staticmethod
    def export_test_design(json_file, opml_file):
        data = XMindExporter._load_json(json_file)
        if data is None:
            print(f"跳过（无法解析 JSON）：{json_file}")
            return

        project = data.get("project", "测试设计")
        modules = []

        for mod in data.get("modules", []):
            mod_node = {"text": mod.get("name", ""), "children": []}

            for design in mod.get("test_designs", []):
                d_node = {"text": f"{design.get('design_id', '')} - {design.get('test_goal', '')}", "children": []}

                d_node["children"].append(f"测试对象：{design.get('test_object', '')}")
                d_node["children"].append(f"风险等级：{design.get('risk_level', '')}")
                d_node["children"].append(f"测试方法：{', '.join(design.get('test_methods', []))}")
                d_node["children"].append(f"场景：{design.get('scenario', '')}")

                for label, key in [
                    ("条件", "conditions"),
                    ("数据维度", "data_dimensions"),
                    ("时间维度", "time_dimensions"),
                    ("状态维度", "state_dimensions"),
                    ("来源维度", "source_dimensions"),
                    ("预期行为", "expected_behavior"),
                    ("覆盖目标", "coverage_targets"),
                ]:
                    items = design.get(key, [])
                    if not items:
                        continue
                    field_node = {"text": label, "children": []}
                    for item in items:
                        if isinstance(item, dict):
                            if item.get("from") and item.get("to"):
                                field_node["children"].append(f"{item['from']} -> {item['to']}")
                            elif item.get("name") and item.get("values"):
                                field_node["children"].append({
                                    "text": item["name"],
                                    "children": [str(v) for v in item["values"]]
                                })
                            elif item.get("name") and item.get("value"):
                                field_node["children"].append(f"{item['name']}：{item['value']}")
                            elif item.get("type") and item.get("target"):
                                field_node["children"].append(f"{item['type']}：{item['target']}")
                            else:
                                field_node["children"].append(str(item))
                        else:
                            field_node["children"].append(str(item))
                    d_node["children"].append(field_node)

                mod_node["children"].append(d_node)

            modules.append(mod_node)

        XMindExporter._write_opml(opml_file, project, project, modules)

    # ==============================================================
    # 4. test_cases.json
    # ==============================================================
    @staticmethod
    def export_test_cases(json_file, opml_file):
        data = XMindExporter._load_json(json_file)
        if data is None:
            print(f"跳过（无法解析 JSON）：{json_file}")
            return

        project = data.get("project", "测试用例")
        modules = []

        for mod in data.get("modules", []):
            mod_node = {"text": mod.get("name", ""), "children": []}

            for tc in mod.get("testcases", []):
                tc_node = {"text": tc.get("title", ""), "children": []}
                for step in tc.get("steps", []):
                    tc_node["children"].append({
                        "text": f"步骤：{step.get('action', '')}",
                        "children": [f"期望：{step.get('expected', '')}"]
                    })
                mod_node["children"].append(tc_node)

            modules.append(mod_node)

        XMindExporter._write_opml(opml_file, project, project, modules)

    # ==============================================================
    # 5. validation_result.json
    # ==============================================================
    @staticmethod
    def export_validation(json_file, opml_file):
        data = XMindExporter._load_json(json_file)
        if data is None:
            print(f"跳过（无法解析 JSON）：{json_file}")
            return

        root_text = f"验证结果：{data.get('status', 'UNKNOWN')}"
        children = []

        children.append(data.get("summary", ""))

        cov = data.get("coverage", {})
        if cov:
            cov_node = {"text": "覆盖率", "children": [
                f"需求规则：{cov.get('covered_requirement_rules', 0)}/{cov.get('requirement_rules', 0)}",
                f"需求覆盖率：{cov.get('requirement_coverage_rate', 0):.0%}",
                f"测试设计：{cov.get('covered_designs', 0)}/{cov.get('design_count', 0)}",
                f"设计覆盖率：{cov.get('design_coverage_rate', 0):.0%}",
            ]}
            for key in ["uncovered_requirements", "uncovered_designs"]:
                items = cov.get(key, [])
                if items:
                    cov_node["children"].append({"text": key, "children": items})
            children.append(cov_node)

        qual = data.get("quality", {})
        if qual:
            qual_node = {"text": "质量维度", "children": [
                f"{k}: {v}" for k, v in qual.items()
            ]}
            children.append(qual_node)

        issues = data.get("issues", [])
        if issues:
            issues_node = {"text": f"问题列表（{len(issues)}）", "children": []}
            for iss in issues:
                issue_text = f"{iss.get('issue_id', '')} [{iss.get('severity', '')}] {iss.get('type', '')}"
                issue_children = [iss.get("problem", "")]
                if iss.get("suggestion"):
                    issue_children.append(f"建议：{iss['suggestion']}")
                issues_node["children"].append({"text": issue_text, "children": issue_children})
            children.append(issues_node)

        vts = data.get("validated_testcases", [])
        if vts:
            vt_node = {"text": f"用例验证（{len(vts)}）", "children": []}
            for vt in vts:
                tc_text = f"{vt.get('testcase_id', '')} - {vt.get('status', '')}"
                tc_children = []
                refs = vt.get("requirement_refs", [])
                if refs:
                    tc_children.append({"text": "需求引用", "children": refs})
                drefs = vt.get("design_refs", [])
                if drefs:
                    tc_children.append({"text": "设计引用", "children": drefs})
                checks = vt.get("checks", {})
                if checks:
                    tc_children.append({"text": "检查项", "children": [
                        f"{k}: {v}" for k, v in checks.items()
                    ]})
                vt_node["children"].append({"text": tc_text, "children": tc_children})
            children.append(vt_node)

        XMindExporter._write_opml(opml_file, "质量验证", root_text, children)

    # ==============================================================
    # Export All
    # ==============================================================
    @staticmethod
    def export_all(output_dir="output", opml_dir="opmls"):
        if not os.path.exists(opml_dir):
            os.makedirs(opml_dir)

        exports = [
            ("parsed.json", "parsed.opml", XMindExporter.export_parsed),
            ("analysis.json", "analysis.opml", XMindExporter.export_analysis),
            ("test_design.json", "test_design.opml", XMindExporter.export_test_design),
            ("test_cases.json", "test_cases.opml", XMindExporter.export_test_cases),
            ("validation_result.json", "validation_result.opml", XMindExporter.export_validation),
        ]

        for json_name, opml_name, func in exports:
            json_path = os.path.join(output_dir, json_name)
            opml_path = os.path.join(opml_dir, opml_name)
            if not os.path.exists(json_path):
                print(f"跳过（文件不存在）：{json_path}")
                continue
            try:
                func(json_path, opml_path)
            except Exception as e:
                print(f"导出失败 {json_name} -> {opml_name}: {e}")

        print(f"\n全部 OPML 文件已生成到 {opml_dir}/ 目录")
