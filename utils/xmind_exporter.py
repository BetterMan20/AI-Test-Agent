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

        root_text = "需求分析"
        children = []

        field_labels = [
            ("actors", "参与者"),
            ("rules", "业务规则"),
            ("states", "状态"),
            ("relations", "关系"),
            ("constraints", "约束"),
        ]

        for field, label in field_labels:
            items = data.get(field, [])
            if not items:
                continue
            field_node = {"text": f"{label}（{len(items)}）", "children": []}
            for item in items:
                if field == "actors":
                    field_node["children"].append({
                        "text": f"{item.get('id', '')} {item.get('name', '')}",
                        "children": [f"source: {', '.join(item.get('source_facts', []))}"]
                    })
                elif field == "rules":
                    field_node["children"].append({
                        "text": f"{item.get('id', '')} [{item.get('confidence', '')}] {item.get('content', '')[:60]}",
                        "children": [f"source: {', '.join(item.get('source_facts', []))}"]
                    })
                elif field == "states":
                    desc = item.get('description', '')
                    field_node["children"].append({
                        "text": f"{item.get('id', '')} {item.get('name', '')}",
                        "children": [desc] if desc else []
                    })
                elif field == "relations":
                    field_node["children"].append({
                        "text": f"{item.get('id', '')} {item.get('source', '')} -> {item.get('target', '')} [{item.get('type', '')}]",
                        "children": [item.get('description', '')] if item.get('description') else []
                    })
                elif field == "constraints":
                    field_node["children"].append({
                        "text": f"{item.get('id', '')} {item.get('content', '')[:60]}",
                        "children": [f"source: {', '.join(item.get('source_facts', []))}"]
                    })
            children.append(field_node)

        XMindExporter._write_opml(opml_file, "需求分析", root_text, children)

    # ==============================================================
    # 3. test_design.json
    # ==============================================================
    @staticmethod
    def export_test_design(json_file, opml_file):
        data = XMindExporter._load_json(json_file)
        if data is None:
            print(f"跳过（无法解析 JSON）：{json_file}")
            return

        root_text = "测试设计"
        children = []

        tps = data.get("test_points", [])
        if tps:
            tp_node = {"text": f"测试点（{len(tps)}）", "children": []}
            for tp in tps:
                tp_text = f"{tp.get('id', '')} [{tp.get('priority', '')}] {tp.get('title', '')}"
                tp_children = [
                    f"类型：{tp.get('type', '')}",
                    f"状态：{tp.get('status', '')}",
                ]
                if tp.get("description"):
                    tp_children.append(tp["description"])
                if tp.get("related_rules"):
                    tp_children.append(f"关联规则：{', '.join(tp['related_rules'])}")
                if tp.get("related_states"):
                    tp_children.append(f"关联状态：{', '.join(tp['related_states'])}")
                if tp.get("related_gaps"):
                    tp_children.append(f"关联缺口：{', '.join(tp['related_gaps'])}")
                tp_node["children"].append({"text": tp_text, "children": tp_children})
            children.append(tp_node)

        cov = data.get("coverage", {})
        if cov:
            cov_children = []
            for dim, items in cov.items():
                if items:
                    cov_children.append({"text": f"{dim}：{', '.join(items)}"})
            if cov_children:
                children.append({"text": "覆盖率", "children": cov_children})

        blocked = data.get("blocked_designs", [])
        if blocked:
            b_node = {"text": f"阻塞设计（{len(blocked)}）", "children": []}
            for b in blocked:
                b_node["children"].append({
                    "text": b.get("test_point_id", ""),
                    "children": [b.get("reason", "")]
                })
            children.append(b_node)

        XMindExporter._write_opml(opml_file, "测试设计", root_text, children)

    # ==============================================================
    # 4. test_cases.json
    # ==============================================================
    @staticmethod
    def export_test_cases(json_file, opml_file):
        data = XMindExporter._load_json(json_file)
        if data is None:
            print(f"跳过（无法解析 JSON）：{json_file}")
            return

        root_text = "测试用例"
        children = []

        tcs = data.get("test_cases", [])
        if tcs:
            tc_node = {"text": f"测试用例（{len(tcs)}）", "children": []}
            for tc in tcs:
                title = f"{tc.get('id', '')} [{tc.get('priority', '')}] {tc.get('title', '')}"
                tc_children = []

                if tc.get("test_point_id"):
                    tc_children.append(f"测试点：{tc['test_point_id']}")

                for pre in tc.get("preconditions", []):
                    tc_children.append(f"前置：{pre}")

                for td in tc.get("test_data", []):
                    tc_children.append(f"数据：{td}")

                steps = tc.get("steps", [])
                if steps:
                    steps_node = {"text": "步骤", "children": []}
                    for step in steps:
                        steps_node["children"].append(f"{step.get('step', '')}. {step.get('action', '')}")
                    tc_children.append(steps_node)

                for exp in tc.get("expected_results", []):
                    tc_children.append(f"期望：{exp}")

                tc_node["children"].append({"text": title, "children": tc_children})
            children.append(tc_node)

        blocked = data.get("blocked_cases", [])
        if blocked:
            b_node = {"text": f"阻塞用例（{len(blocked)}）", "children": []}
            for b in blocked:
                b_node["children"].append({
                    "text": b.get("test_point_id", ""),
                    "children": [b.get("reason", "")]
                })
            children.append(b_node)

        XMindExporter._write_opml(opml_file, "测试用例", root_text, children)

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
    # 6. facts.json
    # ==============================================================
    @staticmethod
    def export_facts(json_file, opml_file):
        data = XMindExporter._load_json(json_file)
        if data is None:
            print(f"跳过（无法解析 JSON）：{json_file}")
            return

        root_text = "需求事实"
        children = []

        facts = data.get("facts", data if isinstance(data, list) else [])
        if isinstance(data, dict) and not facts:
            for key, value in data.items():
                if isinstance(value, list):
                    facts = value
                    break

        for fact in facts if isinstance(facts, list) else []:
            if isinstance(fact, dict):
                fact_text = fact.get("id", fact.get("title", ""))
                fact_children = [fact.get("content", fact.get("text", ""))]
                if fact.get("source"):
                    fact_children.append(f"来源：{fact['source']}")
                if fact.get("type"):
                    fact_children.append(f"类型：{fact['type']}")
                children.append({"text": fact_text, "children": fact_children})
            else:
                children.append(str(fact))

        XMindExporter._write_opml(opml_file, "需求事实", root_text, children)

    # ==============================================================
    # 7. gaps.json
    # ==============================================================
    @staticmethod
    def export_gaps(json_file, opml_file):
        data = XMindExporter._load_json(json_file)
        if data is None:
            print(f"跳过（无法解析 JSON）：{json_file}")
            return

        root_text = "需求缺口"
        children = []

        summary = data.get("summary", {})
        if summary:
            children.append({"text": "汇总", "children": [
                f"{k}: {v}" for k, v in summary.items()
            ]})

        gaps = data.get("gaps", [])
        if gaps:
            gaps_node = {"text": f"缺口列表（{len(gaps)}）", "children": []}
            for gap in gaps:
                gap_text = f"{gap.get('id', '')} [{gap.get('priority', '')}] {gap.get('type', '')}"
                gap_children = [gap.get("description", gap.get("problem", ""))]
                if gap.get("suggestion"):
                    gap_children.append(f"建议：{gap['suggestion']}")
                gaps_node["children"].append({"text": gap_text, "children": gap_children})
            children.append(gaps_node)

        XMindExporter._write_opml(opml_file, "需求缺口", root_text, children)

    # ==============================================================
    # 8. quality_review.json
    # ==============================================================
    @staticmethod
    def export_quality_review(json_file, opml_file):
        data = XMindExporter._load_json(json_file)
        if data is None:
            print(f"跳过（无法解析 JSON）：{json_file}")
            return

        root_text = "质量评估"
        children = []

        children.append(data.get("summary", ""))

        metrics = data.get("metrics", {})
        if metrics:
            children.append({"text": "指标", "children": [
                f"{k}: {v}" for k, v in metrics.items()
            ]})

        cov = data.get("coverage", {})
        if cov:
            children.append({"text": "覆盖率", "children": [
                f"{k}: {v}" for k, v in cov.items()
            ]})

        dims = data.get("quality_dimensions", {})
        if dims:
            children.append({"text": "质量维度", "children": [
                f"{k}: {v}" for k, v in dims.items()
            ]})

        issues_sum = data.get("issues_summary", {})
        if issues_sum:
            children.append({"text": "问题汇总", "children": [
                f"{k}: {v}" for k, v in issues_sum.items()
            ]})

        children.append(f"幻觉风险：{data.get('hallucination_risk', 'UNKNOWN')}")

        issues = data.get("issues", [])
        if issues:
            issues_node = {"text": f"问题列表（{len(issues)}）", "children": []}
            for iss in issues:
                issue_text = f"{iss.get('issue_id', '')} [{iss.get('severity', '')}] {iss.get('type', '')}"
                issues_node["children"].append({"text": issue_text, "children": [
                    iss.get("problem", ""),
                    f"建议：{iss.get('suggestion', '')}"
                ]})
            children.append(issues_node)

        XMindExporter._write_opml(opml_file, "质量评估", root_text, children)

    # ==============================================================
    # 9. release_gate.json
    # ==============================================================
    @staticmethod
    def export_release_gate(json_file, opml_file):
        data = XMindExporter._load_json(json_file)
        if data is None:
            print(f"跳过（无法解析 JSON）：{json_file}")
            return

        gate = data.get("gate", "UNKNOWN")
        root_text = f"执行准入：{gate}"
        children = []

        reasons = data.get("reasons", [])
        if reasons:
            children.append({"text": "判定原因", "children": reasons})

        snapshot = data.get("metrics_snapshot", {})
        if snapshot:
            children.append({"text": "指标快照", "children": [
                f"{k}: {v}" for k, v in snapshot.items()
            ]})

        XMindExporter._write_opml(opml_file, "执行准入", root_text, children)

    # ==============================================================
    # Export All
    # ==============================================================
    @staticmethod
    def export_all(output_dir="output", opml_dir="opmls"):
        if not os.path.exists(opml_dir):
            os.makedirs(opml_dir)

        exports = [
            ("parsed.json", "parsed.opml", XMindExporter.export_parsed),
            ("facts.json", "facts.opml", XMindExporter.export_facts),
            ("analysis.json", "analysis.opml", XMindExporter.export_analysis),
            ("gaps.json", "gaps.opml", XMindExporter.export_gaps),
            ("test_design.json", "test_design.opml", XMindExporter.export_test_design),
            ("test_cases.json", "test_cases.opml", XMindExporter.export_test_cases),
            ("validation_result.json", "validation_result.opml", XMindExporter.export_validation),
            ("quality_review.json", "quality_review.opml", XMindExporter.export_quality_review),
            ("release_gate.json", "release_gate.opml", XMindExporter.export_release_gate),
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
