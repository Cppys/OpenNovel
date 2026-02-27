"""Memory Manager Agent: maintains novel state and generates context."""

import json
import logging
from typing import Optional

from agents.base_agent import BaseAgent
from config.settings import Settings
from memory.chroma_store import ChromaStore
from memory.memory_retriever import MemoryRetriever
from memory.summarizer import Summarizer
from models.database import Database
from models.character import Character, PlotEvent, WorldSetting
from models.enums import CharacterRole, CharacterStatus, EventType, EventImportance
from tools.agent_sdk_client import AgentSDKClient

logger = logging.getLogger(__name__)


class MemoryManagerAgent(BaseAgent):
    """Manages novel memory: context retrieval, summary generation, and state updates."""

    def __init__(
        self,
        db: Database,
        chroma: ChromaStore,
        llm_client: Optional[AgentSDKClient] = None,
        settings: Optional[Settings] = None,
    ):
        super().__init__(llm_client, settings)
        self.db = db
        self.chroma = chroma
        self.retriever = MemoryRetriever(db, chroma, self.settings)
        self.summarizer = Summarizer(self.llm)

    def retrieve_context(
        self, novel_id: int, chapter_number: int, chapter_outline: str
    ) -> str:
        """Retrieve memory context for writing a new chapter.

        Returns a formatted context string for the Writer agent.
        """
        return self.retriever.assemble_context(novel_id, chapter_number, chapter_outline)

    def get_previous_ending(self, novel_id: int, chapter_number: int) -> str:
        """Get the ending of the previous chapter."""
        return self.retriever.get_previous_chapter_ending(novel_id, chapter_number)

    async def update_memory(
        self, novel_id: int, chapter_number: int, chapter_content: str
    ) -> dict:
        """Update memory after a chapter is written.

        Generates summary, extracts character updates and plot events,
        stores everything in ChromaDB and SQLite.

        Returns:
            Summary data dict from the Summarizer.
        """
        logger.info(f"Updating memory for novel {novel_id}, chapter {chapter_number}...")

        # Generate structured summary
        summary_data = await self.summarizer.summarize_chapter(chapter_number, chapter_content)

        # Store chapter summary in ChromaDB
        self.chroma.add_chapter_summary(
            novel_id=novel_id,
            chapter_number=chapter_number,
            summary=summary_data.get("summary", ""),
            key_characters=summary_data.get("key_characters", ""),
            key_events=summary_data.get("key_events", ""),
            emotional_tone=summary_data.get("emotional_tone", ""),
        )

        # Process character updates
        for char_update in summary_data.get("character_updates", []):
            name = char_update.get("name", "")
            changes = char_update.get("changes", "")
            if name and changes:
                self.chroma.add_character_state(
                    novel_id=novel_id,
                    character_name=name,
                    chapter_number=chapter_number,
                    state_description=changes,
                )

        # Process new characters
        new_characters_list = summary_data.get("new_characters", [])
        if new_characters_list:
            existing_names = {c.name for c in self.db.get_characters(novel_id)}
            for new_char in new_characters_list:
                name = new_char.get("name", "")
                if not name or name in existing_names:
                    continue
                role_str = new_char.get("role", "minor")
                try:
                    role = CharacterRole(role_str)
                except ValueError:
                    role = CharacterRole.MINOR
                character = Character(
                    novel_id=novel_id,
                    name=name,
                    role=role,
                    description=new_char.get("description", ""),
                    first_appearance=chapter_number,
                )
                self.db.create_character(character)
                existing_names.add(name)
                logger.info(f"New character discovered: {name}")

        # Process plot events
        for event_data in summary_data.get("plot_events", []):
            event_type_str = event_data.get("event_type", "setup")
            try:
                event_type = EventType(event_type_str)
            except ValueError:
                event_type = EventType.SETUP
            importance_str = event_data.get("importance", "normal")
            try:
                importance = EventImportance(importance_str)
            except ValueError:
                importance = EventImportance.NORMAL
            event = PlotEvent(
                novel_id=novel_id,
                chapter_number=chapter_number,
                event_type=event_type,
                description=event_data.get("description", ""),
                importance=importance,
            )
            self.db.create_plot_event(event)

        logger.info(
            f"Memory updated: summary stored, "
            f"{len(summary_data.get('character_updates', []))} char updates, "
            f"{len(summary_data.get('plot_events', []))} plot events"
        )

        return summary_data

    async def global_review(self, novel_id: int) -> dict:
        """Perform a global review of the novel's consistency.

        Called every N chapters (configured by global_review_interval).
        """
        logger.info(f"Performing global review for novel {novel_id}...")

        # Gather all summaries
        all_summaries = self.chroma.get_all_summaries(novel_id)
        summaries_text = "\n".join(
            f"第{s['chapter_number']}章：{s['summary']}"
            for s in all_summaries
        )

        # Gather character cards
        characters = self.db.get_characters(novel_id)
        chars_text = "\n".join(
            f"- {c.name}（{c.role.value}）：{c.description}"
            for c in characters
        )

        # Gather unresolved threads
        events = self.db.get_unresolved_events(novel_id)
        threads_text = "\n".join(
            f"- [{e.importance.value}] {e.description}（第{e.chapter_number}章）"
            for e in events
        )

        review_data = await self.summarizer.generate_global_review(
            all_summaries=summaries_text or "（暂无摘要）",
            character_cards=chars_text or "（暂无角色）",
            unresolved_threads=threads_text or "（暂无未解决的伏笔）",
        )

        # Update character descriptions based on review
        for arc_update in review_data.get("character_arc_updates", []):
            name = arc_update.get("name", "")
            for char in characters:
                if char.name == name:
                    notes = arc_update.get("development_notes", "")
                    if notes:
                        char.notes = notes
                        self.db.update_character(char)
                    break

        logger.info(
            f"Global review complete: "
            f"{len(review_data.get('inconsistencies', []))} inconsistencies, "
            f"{len(review_data.get('stale_threads', []))} stale threads"
        )

        return review_data
