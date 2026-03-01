"""Short Story Writer Agent: generates complete short story content."""

import logging
import re
from typing import Callable, Optional

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


def _parse_writer_output(text: str) -> dict:
    """Parse the writer's structured text output into title + content."""
    title = "未命名短篇"
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


class ShortStoryWriterAgent(BaseAgent):
    """Generates complete short story content with natural, human-like writing style."""

    def __init__(
        self,
        llm_client: Optional[AgentSDKClient] = None,
        settings: Optional[Settings] = None,
    ):
        super().__init__(llm_client, settings)
        self._template = self._load_prompt("short_story_writer")

    async def write(
        self,
        genre: str,
        style_guide: str,
        plot_outline: str,
        characters: str,
        target_chars: int = 10000,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Write a complete short story.

        Args:
            genre: Story genre.
            style_guide: Writing style guide from planner.
            plot_outline: Plot outline for the story.
            characters: Character descriptions.
            target_chars: Target Chinese character count.
            on_event: Optional callback for progress events.

        Returns:
            Dict with keys: title, content, char_count.
        """
        system_prompt = self._extract_section(self._template, "System Prompt")
        user_section = self._extract_section(self._template, "创作指令")

        # Build story_plan from plot_outline + characters
        story_plan = ""
        if plot_outline:
            story_plan += f"**情节大纲：**\n{plot_outline}\n\n"
        if characters:
            story_plan += f"**角色设定：**\n{characters}"

        user_prompt = self._safe_format(
            user_section,
            genre=genre,
            style_guide=style_guide or f"{genre}类短篇小说标准风格",
            story_plan=story_plan or "（无详细规划，请根据类型和风格自由创作）",
            chapter_number=1,
            total_chapters=1,
            chapter_outline="单章短篇，完整创作",
            emotional_tone="根据故事内容自然展开",
            previous_content="（无，这是第一章/单章短篇）",
            writing_notes="请确保故事完整，有开头、发展、高潮和结尾。",
            min_chars=int(target_chars * 0.8),
            max_chars=int(target_chars * 1.2),
            chapter_title="",
        )

        logger.info(
            "ShortStoryWriterAgent: writing '%s' story (target %d chars)",
            genre, target_chars,
        )

        raw_text = await self.llm.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.settings.llm_model_writing,
            on_event=on_event,
        )

        result = _parse_writer_output(raw_text)
        title = result["title"]
        content = result["content"]
        char_count = count_chinese_chars(content)

        # Retry if output is below 50% of target
        min_acceptable = int(target_chars * 0.5)
        for attempt in range(_MAX_RETRIES):
            if char_count >= min_acceptable:
                break

            logger.warning(
                "Short story too short: %d chars (need %d). Retry %d/%d",
                char_count, min_acceptable, attempt + 1, _MAX_RETRIES,
            )

            expand_prompt = (
                f"你刚才写的短篇小说只有{char_count}个中文字符，"
                f"远低于最低要求的{min_acceptable}字（目标{target_chars}字）。\n\n"
                f"以下是你写的内容：\n{content}\n\n"
                f"请基于相同的大纲和设定，**重新创作完整的短篇小说**。"
                f"这次必须写到{min_acceptable}-{int(target_chars * 1.2)}个中文字符。\n"
                f"要求：\n"
                f"- 丰富场景描写、角色对话、内心活动和感官细节\n"
                f"- 每个关键场景至少展开3-5段\n"
                f"- 对话要有来有回，穿插动作和神态描写\n"
                f"- 不要概括性叙述，要展示具体的过程和细节\n\n"
                f"请严格按以下格式输出：\n\n"
                f"【标题】\n故事标题\n\n【正文】\n故事正文内容"
            )

            raw_text = await self.llm.chat(
                system_prompt=system_prompt,
                user_prompt=expand_prompt,
                model=self.settings.llm_model_writing,
                on_event=on_event,
            )

            result = _parse_writer_output(raw_text)
            if result["title"] and result["title"] != "未命名短篇":
                title = result["title"]
            new_content = result["content"]
            new_count = count_chinese_chars(new_content)

            # Only accept if it's an improvement
            if new_count > char_count:
                content = new_content
                char_count = new_count
                logger.info(
                    "Short story expanded to %d chars on retry %d",
                    char_count, attempt + 1,
                )

        logger.info(
            "ShortStoryWriterAgent: story written — '%s', %d chars",
            title, char_count,
        )

        return {
            "title": title,
            "content": content,
            "char_count": char_count,
        }
