"""
agents/requirement_analysis.py

Requirement Analysis — Business Model Builder
=============================================

职责：
    从 Requirement Facts 构建业务模型（Business Model）。

核心原则：

       Facts
            ↓
    Requirement Analysis
            ↓
    Business Model (Entities, States, Conditions, Actions, Outcomes, Relations)
            ↓
    Gap Detection / Test Design

Requirement Analysis 负责：
    - 识别业务对象（Entities）
    - 识别业务状态（States）
    - 识别触发条件（Conditions）
    - 识别业务动作（Actions）
    - 识别可观察结果（Outcomes）
    - 建立因果关系（Relations）
    - 区分需求事实（derived=false）与测试推导（derived=true）
    - 引用 Fact IDs

Requirement Analysis 不负责：
    - Fact Extraction
    - Gap Detection
    - Test Design
    - Test Case 生成
"""

from __future__ import annotations

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

from configs.skills import SKILLS
from utils.skill_engine import SkillEngine
from utils.skill_loader import load_skill


class RequirementAnalysis:

    AGENT_NAME = "requirement_analysis"
    STAGE_NAME = "Requirement Analysis"

    SKILL_PATH = SKILLS["analysis"]

    SCHEMA_PATH = (
        Path(__file__).resolve().parent.parent
        / "schema"
        / "requirement_analysis.schema.json"
    )

    # 分块并行建模。单块 Fact 数越小，LLM 单次调用的输入/输出都越小，
    # 从机制上杜绝 glm-4.5-air 在"逐条遍历全部 Fact"时先把输出预算烧光、
    # 正文 JSON 为空（finish_reason=length）的问题。
    # 实跑发现 25 条/块在密集规则块（如黑白名单）上仍会压爆 max_tokens=32000，
    # 故降到 12 条/块，并对碎片调用单独收紧输出上限，逼模型精简。
    CHUNK_SIZE = 12             # 每块最多 Fact 数
    MAX_PARALLEL = 3            # 并行抽取的最大并发数
    MIN_FACTS_TO_CHUNK = 45     # 少于该数量时退化为单次调用（合并有开销）
    FRAGMENT_MAX_TOKENS = 20000  # 碎片调用输出上限（12 块≈1.5 万token保底，留~30%余量防截断）

    # ======================================================
    # Public API
    # ======================================================

    def run(self, facts: Any) -> Dict[str, Any]:

        if not isinstance(facts, dict):
            raise ValueError(
                "RequirementAnalysis requires facts as dict."
            )

        fact_list = facts.get("facts", [])

        if not isinstance(fact_list, list) or not fact_list:
            raise ValueError(
                "RequirementAnalysis requires non-empty facts list."
            )

        # 少量 Fact：一次调用即可，避免分块+合并的额外开销，且保留跨块关系。
        if len(fact_list) <= self.MIN_FACTS_TO_CHUNK:

            return SkillEngine.run(
                skill_path=self.SKILL_PATH,
                input_data=facts,
                schema_path=str(self.SCHEMA_PATH),
                output_mode="json",
            )

        # 大量 Fact：分块并行建模，再确定性合并。
        return self._chunk_and_merge(fact_list)

    # ======================================================
    # Chunked modeling
    # ======================================================

    def _chunk_and_merge(
        self,
        fact_list: List[Dict[str, Any]],
    ) -> Dict[str, Any]:

        chunks: List[Dict[str, Any]] = []
        for start in range(0, len(fact_list), self.CHUNK_SIZE):
            chunks.append(
                {"facts": fact_list[start:start + self.CHUNK_SIZE]}
            )

        total = len(chunks)

        with tempfile.TemporaryDirectory(
            prefix="analysis_frag_"
        ) as tmpdir:

            skill_path = self._write_fragment_skill(tmpdir)
            frag_schema = self._write_relaxed_schema(tmpdir)

            ordered: List[Dict[str, Any]] = [{} for _ in chunks]
            errors: List[Exception] = []

            def _one(idx: int, chunk: Dict[str, Any]) -> Dict[str, Any]:
                return (idx, SkillEngine.run(
                    skill_path=skill_path,
                    input_data=chunk,
                    schema_path=frag_schema,
                    output_mode="json",
                    max_tokens=self.FRAGMENT_MAX_TOKENS,
                ))

            with ThreadPoolExecutor(
                max_workers=min(self.MAX_PARALLEL, total)
            ) as pool:
                futures = [
                    pool.submit(_one, idx, chunk)
                    for idx, chunk in enumerate(chunks)
                ]
                for future in as_completed(futures):
                    try:
                        idx, model = future.result()
                        ordered[idx] = model
                    except Exception as e:  # noqa: BLE001
                        errors.append(e)

        if errors:
            raise errors[0]

        merged = self._merge(ordered)

        self._assert_valid(merged)

        print(
            f"[RequirementAnalysis] 分块建模完成：{total} 块 → "
            f"合并后 entities={len(merged['entities'])}, "
            f"states={len(merged['states'])}, "
            f"conditions={len(merged['conditions'])}, "
            f"actions={len(merged['actions'])}, "
            f"outcomes={len(merged['outcomes'])}, "
            f"relations={len(merged['relations'])}"
        )

        return merged

    def _write_relaxed_schema(self, tmpdir: str) -> str:
        """fragment 用的 schema：7 个根数组 minItems 放宽为 0。

        片段只是全文一部分，可能自然产出少于整篇标准的元素数量
        （例如全是 RULE/QUANTITY 的块可能没有 actor）；强制 minItems
        会逼模型为凑数杜撰本块不存在的内容。合并后再统一按严格 schema 校验。
        """
        import json as _json
        import copy

        with open(self.SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = _json.load(f)

        schema = copy.deepcopy(schema)
        for arr in ("actors", "entities", "states",
                    "conditions", "actions", "outcomes", "relations"):
            props = schema.get("properties", {}).get(arr)
            if isinstance(props, dict):
                props["minItems"] = 0

        path = os.path.join(tmpdir, "requirement_analysis_fragment.schema.json")
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(schema, f, ensure_ascii=False, indent=2)
        return path

    def _assert_valid(self, merged: Dict[str, Any]) -> None:
        from jsonschema import validate as _validate
        from jsonschema.exceptions import ValidationError

        import json as _json
        with open(self.SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = _json.load(f)

        try:
            _validate(instance=merged, schema=schema)
        except ValidationError as e:
            raise ValueError(
                "S2 分块合并结果未通过严格 Schema："
                + SkillEngine._format_validation_error(e)
            ) from e

    @staticmethod
    def _write_fragment_skill(tmpdir: str) -> str:

        base = load_skill(SKILLS["analysis"])

        header = """

## 分块建模模式（本调用只处理一个片段）

你收到的是全部需求 Facts 的一个**子集**（片段），每个 Fact 保留其**全局原始编号**（Fxxx，不要改动编号）。

规则：
1. 只基于【本片段内】出现的 Fact 构建这一部分的业务模型；不把本片段内容与其它片段合并，也不脑补其它片段的内容。
2. `source_facts` 只能引用本片段输入里真实存在的全局 F 编号（如 "F023"），不要凭空写 F001 之类的本块不存在的编号。
3. 本片段只是全文的一部分：实体/状态/条件/动作/结果/关系的数量只要求“覆盖本片段真实存在的内容”，允许明显少于整篇标准（例如本片段只有 1~4 个实体也完全正常）。
4. 严禁为凑数量杜撰本片段不存在的对象、规则、条件、动作或数值。
5. 元素 id 使用本片段局部编号（A001/E001/…），允许与其它片段重复，合并阶段会统一重编号，你无需跨片段保持一致。
6. 思考从简：直接输出符合输出格式的完整 JSON，不要在 reasoning 里逐条枚举本片段每个 Fact 的映射。
7. 【精简输出，控制体量】这是硬性要求：description 一律 ≤ 20 个中文字符，一句话讲清即可；attributes 只列关键属性（≤4 项）；严禁"每条 Fact 都拆成一个实体+一个状态+一个动作+一个结果"的重复膨胀——能合并到同一实体的就合并。整个片段输出尽量控制在数千字符内。
8. 【禁止多余字段】只输出根对象要求的 7 个根字段（actors/entities/states/conditions/actions/outcomes/relations）及其子字段，绝不输出 test_cases、test_points、gap 分析或任何 schema 之外的内容。

"""
        path = os.path.join(tmpdir, "requirement-analysis-fragment.skill.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(base + header)
        return path

    # ======================================================
    # Deterministic merge
    # ======================================================

    # 合并品类处理顺序：实体/角色先（无跨类引用依赖），
    # 再状态→条件→动作→结果（依赖已有 map），最后关系（依赖全部 map）。
    _CAT_ORDER = (
        "actors", "entities", "states",
        "conditions", "actions", "outcomes",
    )

    # 每个品类元素里"引用其它品类"的字段 → 指向的品类
    _REF_FIELDS = {
        "states": [("entity_id", "entities")],
        "conditions": [("related_entity", "entities"),
                       ("related_state", "states")],
        "actions": [("actor_id", "actors"),
                    ("target_entity", "entities")],
        "outcomes": [("entity_id", "entities")],
        "relations": [("condition_id", "conditions"),
                      ("action_id", "actions"),
                      ("outcome_id", "outcomes"),
                      ("from_state_id", "states"),
                      ("to_state_id", "states"),
                      ("source_entity", "entities"),
                      ("target_entity", "entities")],
    }

    def _merge(
        self,
        partials: List[Dict[str, Any]],
    ) -> Dict[str, Any]:

        merged: Dict[str, Any] = {
            "actors": [],
            "entities": [],
            "states": [],
            "conditions": [],
            "actions": [],
            "outcomes": [],
            "relations": [],
        }

        # 每个块自己的 id 映射：category -> {本块局部 id 或显示值 -> 全局 id}。
        # 必须按块隔离：不同块的局部 "E003" 指向不同实体，不能共用一张表。
        cats = list(self._CAT_ORDER)
        chunk_maps: List[Dict[str, Dict[str, str]]] = [
            {c: {} for c in cats} for _ in partials
        ]

        # ---------- 第一遍：实体/角色 => 状态 => 条件 => 动作 => 结果 ----------
        for cat in self._CAT_ORDER:

            seen: Dict[str, dict] = {}
            counter = [1]

            for idx, partial in enumerate(partials):
                cm = chunk_maps[idx]
                for it in partial.get(cat, []):
                    if not isinstance(it, dict):
                        continue

                    # 先把本元素引用的其它品类 id，从本块局部值重写为全局值
                    for fld, ref_cat in self._REF_FIELDS.get(cat, []):
                        v = it.get(fld)
                        if isinstance(v, str) and v:
                            it[fld] = cm[ref_cat].get(self._norm(v), v)

                    _, key = self._cat_key(cat, it)

                    if key in seen:
                        self._merge_source_facts(seen[key], it)
                        # 该局部 id 已被合并，指向保留元素的全局 id
                        cm[cat][self._norm(it.get("id"))] = seen[key]["id"]
                        continue

                    new_id = self._global_id(cat, counter[0])
                    counter[0] += 1
                    old_id = self._norm(it.get("id"))
                    it["id"] = new_id
                    seen[key] = it
                    cm[cat][old_id] = new_id
                    # 允许用显示值反查（entity name、content 等）
                    for val_name in ("name", "content"):
                        v = it.get(val_name)
                        if isinstance(v, str) and v:
                            cm[cat].setdefault(self._norm(v), new_id)
                    merged[cat].append(it)

        # ---------- 第二遍：relations（全部引用已可重写） ----------
        seen_rel: Dict[str, dict] = {}
        rel_counter = [1]

        for idx, partial in enumerate(partials):
            cm = chunk_maps[idx]
            for rel in partial.get("relations", []):
                if not isinstance(rel, dict):
                    continue

                for fld, ref_cat in self._REF_FIELDS["relations"]:
                    v = rel.get(fld)
                    if isinstance(v, str) and v:
                        rel[fld] = cm[ref_cat].get(self._norm(v), v)

                _, rel_key = self._cat_key("relations", rel)
                if rel_key in seen_rel:
                    self._merge_source_facts(seen_rel[rel_key], rel)
                    continue

                rel["id"] = self._global_id("relations", rel_counter[0])
                rel_counter[0] += 1
                seen_rel[rel_key] = rel
                merged["relations"].append(rel)

        return merged

    def _cat_key(self, cat: str, elem: dict) -> tuple:
        if cat in ("actors", "entities"):
            return ("name", self._norm(elem.get("name")))
        if cat in ("conditions", "actions", "outcomes"):
            return ("content", self._norm(elem.get("content")))
        if cat == "states":
            # 以(状态名, 所属实体全局id)去重，避免不同实体同名状态被误并
            return ("state", self._norm(elem.get("name"))
                    + "|@|" + self._norm(elem.get("entity_id")))
        # relations：以类型+所有引用的全局 id 去重
        parts = [self._norm(str(elem.get("type")))]
        for fld, _ in self._REF_FIELDS["relations"]:
            parts.append(self._norm(elem.get(fld)))
        return ("rel", "|@|".join(parts))

    @staticmethod
    def _norm(value) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _global_id(cat: str, n: int) -> str:
        prefix = {
            "actors": "A", "entities": "E", "states": "S",
            "conditions": "CN", "actions": "AC", "outcomes": "O",
            "relations": "REL",
        }[cat]
        return f"{prefix}{n:03d}"

    @staticmethod
    def _merge_source_facts(target: dict, source: dict) -> None:
        t = target.get("source_facts")
        s = source.get("source_facts")
        if not isinstance(t, list):
            return
        if not isinstance(s, list):
            return
        existing = set(t)
        for x in s:
            if x not in existing:
                existing.add(x)
                t.append(x)