"""Short Story Editor Agent: polishes short stories and adjusts word count."""

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


class ShortStoryEditorAgent(BaseAgent):
    """Polishes short story content and adjusts character count."""

    def __init__(
        self,
        llm_client: Optional[AgentSDKClient] = None,
        settings: Optional[Settings] = None,
    ):
        super().__init__(llm_client, settings)
        self._template = self._load_prompt("short_story_editor")

    async def edit(
        self,
        content: str,
        char_count: int,
        review_issues: str = "",
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Edit a short story for quality and polish.

        Args:
            content: The draft short story text.
            char_count: Current Chinese character count.
            review_issues: Optional formatted string of review issues to address.
            on_event: Optional callback for progress events.

        Returns:
            Dict with keys: content, char_count, edit_notes.
        """
        system_prompt = self._extract_section(self._template, "System Prompt")
        edit_rules = self._extract_section(self._template, "编辑指令")

        target_min = int(char_count * 0.85)
        target_max = int(char_count * 1.15)

        user_prompt = self._safe_format(
            edit_rules,
            story_title="",
            chapter_info="单章短篇",
            content=content,
            char_count=char_count,
            target_min=target_min,
            target_max=target_max,
            story_plan="（参见上文内容）",
            previous_content="（无）",
        )

        # Add reviewer feedback if available
        if review_issues:
            user_prompt += f"\n\n**审核反馈（请重点修改）：**\n{review_issues}"

        logger.info(
            "ShortStoryEditorAgent: editing story (%d chars)...",
            char_count,
        )

        # Use plain text output (not JSON) to avoid truncation/escaping issues
        raw_text = await self.llm.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.settings.llm_model_editing,
            on_event=on_event,
        )

        result = _parse_editor_output(raw_text, content)
        edited_content = result["content"]
        new_count = count_chinese_chars(edited_content)
        edit_notes = result["edit_notes"]

        logger.info(
            "ShortStoryEditorAgent: editing complete — %d -> %d chars. Notes: %s",
            char_count, new_count, edit_notes[:100],
        )

        return {
            "content": edited_content,
            "char_count": new_count,
            "edit_notes": edit_notes,
        }
