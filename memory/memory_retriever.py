"""Memory retrieval and context assembly for chapter writing."""

import json
import logging
from typing import Optional

from config.settings import Settings
from memory.chroma_store import ChromaStore
from models.database import Database

logger = logging.getLogger(__name__)


class MemoryRetriever:
    """Assembles context from memory for the Writer agent.

    Combines recent chapter summaries, semantically relevant earlier chapters,
    character states, unresolved plot threads, and world settings into a
    structured context prompt.
    """

    def __init__(self, db: Database, chroma: ChromaStore, settings: Optional[Settings] = None):
        self.db = db
        self.chroma = chroma
        self.settings = settings or Settings()

    def assemble_context(
        self,
        novel_id: int,
        current_chapter_number: int,
        chapter_outline: str,
    ) -> str:
        """Assemble the full memory context for writing the next chapter.

        Args:
            novel_id: The novel being written.
            current_chapter_number: The chapter about to be written.
            chapter_outline: The outline for the current chapter.

        Returns:
            Formatted context string, capped at context_max_chars.
        """
        sections = []

        # 1. Recent chapter summaries (last 3)
        recent = self.chroma.get_recent_summaries(
            novel_id, current_chapter_number, count=3
        )
        if recent:
            lines = ["【近期章节回顾】"]
            for item in recent:
                lines.append(f"第{item['chapter_number']}章：{item['summary']}")
            sections.append("\n".join(lines))

        # 2. Semantically relevant earlier summaries
        exclude_chapters = [item["chapter_number"] for item in recent]
        exclude_chapters.append(current_chapter_number)

        relevant = self.chroma.search_relevant_summaries(
            novel_id=novel_id,
            query=chapter_outline,
            exclude_chapters=exclude_chapters,
            top_k=7,
        )
        if relevant:
            lines = ["【相关前文回顾】"]
            # Sort by chapter number for readability
            relevant.sort(key=lambda x: x["chapter_number"])
            for item in relevant:
                lines.append(f"第{item['chapter_number']}章：{item['summary']}")
            sections.append("\n".join(lines))

        # 3. Active character states
        characters = self.db.get_characters(novel_id)
        if characters:
            lines = ["【主要角色状态】"]
            for char in characters:
                if char.status.value != "active":
                    continue
                # Get latest state from ChromaDB
                state = self.chroma.get_latest_character_state(novel_id, char.name)
                state_text = state["state"] if state else "初始状态"
                role_label = {"protagonist": "主角", "antagonist": "反派",
                              "supporting": "配角", "minor": "路人"}.get(char.role.value, "")
                lines.append(f"- {char.name}（{role_label}）：{char.description[:100]}。当前：{state_text[:100]}")
            sections.append("\n".join(lines))

        # 4. Unresolved plot threads
        events = self.db.get_unresolved_events(novel_id)
        if events:
            lines = ["【未解决的伏笔/悬念】"]
            for event in events:
                importance_label = {"critical": "关键", "major": "重要",
                                    "normal": "普通", "minor": "次要"}.get(event.importance.value, "")
                lines.append(
                    f"- [{importance_label}] {event.description}（第{event.chapter_number}章埋下）"
                )
            sections.append("\n".join(lines))

        # 5. Relevant world settings
        world_settings = self.db.get_world_settings(novel_id)
        if world_settings:
            lines = ["【世界观设定】"]
            for ws in world_settings[:10]:  # Limit to avoid overflowing context
                lines.append(f"- {ws.name}：{ws.description[:80]}")
            sections.append("\n".join(lines))

        # Combine and trim to context limit
        full_context = "\n\n".join(sections)

        max_chars = self.settings.context_max_chars
        if len(full_context) > max_chars:
            # Trim relevant summaries first, keep recent and character info
            full_context = self._trim_context(sections, max_chars)

        return full_context

    def _trim_context(self, sections: list[str], max_chars: int) -> str:
        """Trim context to fit within max_chars, prioritizing recent info."""
        # Priority order: recent summaries > characters > plot threads > relevant summaries > world settings
        result = ""
        for section in sections:
            if len(result) + len(section) + 2 <= max_chars:
                result += section + "\n\n"
            else:
                # Add as much of this section as fits
                remaining = max_chars - len(result)
                if remaining > 50:
                    result += section[:remaining - 3] + "..."
                break
        return result.strip()

    def get_previous_chapter_ending(
        self, novel_id: int, current_chapter_number: int, char_limit: int = 500
    ) -> str:
        """Get the ending of the previous chapter for continuity.

        Falls back to the most recent written chapter if the immediately
        preceding chapter has no content (supports non-consecutive writing).
        """
        if current_chapter_number <= 1:
            return ""

        # Try the immediately preceding chapter first
        prev_chapter = self.db.get_chapter(novel_id, current_chapter_number - 1)
        if prev_chapter and prev_chapter.content:
            content = prev_chapter.content
            if len(content) <= char_limit:
                return content
            return content[-char_limit:]

        # Fallback: find the most recent chapter with content before current
        all_chapters = self.db.get_chapters(novel_id)
        earlier = [
            ch for ch in all_chapters
            if ch.chapter_number < current_chapter_number and ch.content
        ]
        if earlier:
            prev = max(earlier, key=lambda ch: ch.chapter_number)
            content = prev.content
            if len(content) <= char_limit:
                return content
            return content[-char_limit:]

        return ""
