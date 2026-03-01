"""Editor Agent: polishes chapters and adjusts word count."""

import logging
import re
from typing import Callable, Optional

from agents.base_agent import BaseAgent
from config.settings import Settings
from tools.agent_sdk_client import AgentSDKClient
from tools.text_utils import count_chinese_chars

logger = logging.getLogger(__name__)

# Marker patterns for structured text output
_TITLE_RE = re.compile(r"【标题】\s*\n?(.*?)(?=\n【编辑说明】)", re.DOTALL)
_NOTES_RE = re.compile(r"【编辑说明】\s*\n?(.*?)(?=\n【正文】)", re.DOTALL)
_CONTENT_RE = re.compile(r"【正文】\s*\n(.*)", re.DOTALL)


def _parse_editor_output(text: str, original_content: str) -> dict:
    """Parse the editor's structured text output into title + content + edit_notes."""
    content = ""
    edit_notes = ""
    new_title = ""

    title_match = _TITLE_RE.search(text)
    if title_match:
        raw_title = title_match.group(1).strip()
        # Extract just the title (before any parenthetical explanation)
        paren_idx = raw_title.find("（")
        if paren_idx > 0:
            new_title = raw_title[:paren_idx].strip()
        else:
            new_title = raw_title

    notes_match = _NOTES_RE.search(text)
    if notes_match:
        edit_notes = notes_match.group(1).strip()

    content_match = _CONTENT_RE.search(text)
    if content_match:
        content = content_match.group(1).strip()
    else:
        # No markers — treat entire response as content
        content = text.strip()

    # If parsed content is too short, fall back to original
    if count_chinese_chars(content) < 50 and count_chinese_chars(original_content) > 50:
        logger.warning("Edited content too short, keeping original")
        content = original_content
        edit_notes = edit_notes or "编辑输出异常，保留原文"

    return {"content": content, "edit_notes": edit_notes, "new_title": new_title}


class EditorAgent(BaseAgent):
    """Polishes chapter content and adjusts character count to target range."""

    def __init__(
        self,
        llm_client: Optional[AgentSDKClient] = None,
        settings: Optional[Settings] = None,
    ):
        super().__init__(llm_client, settings)
        self._template = self._load_prompt("editor")

    async def edit_chapter(
        self,
        chapter_content: str,
        chapter_outline: str,
        char_count: int,
        review_issues: Optional[list[dict]] = None,
        chapter_title: str = "",
        chapter_number: int = 0,
        existing_titles: str = "",
        previous_ending: str = "",
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Edit a chapter for quality and word count compliance.

        Args:
            chapter_content: The draft chapter text.
            chapter_outline: Original outline for reference.
            char_count: Current Chinese character count.
            review_issues: Optional list of issues from the Reviewer to address.
            chapter_title: Current chapter title (for title quality check).
            chapter_number: Chapter number (for title format check).
            existing_titles: Newline-separated list of existing titles (for dedup check).
            previous_ending: The ending text of the previous chapter for coherence fixes.

        Returns:
            Dict with keys: content, char_count, edit_notes, new_title.
        """
        system_prompt = self._extract_section(self._template, "System Prompt")
        edit_rules = self._extract_section(self._template, "编辑指令")

        user_prompt = edit_rules.format(
            chapter_content=chapter_content,
            char_count=char_count,
            target_min=self.settings.chapter_min_chars,
            target_max=self.settings.chapter_max_chars,
            chapter_outline=chapter_outline,
            chapter_title=chapter_title or "（未提供）",
            chapter_number=chapter_number,
            existing_titles=existing_titles or "（无已有标题）",
            previous_ending=previous_ending or "（无上一章结尾——本章为第一章）",
        )

        # If content is under target, add forceful expansion instructions
        if char_count < self.settings.chapter_min_chars:
            deficit = self.settings.chapter_min_chars - char_count
            user_prompt += (
                f"\n\n**【重要：字数严重不足】**\n"
                f"当前仅{char_count}字，距目标最少{self.settings.chapter_min_chars}字"
                f"还差约{deficit}字。请务必大幅扩写：\n"
                f"- 在每个关键对话和事件后，补充角色的内心反应和心理活动\n"
                f"- 展开角色做决定时的心理博弈（犹豫、权衡、下定决心的过程）\n"
                f"- 对话之间穿插角色的心声和情感波动\n"
                f"- 适当添加回忆或联想来丰富人物情感层次\n"
                f"- 环境描写只用1-2句点明氛围，不要大段堆砌\n"
                f"- 最终输出必须达到{self.settings.chapter_min_chars}字以上"
            )

        # Add reviewer feedback if available
        if review_issues:
            issues_text = "\n".join(
                f"- [{issue.get('severity', 'minor')}] {issue.get('category', '')}: "
                f"{issue.get('description', '')} → {issue.get('suggestion', '')}"
                for issue in review_issues
            )
            user_prompt += f"\n\n**审核反馈（请重点修改）：**\n{issues_text}"

            # Check for coherence issues specifically — provide previous chapter ending
            coherence_categories = {"连贯性", "coherence", "consistency", "逻辑一致性"}
            has_coherence_issues = any(
                any(cc in issue.get("category", "").lower() for cc in coherence_categories)
                for issue in review_issues
            )
            if has_coherence_issues and previous_ending:
                user_prompt += (
                    f"\n\n**【连贯性修复——上一章结尾原文】**\n"
                    f"审核发现了连贯性问题，以下是上一章的最后部分，"
                    f"请根据此内容重写本章开头，确保自然衔接：\n"
                    f"---\n{previous_ending}\n---\n"
                    f"修复要求：\n"
                    f"1. 本章开头必须承接上一章的场景、情绪和对话\n"
                    f"2. 角色的位置、状态、情绪必须与上一章结尾一致\n"
                    f"3. 时间线必须连续，不能有突兀的跳跃\n"
                    f"4. 如果上一章结尾是对话中断或紧张场景，本章必须延续而非跳过\n"
                )
        elif previous_ending:
            # Even without review issues, provide previous ending for first-pass coherence
            user_prompt += (
                f"\n\n**【上一章结尾参考】**\n"
                f"请确保本章开头与上一章结尾自然衔接：\n"
                f"---\n{previous_ending}\n---\n"
            )

        logger.info(
            f"Editing chapter ({char_count} chars, "
            f"target {self.settings.chapter_min_chars}-{self.settings.chapter_max_chars})..."
        )

        # Use plain text output (not JSON) to avoid truncation/escaping issues
        raw_text = await self.llm.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.settings.llm_model_editing,
            on_event=on_event,
        )

        result = _parse_editor_output(raw_text, chapter_content)
        content = result["content"]
        new_count = count_chinese_chars(content)
        edit_notes = result["edit_notes"]
        new_title = result.get("new_title", "")

        logger.info(f"Editing complete: {char_count} → {new_count} chars. Notes: {edit_notes[:100]}")
        if new_title and new_title != chapter_title:
            logger.info(f"Title changed: '{chapter_title}' → '{new_title}'")

        return {
            "content": content,
            "char_count": new_count,
            "edit_notes": edit_notes,
            "new_title": new_title,
        }
