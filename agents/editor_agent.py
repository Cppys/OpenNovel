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
_NOTES_RE = re.compile(r"【编辑说明】\s*\n?(.*?)(?=\n【正文】)", re.DOTALL)
_CONTENT_RE = re.compile(r"【正文】\s*\n(.*)", re.DOTALL)


def _parse_editor_output(text: str, original_content: str) -> dict:
    """Parse the editor's structured text output into content + edit_notes."""
    content = ""
    edit_notes = ""

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

    return {"content": content, "edit_notes": edit_notes}


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
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Edit a chapter for quality and word count compliance.

        Args:
            chapter_content: The draft chapter text.
            chapter_outline: Original outline for reference.
            char_count: Current Chinese character count.
            review_issues: Optional list of issues from the Reviewer to address.

        Returns:
            Dict with keys: content, char_count, edit_notes.
        """
        system_prompt = self._extract_section(self._template, "System Prompt")
        edit_rules = self._extract_section(self._template, "编辑指令")

        user_prompt = edit_rules.format(
            chapter_content=chapter_content,
            char_count=char_count,
            target_min=self.settings.chapter_min_chars,
            target_max=self.settings.chapter_max_chars,
            chapter_outline=chapter_outline,
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

        logger.info(f"Editing complete: {char_count} → {new_count} chars. Notes: {edit_notes[:100]}")

        return {
            "content": content,
            "char_count": new_count,
            "edit_notes": edit_notes,
        }
