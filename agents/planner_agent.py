"""Planner Agent: orchestrates sub-agents to generate novel outlines, character cards, and world settings."""

import logging
import math
import re
from typing import Callable, Optional

from agents.base_agent import BaseAgent
from config.settings import Settings
from tools.agent_sdk_client import AgentSDKClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured text parsers (shared with sub-agents)
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"【([^】]+)】")
_CHAPTER_RE = re.compile(r"===\s*第\s*(\d+)\s*章\s*===")
_VOLUME_RE = re.compile(r"【第(\d+)卷】\s*(.*)")


def _extract_section(text: str, name: str) -> str:
    """Extract content between 【name】 and the next 【...】 or end of text."""
    pattern = re.compile(rf"【{re.escape(name)}】[^\n]*\n(.*?)(?=\n【|$)", re.DOTALL)
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def _parse_pipe_lines(text: str, field_count: int) -> list[list[str]]:
    """Parse lines in 'a|b|c' format."""
    results = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("（") or line.startswith("("):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue  # Skip instruction lines
        while len(parts) < field_count:
            parts.append("")
        results.append(parts[:field_count])
    return results


def _parse_chapter_block(block: str) -> dict:
    """Parse a single chapter block (lines after ===第N章===)."""
    outline = ""
    key_scenes = []
    characters_involved = []
    emotional_tone = ""
    hook_type = "cliffhanger"

    for line in block.strip().splitlines():
        line = line.strip()
        if line.startswith("大纲：") or line.startswith("大纲:"):
            outline = line.split("：", 1)[-1].strip() if "：" in line else line.split(":", 1)[-1].strip()
        elif line.startswith("场景：") or line.startswith("场景:"):
            raw = line.split("：", 1)[-1].strip() if "：" in line else line.split(":", 1)[-1].strip()
            key_scenes = [s.strip() for s in raw.split(",") if s.strip()]
            if not key_scenes:
                key_scenes = [s.strip() for s in raw.split("，") if s.strip()]
        elif line.startswith("角色：") or line.startswith("角色:"):
            raw = line.split("：", 1)[-1].strip() if "：" in line else line.split(":", 1)[-1].strip()
            characters_involved = [s.strip() for s in raw.split(",") if s.strip()]
            if not characters_involved:
                characters_involved = [s.strip() for s in raw.split("，") if s.strip()]
        elif line.startswith("情感：") or line.startswith("情感:"):
            emotional_tone = line.split("：", 1)[-1].strip() if "：" in line else line.split(":", 1)[-1].strip()
        elif line.startswith("钩子：") or line.startswith("钩子:"):
            hook_type = line.split("：", 1)[-1].strip() if "：" in line else line.split(":", 1)[-1].strip()
        else:
            # Lines without a prefix may be continuation of outline
            if not outline and line:
                outline = line

    return {
        "outline": outline,
        "key_scenes": key_scenes,
        "characters_involved": characters_involved,
        "emotional_tone": emotional_tone,
        "hook_type": hook_type,
    }


def _parse_planner_output(text: str, genre: str) -> dict:
    """Parse the planner's structured text output into the expected dict format."""
    title = _extract_section(text, "书名") or "未命名小说"
    synopsis = _extract_section(text, "简介")
    style_guide = _extract_section(text, "风格指南")

    # Characters
    char_section = _extract_section(text, "角色列表")
    characters = []
    for parts in _parse_pipe_lines(char_section, 6):
        characters.append({
            "name": parts[0],
            "role": parts[1],
            "description": parts[2],
            "background": parts[3],
            "abilities": parts[4],
            "arc": parts[5],
        })

    # World settings
    ws_section = _extract_section(text, "世界设定")
    world_settings = []
    for parts in _parse_pipe_lines(ws_section, 3):
        world_settings.append({
            "category": parts[0],
            "name": parts[1],
            "description": parts[2],
        })

    # Volumes and chapters
    volumes = []
    vol_matches = list(_VOLUME_RE.finditer(text))

    for i, vol_match in enumerate(vol_matches):
        vol_num = int(vol_match.group(1))
        vol_title = vol_match.group(2).strip()

        # Get text between this volume header and next volume header (or end)
        start = vol_match.end()
        end = vol_matches[i + 1].start() if i + 1 < len(vol_matches) else len(text)
        vol_text = text[start:end]

        # Extract volume synopsis (text before first ===第N章===)
        first_ch = _CHAPTER_RE.search(vol_text)
        vol_synopsis = vol_text[:first_ch.start()].strip() if first_ch else vol_text.strip()

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

    return {
        "title": title,
        "synopsis": synopsis,
        "genre": genre,
        "style_guide": style_guide,
        "characters": characters,
        "world_settings": world_settings,
        "volumes": volumes,
    }


# ---------------------------------------------------------------------------
# Agent (orchestrator for 3 sub-agents)
# ---------------------------------------------------------------------------

class PlannerAgent(BaseAgent):
    """Orchestrates sub-agents to generate complete novel plans."""

    def __init__(
        self,
        llm_client: Optional[AgentSDKClient] = None,
        settings: Optional[Settings] = None,
    ):
        super().__init__(llm_client, settings)

    async def generate_outline(
        self,
        genre: str,
        premise: str,
        target_chapters: int = 30,
        ideas: str = "",
        chapters_per_volume: int = 30,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """Generate a complete novel outline by orchestrating sub-agents.

        Pipeline:
          1. GenreResearchAgent  — analyze genre conventions and reader expectations
          2. StoryArchitectAgent — design characters, world, volumes, plot backbone

        Per-chapter outlines are NOT generated here; they are created on-demand
        when each volume's chapters are about to be written (via ConflictDesignAgent
        in the load_chapter_context workflow node).

        Args:
            genre: Novel genre (e.g., '玄幻', '都市', '言情').
            premise: User-provided concept/premise.
            target_chapters: Total number of chapters to plan (from user input).
            ideas: Optional author notes / extra ideas.
            chapters_per_volume: Chapters per volume (default 30).
            progress_callback: Optional callback(step_name) for progress reporting.

        Returns:
            Dict with keys: title, synopsis, genre, style_guide, characters,
            world_settings, volumes (metadata only, no chapter outlines),
            planning_metadata.
        """
        from agents.genre_research_agent import GenreResearchAgent
        from agents.story_architect_agent import StoryArchitectAgent
        from agents.conflict_design_agent import ConflictDesignAgent

        num_volumes = math.ceil(target_chapters / chapters_per_volume)

        # Step 1: Genre Research
        if progress_callback:
            progress_callback("genre_research")

        logger.info("Step 1/2: Genre research for '%s'", genre)
        research_agent = GenreResearchAgent(self.llm, self.settings)
        genre_brief = await research_agent.analyze(genre, premise, ideas)

        # Step 2: Story Architecture
        if progress_callback:
            progress_callback("story_architecture")

        logger.info("Step 2/2: Story architecture for '%s'", premise[:50])
        architect_agent = StoryArchitectAgent(self.llm, self.settings)
        architecture = await architect_agent.design(
            genre, premise, ideas, target_chapters, genre_brief,
            chapters_per_volume=chapters_per_volume,
        )

        # Build volumes list (metadata only, no per-chapter outlines)
        arch_volumes = architecture.get("volumes", [])
        volumes = []
        for i, vol_meta in enumerate(arch_volumes):
            vol_entry = {
                "volume_number": vol_meta.get("volume_number", i + 1),
                "title": vol_meta.get("title", ""),
                "synopsis": vol_meta.get("synopsis", ""),
                "chapters": [],
            }
            volumes.append(vol_entry)

        # Build planning_metadata for later on-demand outline generation
        planning_metadata = {
            "genre_brief": genre_brief,
            "plot_backbone": architecture.get("plot_backbone", ""),
            "architecture_summary": ConflictDesignAgent._format_architecture(architecture),
            "volumes": [
                {
                    "volume_number": v.get("volume_number", idx + 1),
                    "title": v.get("title", ""),
                    "synopsis": v.get("synopsis", ""),
                }
                for idx, v in enumerate(arch_volumes)
            ],
        }

        # Merge result
        result = {
            "title": architecture.get("title", premise),
            "synopsis": architecture.get("synopsis", ""),
            "genre": genre,
            "style_guide": architecture.get("style_guide", ""),
            "characters": architecture.get("characters", []),
            "world_settings": architecture.get("world_settings", []),
            "volumes": volumes,
            "planning_metadata": planning_metadata,
        }

        # Ensure defaults
        result.setdefault("title", "未命名小说")
        result.setdefault("synopsis", "")
        result.setdefault("genre", genre)
        result.setdefault("style_guide", "")
        result.setdefault("characters", [])
        result.setdefault("world_settings", [])
        result.setdefault("volumes", [])

        if progress_callback:
            progress_callback("complete")

        logger.info(
            "Outline generated: '%s' with %d characters, %d volumes",
            result["title"],
            len(result["characters"]),
            len(result["volumes"]),
        )

        return result
