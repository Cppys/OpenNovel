"""Conflict Design Agent: designs per-chapter conflicts, scenes, emotional tone, and hooks."""

import logging
from typing import Optional

from agents.base_agent import BaseAgent
from agents.planner_agent import (
    _VOLUME_RE,
    _CHAPTER_RE,
    _parse_chapter_block,
)
from config.settings import Settings
from tools.agent_sdk_client import AgentSDKClient

logger = logging.getLogger(__name__)


class ConflictDesignAgent(BaseAgent):
    """Designs per-chapter conflicts, key scenes, emotional tone, and hooks."""

    def __init__(
        self,
        llm_client: Optional[AgentSDKClient] = None,
        settings: Optional[Settings] = None,
    ):
        super().__init__(llm_client, settings)
        self._template = self._load_prompt("conflict_design")

    async def design(
        self,
        genre: str,
        target_chapters: int,
        architecture: dict,
        genre_research: dict,
    ) -> dict:
        """Design per-chapter conflict and scenes.

        Args:
            genre: Novel genre.
            target_chapters: Total target chapter count.
            architecture: Output from StoryArchitectAgent.
            genre_research: Output from GenreResearchAgent.

        Returns:
            Dict with key 'volumes': list of volume dicts, each containing
            chapters with outline, key_scenes, characters_involved,
            emotional_tone, hook_type.
        """
        system_prompt = self._extract_section(self._template, "System Prompt")
        user_prompt = self._extract_section(self._template, "冲突设计指令")
        user_prompt = user_prompt.replace("{genre}", genre)
        user_prompt = user_prompt.replace("{target_chapters}", str(target_chapters))

        # Format architecture as readable text
        arch_text = self._format_architecture(architecture)
        user_prompt = user_prompt.replace("{story_architecture}", arch_text)

        # Format genre brief
        genre_brief = self._format_genre_brief(genre_research)
        user_prompt = user_prompt.replace("{genre_brief}", genre_brief)

        # Fill volume placeholders from architecture
        volumes = architecture.get("volumes", [])
        if volumes:
            vol1 = volumes[0]
            user_prompt = user_prompt.replace("{vol1_title}", vol1.get("title", ""))
            user_prompt = user_prompt.replace("{vol1_synopsis}", vol1.get("synopsis", ""))

        logger.info("ConflictDesignAgent: designing %d chapters", target_chapters)

        raw_text = await self.llm.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.settings.llm_model_planning,
        )

        result = self._parse_chapters(raw_text, architecture)

        total_chapters = sum(
            len(v.get("chapters", [])) for v in result.get("volumes", [])
        )
        logger.info("ConflictDesignAgent: completed — %d chapters designed", total_chapters)
        return result

    @staticmethod
    def _format_architecture(arch: dict) -> str:
        """Format architecture dict into readable text for the prompt."""
        lines = []
        lines.append(f"书名: {arch.get('title', '')}")
        lines.append(f"简介: {arch.get('synopsis', '')}")
        lines.append(f"风格: {arch.get('style_guide', '')}")

        lines.append("\n角色体系:")
        for c in arch.get("characters", []):
            lines.append(
                f"  - {c['name']}（{c['role']}）: {c.get('description', '')} "
                f"| 背景: {c.get('background', '')} | 弧线: {c.get('arc', '')}"
            )

        lines.append("\n世界设定:")
        for ws in arch.get("world_settings", []):
            lines.append(f"  - [{ws['category']}] {ws['name']}: {ws['description']}")

        lines.append("\n卷结构:")
        for v in arch.get("volumes", []):
            lines.append(f"  第{v['volume_number']}卷 {v['title']}: {v.get('synopsis', '')}")

        backbone = arch.get("plot_backbone", "")
        if backbone:
            lines.append(f"\n主线骨架:\n{backbone}")

        return "\n".join(lines)

    @staticmethod
    def _format_genre_brief(research: dict) -> str:
        """Format a condensed genre brief for the conflict designer."""
        parts = []
        conventions = research.get("genre_conventions", "")
        if conventions:
            parts.append(f"核心套路: {conventions[:200]}")
        pacing = research.get("pacing_guidelines", "")
        if pacing:
            parts.append(f"节奏建议: {pacing[:200]}")
        golden = research.get("golden_three_strategy", "")
        if golden:
            parts.append(f"黄金三章: {golden[:200]}")
        return "\n".join(parts)

    @staticmethod
    def _parse_chapters(text: str, architecture: dict) -> dict:
        """Parse the conflict designer's output into structured volume/chapter data."""
        volumes = []
        vol_matches = list(_VOLUME_RE.finditer(text))

        # Fall back to architecture volumes for metadata
        arch_volumes = {
            v["volume_number"]: v for v in architecture.get("volumes", [])
        }

        for i, vol_match in enumerate(vol_matches):
            vol_num = int(vol_match.group(1))
            vol_title = vol_match.group(2).strip()

            start = vol_match.end()
            end = vol_matches[i + 1].start() if i + 1 < len(vol_matches) else len(text)
            vol_text = text[start:end]

            # Extract volume synopsis (text before first ===第N章===)
            first_ch = _CHAPTER_RE.search(vol_text)
            vol_synopsis = vol_text[:first_ch.start()].strip() if first_ch else vol_text.strip()

            # Use architecture synopsis if conflict output doesn't have one
            if not vol_synopsis and vol_num in arch_volumes:
                vol_synopsis = arch_volumes[vol_num].get("synopsis", "")

            # Parse chapters
            ch_matches = list(_CHAPTER_RE.finditer(vol_text))
            chapters = []
            for j, ch_match in enumerate(ch_matches):
                ch_num = int(ch_match.group(1))
                ch_start = ch_match.end()
                ch_end = ch_matches[j + 1].start() if j + 1 < len(ch_matches) else len(vol_text)
                ch_block = vol_text[ch_start:ch_end]

                ch_data = _parse_chapter_block(ch_block)
                ch_data["chapter_number"] = ch_num
                chapters.append(ch_data)

            volumes.append({
                "volume_number": vol_num,
                "title": vol_title,
                "synopsis": vol_synopsis,
                "chapters": chapters,
            })

        return {"volumes": volumes}

    async def design_volume(
        self,
        genre: str,
        volume_number: int,
        volume_title: str,
        volume_synopsis: str,
        chapters_per_volume: int,
        chapter_start: int,
        architecture: dict,
        genre_research: dict,
        previously_written_summaries: str = "",
    ) -> dict:
        """Design per-chapter outline for a single volume (on-demand).

        Args:
            genre: Novel genre.
            volume_number: The volume number (1-based).
            volume_title: Title of this volume.
            volume_synopsis: Synopsis/description of this volume.
            chapters_per_volume: Number of chapters in this volume.
            chapter_start: First chapter number of this volume.
            architecture: Full story architecture dict.
            genre_research: Genre research dict.
            previously_written_summaries: Summaries of already-written chapters for continuity.

        Returns:
            Dict with key 'chapters': list of chapter dicts with outline, key_scenes, etc.
        """
        chapter_end = chapter_start + chapters_per_volume - 1

        system_prompt = self._extract_section(self._template, "System Prompt")
        user_prompt = self._extract_section(self._template, "单卷冲突设计指令")

        user_prompt = user_prompt.replace("{genre}", genre)
        user_prompt = user_prompt.replace("{volume_number}", str(volume_number))
        user_prompt = user_prompt.replace("{volume_title}", volume_title)
        user_prompt = user_prompt.replace("{volume_synopsis}", volume_synopsis)
        user_prompt = user_prompt.replace("{chapters_per_volume}", str(chapters_per_volume))
        user_prompt = user_prompt.replace("{chapter_start}", str(chapter_start))
        user_prompt = user_prompt.replace("{chapter_end}", str(chapter_end))

        arch_text = self._format_architecture(architecture)
        user_prompt = user_prompt.replace("{story_architecture}", arch_text)

        genre_brief = self._format_genre_brief(genre_research)
        user_prompt = user_prompt.replace("{genre_brief}", genre_brief)

        user_prompt = user_prompt.replace(
            "{previously_written_summaries}",
            previously_written_summaries or "无（这是第一卷）",
        )

        logger.info(
            "ConflictDesignAgent: designing volume %d (chapters %d-%d)",
            volume_number, chapter_start, chapter_end,
        )

        raw_text = await self.llm.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.settings.llm_model_planning,
        )

        chapters = self._parse_volume_chapters(raw_text, chapter_start, chapter_end)

        logger.info(
            "ConflictDesignAgent: volume %d completed - %d chapters designed",
            volume_number, len(chapters),
        )
        return {"chapters": chapters}

    @staticmethod
    def _parse_volume_chapters(text: str, chapter_start: int, chapter_end: int) -> list[dict]:
        """Parse chapter blocks from a single-volume design output."""
        ch_matches = list(_CHAPTER_RE.finditer(text))
        chapters = []
        for j, ch_match in enumerate(ch_matches):
            ch_num = int(ch_match.group(1))
            ch_start_pos = ch_match.end()
            ch_end_pos = ch_matches[j + 1].start() if j + 1 < len(ch_matches) else len(text)
            ch_block = text[ch_start_pos:ch_end_pos]

            ch_data = _parse_chapter_block(ch_block)
            ch_data["chapter_number"] = ch_num
            chapters.append(ch_data)
        return chapters
