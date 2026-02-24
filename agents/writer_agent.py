"""Writer Agent: core chapter creation with human-like writing style."""

import logging
import re
from typing import Optional

from agents.base_agent import BaseAgent
from config.settings import Settings
from tools.agent_sdk_client import AgentSDKClient
from tools.text_utils import count_chinese_chars

logger = logging.getLogger(__name__)

# Marker patterns for structured text output
_TITLE_RE = re.compile(r"【标题】\s*\n?(.*?)(?:\n\n|\n(?=【))", re.DOTALL)
_CONTENT_RE = re.compile(r"【正文】\s*\n(.*)", re.DOTALL)

# Maximum retry attempts for short output
_MAX_RETRIES = 2
# Writer minimum — editor handles the rest to reach chapter_min_chars
_WRITER_MIN_CHARS = 1500


def _parse_writer_output(text: str, chapter_number: int) -> dict:
    """Parse the writer's structured text output into title + content."""
    title = f"第{chapter_number}章"
    content = ""

    title_match = _TITLE_RE.search(text)
    if title_match:
        title = title_match.group(1).strip()

    content_match = _CONTENT_RE.search(text)
    if content_match:
        content = content_match.group(1).strip()
    elif "【标题】" in text:
        # Fallback: everything after the title section
        idx = text.find("【正文】")
        if idx != -1:
            content = text[idx + len("【正文】"):].strip()
    else:
        # No markers at all — treat entire response as content
        content = text.strip()

    return {"title": title, "content": content}


class WriterAgent(BaseAgent):
    """Generates chapter content with natural, human-like writing style."""

    def __init__(
        self,
        llm_client: Optional[AgentSDKClient] = None,
        settings: Optional[Settings] = None,
    ):
        super().__init__(llm_client, settings)
        self._template = self._load_prompt("writer")

    async def write_chapter(
        self,
        genre: str,
        style_guide: str,
        chapter_number: int,
        chapter_outline: str,
        context_prompt: str,
        previous_chapter_ending: str = "",
        emotional_tone: str = "",
        hook_type: str = "cliffhanger",
        target_chapters: int = 0,
    ) -> dict:
        """Write a single chapter.

        Args:
            genre: Novel genre.
            style_guide: Writing style guide from planner.
            chapter_number: Chapter number.
            chapter_outline: What should happen in this chapter.
            context_prompt: Memory context from MemoryRetriever.
            previous_chapter_ending: Last ~500 chars of previous chapter.
            emotional_tone: Target emotional tone.
            hook_type: Type of chapter-ending hook.

        Returns:
            Dict with keys: title, content, char_count.
        """
        system_prompt = self._extract_section(self._template, "System Prompt")
        system_prompt += "\n\n" + self._extract_section(self._template, "核心写作原则")
        system_prompt += "\n\n写作时请充分发挥创意，灵活运用修辞手法，避免模式化表达。"

        # Compute progress note so the writer knows when to wrap up the story
        progress_note = ""
        if target_chapters > 0:
            remaining = target_chapters - chapter_number
            if remaining <= 10:
                progress_note = (
                    f"\n**【重要收尾提示】全书共规划 {target_chapters} 章，当前为第 {chapter_number} 章，"
                    f"仅剩约 {remaining} 章。请开始快速收束所有主要矛盾与支线，推动故事走向圆满结局。**"
                )
            elif remaining <= 30:
                progress_note = (
                    f"\n**【进度提示】全书 {target_chapters} 章，当前第 {chapter_number} 章，"
                    f"已进入尾声阶段（剩余 {remaining} 章），请逐步收束各条支线情节。**"
                )

        user_section = self._extract_section(self._template, "创作指令")
        user_prompt = user_section.format(
            genre=genre,
            style_guide=style_guide or f"{genre}类网文标准风格",
            context_prompt=context_prompt or "（这是第一章，无前情提要）",
            previous_chapter_ending=previous_chapter_ending or "（这是第一章，无上一章内容）",
            chapter_outline=chapter_outline,
            emotional_tone=emotional_tone or "自然过渡",
            hook_type=hook_type,
            chapter_number=chapter_number,
            min_chars=self.settings.chapter_min_chars,
            max_chars=self.settings.chapter_max_chars,
            progress_note=progress_note,
        )

        logger.info(f"Writing chapter {chapter_number}...")

        raw_text = await self.llm.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.settings.llm_model_writing,
        )

        result = _parse_writer_output(raw_text, chapter_number)
        title = result["title"]
        content = result["content"]
        char_count = count_chinese_chars(content)

        # Retry if output is below the writer minimum threshold
        for attempt in range(_MAX_RETRIES):
            if char_count >= _WRITER_MIN_CHARS:
                break

            logger.warning(
                "Chapter %d too short: %d chars (need %d). Retry %d/%d",
                chapter_number, char_count, _WRITER_MIN_CHARS, attempt + 1, _MAX_RETRIES,
            )

            expand_prompt = (
                f"你刚才写的第{chapter_number}章只有{char_count}个中文字符，"
                f"远低于最低要求的{_WRITER_MIN_CHARS}字。\n\n"
                f"以下是你写的内容：\n{content}\n\n"
                f"请基于相同的大纲和设定，**重新创作完整的第{chapter_number}章**。"
                f"这次必须写到{_WRITER_MIN_CHARS}-{self.settings.chapter_max_chars}个中文字符。\n"
                f"要求：\n"
                f"- 丰富场景描写、角色对话、内心活动和感官细节\n"
                f"- 每个关键场景至少展开3-5段\n"
                f"- 对话要有来有回，穿插动作和神态描写\n"
                f"- 不要概括性叙述，要展示具体的过程和细节\n\n"
                f"请严格按以下格式输出：\n\n"
                f"【标题】\n章节标题\n\n【正文】\n章节正文内容"
            )

            raw_text = await self.llm.chat(
                system_prompt=system_prompt,
                user_prompt=expand_prompt,
                model=self.settings.llm_model_writing,
            )

            result = _parse_writer_output(raw_text, chapter_number)
            if result["title"] and result["title"] != f"第{chapter_number}章":
                title = result["title"]
            new_content = result["content"]
            new_count = count_chinese_chars(new_content)

            # Only accept if it's an improvement
            if new_count > char_count:
                content = new_content
                char_count = new_count
                logger.info(
                    "Chapter %d expanded to %d chars on retry %d",
                    chapter_number, char_count, attempt + 1,
                )

        logger.info(f"Chapter {chapter_number} written: '{title}', {char_count} chars")

        return {
            "title": title,
            "content": content,
            "char_count": char_count,
        }
