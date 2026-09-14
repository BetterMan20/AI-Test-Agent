"""
agents/fact_extraction.py

Fact Extraction
===============

职责：
    从解析后的需求文本中提取事实。

核心原则：

    Parsed Text
            ↓
    Fact Extraction
            ↓
       Facts
            ↓
    Requirement Analysis

Fact Extraction 负责：
    - 提取需求中明确陈述的事实
    - 为每个事实分配唯一 ID

Fact Extraction 不负责：
    - 需求分析
    - Gap Detection
    - Test Design
    - Test Case 生成

稳定性设计（分块抽取）
---------------------------------------
大型需求整份交给 LLM 抽取，易因输出超出 token 上限被截断（finish_reason=length）
导致 JSON 不完整而解析失败。本实现按 markdown 章节把需求切成多个片段，
分别抽取后合并去重、统一重编号，使单次 LLM 输出远低于上限。

面向片段抽取时，会明确覆盖原 skill 中"少于 40 个 Fact 需重新遍历"的指令，
避免模型在小片段上为凑数量而杜撰 Fact。
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class FactExtraction:

    AGENT_NAME = "fact_extraction"
    STAGE_NAME = "Fact Extraction"

    SKILL_PATH = SKILLS["fact_extraction"]

    SCHEMA_PATH = (
        Path(__file__).resolve().parent.parent
        / "schema"
        / "requirement_fact.schema.json"
    )

    # 单个分块的最大字符数；超过则继续拆分，控制单次 LLM 输出规模。
    MAX_CHUNK_CHARS = 1200

    # 并行抽取的最大并发数。LLM API 单次调用为分钟级网络等待，
    # 分块彼此独立，用有限度并行把 Stage 2 墙钟时间压到≈单次调用。
    MAX_PARALLEL = 3

    _HEADING = re.compile(r"^#{2,4}\s")

    def run(self, parsed: Any) -> Dict[str, Any]:

        if not isinstance(parsed, str):
            raise ValueError(
                "FactExtraction requires parsed as str."
            )

        if not parsed.strip():
            raise ValueError(
                "FactExtraction requires non-empty parsed text."
            )

        chunks = self._build_chunks(
            parsed,
            self.MAX_CHUNK_CHARS,
        )

        if len(chunks) <= 1:
            return self._extract_single(parsed)

        return self._extract_chunked(chunks)

    # =========================================================
    # 单块抽取
    # =========================================================

    def _extract_single(self, parsed: str) -> Dict[str, Any]:

        result = SkillEngine.run(
            skill_path=self.SKILL_PATH,
            input_data=parsed,
            schema_path=str(self.SCHEMA_PATH),
            output_mode="json",
        )

        if not isinstance(result, dict):
            raise ValueError(
                "FactExtraction output must be a dict."
            )

        if not result:
            raise ValueError(
                "FactExtraction output is empty."
            )

        return result

    # =========================================================
    # 分块抽取：抽取 → 合并 → 去重 → 统一重编号
    # =========================================================

    def _extract_chunked(
        self,
        chunks: List[str],
    ) -> Dict[str, Any]:

        total = len(chunks)
        ordered: List[List[Dict[str, Any]]] = [
            [] for _ in chunks
        ]
        stats_list: List[Dict[str, Any]] = [
            {} for _ in chunks
        ]

        with ThreadPoolExecutor(
            max_workers=min(self.MAX_PARALLEL, total)
        ) as pool:

            future_map = {
                pool.submit(
                    self._extract_one_chunk,
                    chunk,
                    idx,
                    total,
                ): idx
                for idx, chunk in enumerate(chunks)
            }

            for future in as_completed(future_map):

                idx = future_map[future]
                facts, stats = future.result()
                ordered[idx] = facts
                stats_list[idx] = stats

        all_facts: List[Dict[str, Any]] = []
        for facts in ordered:
            all_facts.extend(facts)

        all_facts = self._dedup(all_facts)
        all_facts = self._renumber(all_facts)

        print(
            f"[FactExtraction] 并行分块完成：{total} 块 → "
            f"{len(all_facts)} 个去重 Fact "
            f"(并发≤{self.MAX_PARALLEL})"
        )

        self._print_perf(stats_list)

        # 保持与原单块输出结构完全一致，避免下游额外适配。
        return {"facts": all_facts}

    def _extract_one_chunk(
        self,
        chunk: str,
        idx: int,
        total: int,
    ) -> tuple:

        chunk_id = idx + 1

        print(
            f"[FactExtraction] 处理分块 {chunk_id}/{total} "
            f"(chars={len(chunk)})"
        )

        start_time = time.time()

        result, stats = SkillEngine.run(
            skill_path=self.SKILL_PATH,
            input_data=self._wrap_chunk(chunk, chunk_id, total),
            schema_path=str(self.SCHEMA_PATH),
            output_mode="json",
            collect_stats=True,
        )

        end_time = time.time()

        facts = (
            result.get("facts", [])
            if isinstance(result, dict)
            else []
        )

        if not isinstance(facts, list):
            facts = []

        stats = dict(stats or {})
        stats.update({
            "chunk_id": chunk_id,
            "start_time": start_time,
            "end_time": end_time,
            "duration": end_time - start_time,
        })

        return facts, stats

    @staticmethod
    def _print_perf(stats_list: List[Dict[str, Any]]) -> None:

        valid = [s for s in stats_list if s and s.get("duration")]

        if not valid:
            return

        total_s = sum(s["duration"] for s in valid)
        avg = total_s / len(valid)
        mx = max(s["duration"] for s in valid)
        retries = sum(s.get("retry_count", 0) for s in valid)

        print()
        print("=" * 45)
        print("Fact Extraction Performance")
        print("=" * 45)
        print(f"Chunks: {len(valid)}")
        print(f"LLM calls: {len(valid)}")
        print(f"Total: {total_s:.1f}s")
        print(f"Average: {avg:.1f}s")
        print(f"Max: {mx:.1f}s")
        print(f"Retry: {retries}")

        slowest = sorted(
            valid,
            key=lambda s: s["duration"],
            reverse=True,
        )[:3]
        print("Slowest:")
        for s in slowest:
            print(
                f"  chunk-{s['chunk_id']:02d}: "
                f"{s['duration']:.1f}s"
            )

        print("Per-chunk:")
        for s in sorted(valid, key=lambda s: s["chunk_id"]):
            print(
                f"  chunk-{s['chunk_id']:02d}: "
                f"{s['duration']:.1f}s | "
                f"in={s.get('input_tokens', 0)} "
                f"out={s.get('output_tokens', 0)} | "
                f"retry={s.get('retry_count', 0)}"
            )
        print("=" * 45)

    # =========================================================
    # Helpers
    # =========================================================

    @staticmethod
    def _wrap_chunk(
        chunk: str,
        idx: int,
        total: int,
    ) -> str:
        """
        面向片段抽取的用户提示，覆盖"少于40个Fact需重提"的整篇要求。
        """
        return (
            "以下是产品需求文档的第 {idx}/{total} 段（一个片段，非完整文档）。\n"
            "请只提取本段中明确存在的事实：不提取其它段落的内容；"
            "也不遗漏本段内任何细节。\n"
            "【重要】本段只是片段，实际事实数量可能远少于整篇文档的正常值；"
            "绝对不要为凑够数量而杜撰或脑补本段不存在的事实——"
            "你唯一的目标是把本段真实存在的内容全部、准确地提取出来。\n\n"
            "{body}"
        ).format(idx=idx, total=total, body=chunk)

    @classmethod
    def _build_chunks(
        cls,
        text: str,
        max_chars: int = MAX_CHUNK_CHARS,
    ) -> List[str]:

        # 1) 按 markdown 标题（H2/H3/H4）切成段落块（标题归属其后内容）
        blocks: List[str] = []
        cur: List[str] = []

        for line in text.splitlines():
            if cls._HEADING.match(line):
                if cur:
                    blocks.append("\n".join(cur))
                    cur = []
            cur.append(line)

        if cur:
            blocks.append("\n".join(cur))

        # 2) 超级块（单块超 max_chars）按行继续细分：
        #    原实现只在"块之间"按 max_chars 合拢，遇到某个不含二级标题的
        #    超大章节（如整片 H4 需求详情）会压成远超上限的单块，撑爆单次
        #    LLM 输出导致超时/截断。这里把每个超大块再按行裂成 ≤max_chars 的小块。
        fine_blocks: List[str] = []

        for block in blocks:
            if len(block) <= max_chars:
                fine_blocks.append(block)
                continue

            bucket: List[str] = []
            bucket_len = 0

            for line in block.splitlines():
                if bucket and bucket_len + len(line) + 1 > max_chars:
                    fine_blocks.append("\n".join(bucket))
                    bucket = []
                    bucket_len = 0
                bucket.append(line)
                bucket_len += len(line) + 1

            if bucket:
                fine_blocks.append("\n".join(bucket))

        blocks = fine_blocks

        # 3) 把段落块按字符数合拢成分块
        chunks: List[str] = []
        cur_chunk: List[str] = []
        cur_len = 0

        for block in blocks:
            if cur_chunk and cur_len + len(block) > max_chars:
                chunks.append("\n".join(cur_chunk))
                cur_chunk = []
                cur_len = 0
            cur_chunk.append(block)
            cur_len += len(block)

        if cur_chunk:
            chunks.append("\n".join(cur_chunk))

        return chunks

    @staticmethod
    def _dedup(
        facts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        seen = set()
        result: List[Dict[str, Any]] = []

        for fact in facts:
            if not isinstance(fact, dict):
                continue
            key = (fact.get("type"), fact.get("content"))
            if key in seen:
                continue
            seen.add(key)
            result.append(fact)

        return result

    @staticmethod
    def _renumber(
        facts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        result: List[Dict[str, Any]] = []

        for idx, fact in enumerate(facts, start=1):
            fresh = dict(fact)
            fresh["id"] = (
                f"F{idx:03d}"
                if idx < 1000
                else f"F{idx:04d}"
            )
            result.append(fresh)

        return result