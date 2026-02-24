"""Chapter summarization using LLM."""

import logging
import re
from typing import Optional

from tools.agent_sdk_client import AgentSDKClient

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM_PROMPT = """你是一位小说内容分析专家。你的任务是为给定的章节生成精确的结构化摘要，用于后续章节的创作参考。

要求：
1. 摘要要准确概括章节的主要事件、角色行动和情感变化
2. 标注新出现的角色和世界设定
3. 标注伏笔、悬念等需要后续跟进的内容

请严格遵守以上要求，保持准确客观。"""

_SUMMARY_USER_TEMPLATE = """请分析以下章节内容并生成结构化摘要：

【第{chapter_number}章】
{chapter_content}

请严格按以下格式输出（每个标记必须独占一行）：

【摘要】
200-300字的章节摘要

【角色变化】
角色名: 状态变化描述
（每行一个角色，无角色变化则写"无"）

【情节事件】
事件类型|重要性|事件描述
（事件类型: foreshadow/climax/reveal/twist/setup/resolution）
（重要性: critical/major/normal/minor）
（每行一个事件，无事件则写"无"）

【新角色】
角色名|角色类型|描述
（角色类型: protagonist/antagonist/supporting/minor）
（每行一个角色，无新角色则写"无"）

【关键角色】
本章涉及的主要角色名，逗号分隔

【关键事件】
本章关键事件的简短标签，逗号分隔

【情感基调】
本章的情感基调"""

_GLOBAL_REVIEW_SYSTEM_PROMPT = (
    "你是一位资深小说编辑，负责对长篇小说进行阶段性全局回顾。"
    "你需要检查角色发展的一致性、情节线索的推进情况，并发现潜在的矛盾。"
    "请保持严谨客观的分析态度。"
)

_GLOBAL_REVIEW_USER_TEMPLATE = """请对以下小说的整体进展进行全局回顾：

【所有章节摘要】
{all_summaries}

【当前角色卡】
{character_cards}

【未解决的伏笔/悬念】
{unresolved_threads}

请严格按以下格式输出（每个标记必须独占一行）：

【故事进展】
当前故事进展总结（100-200字）

【角色发展】
角色名|当前状态|发展轨迹分析
（每行一个角色，无则写"无"）

【不一致之处】
严重程度|描述|修正建议
（严重程度: critical/minor）
（每行一个，无则写"无"）

【停滞伏笔】
起始章节|描述|推进建议
（每行一个，无则写"无"）"""


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"【([^】]+)】\s*\n")


def _extract_section(text: str, name: str) -> str:
    """Extract content between 【name】 and the next 【...】 or end of text."""
    pattern = re.compile(rf"【{re.escape(name)}】\s*\n(.*?)(?=\n【|$)", re.DOTALL)
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def _parse_pipe_lines(text: str, field_count: int) -> list[list[str]]:
    """Parse lines in 'a|b|c' format. Returns list of field lists."""
    results = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line == "无":
            continue
        parts = [p.strip() for p in line.split("|")]
        # Pad if missing fields
        while len(parts) < field_count:
            parts.append("")
        results.append(parts[:field_count])
    return results


def _parse_colon_lines(text: str) -> list[tuple[str, str]]:
    """Parse lines in 'key: value' format."""
    results = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line == "无":
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            results.append((k.strip(), v.strip()))
        elif "：" in line:
            k, v = line.split("：", 1)
            results.append((k.strip(), v.strip()))
    return results


def _parse_chapter_summary(text: str) -> dict:
    """Parse structured text output from summarize_chapter into a dict."""
    summary = _extract_section(text, "摘要")
    key_characters = _extract_section(text, "关键角色")
    key_events = _extract_section(text, "关键事件")
    emotional_tone = _extract_section(text, "情感基调")

    # Character updates
    char_section = _extract_section(text, "角色变化")
    character_updates = [
        {"name": name, "changes": changes}
        for name, changes in _parse_colon_lines(char_section)
    ]

    # Plot events
    event_section = _extract_section(text, "情节事件")
    plot_events = [
        {"event_type": parts[0], "importance": parts[1], "description": parts[2]}
        for parts in _parse_pipe_lines(event_section, 3)
    ]

    # New characters
    new_char_section = _extract_section(text, "新角色")
    new_characters = [
        {"name": parts[0], "role": parts[1], "description": parts[2]}
        for parts in _parse_pipe_lines(new_char_section, 3)
    ]

    return {
        "summary": summary,
        "character_updates": character_updates,
        "plot_events": plot_events,
        "new_characters": new_characters,
        "key_characters": key_characters,
        "key_events": key_events,
        "emotional_tone": emotional_tone,
    }


def _parse_global_review(text: str) -> dict:
    """Parse structured text output from generate_global_review into a dict."""
    story_progression = _extract_section(text, "故事进展")

    # Character arc updates
    char_section = _extract_section(text, "角色发展")
    character_arc_updates = [
        {"name": parts[0], "current_state": parts[1], "development_notes": parts[2]}
        for parts in _parse_pipe_lines(char_section, 3)
    ]

    # Inconsistencies
    incon_section = _extract_section(text, "不一致之处")
    inconsistencies = [
        {"severity": parts[0], "description": parts[1], "suggestion": parts[2]}
        for parts in _parse_pipe_lines(incon_section, 3)
    ]

    # Stale threads
    stale_section = _extract_section(text, "停滞伏笔")
    stale_threads = []
    for parts in _parse_pipe_lines(stale_section, 3):
        try:
            setup_ch = int(parts[0])
        except (ValueError, IndexError):
            setup_ch = 0
        stale_threads.append({
            "setup_chapter": setup_ch,
            "description": parts[1],
            "suggestion": parts[2],
        })

    return {
        "story_progression": story_progression,
        "character_arc_updates": character_arc_updates,
        "inconsistencies": inconsistencies,
        "stale_threads": stale_threads,
    }


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------

class Summarizer:
    """Generate chapter summaries and extract structured information."""

    def __init__(self, llm_client: AgentSDKClient):
        self.llm = llm_client

    async def summarize_chapter(self, chapter_number: int, chapter_content: str) -> dict:
        """Generate a structured summary for a chapter.

        Returns:
            Dict with keys: summary, character_updates, plot_events,
            new_characters, key_characters, key_events, emotional_tone
        """
        user_prompt = _SUMMARY_USER_TEMPLATE.format(
            chapter_number=chapter_number,
            chapter_content=chapter_content,
        )

        raw_text = await self.llm.chat(
            system_prompt=_SUMMARY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=self.llm.settings.llm_model_editing,
        )

        result = _parse_chapter_summary(raw_text)
        logger.info(
            "Chapter %d summary: %d chars, %d char_updates, %d events",
            chapter_number,
            len(result["summary"]),
            len(result["character_updates"]),
            len(result["plot_events"]),
        )
        return result

    async def generate_global_review(
        self,
        all_summaries: str,
        character_cards: str,
        unresolved_threads: str,
    ) -> dict:
        """Generate a global review of the novel's progress.

        Called every 5 chapters to maintain long-term consistency.
        """
        user_prompt = _GLOBAL_REVIEW_USER_TEMPLATE.format(
            all_summaries=all_summaries,
            character_cards=character_cards,
            unresolved_threads=unresolved_threads,
        )

        raw_text = await self.llm.chat(
            system_prompt=_GLOBAL_REVIEW_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=self.llm.settings.llm_model_writing,
        )

        result = _parse_global_review(raw_text)
        logger.info(
            "Global review: %d arc_updates, %d inconsistencies, %d stale_threads",
            len(result["character_arc_updates"]),
            len(result["inconsistencies"]),
            len(result["stale_threads"]),
        )
        return result
