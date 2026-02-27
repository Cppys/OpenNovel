"""LangGraph StateGraph: orchestrates the multi-agent novel workflow."""

import asyncio
import json
import logging
import math
from typing import Optional

from langgraph.graph import StateGraph, END

from config.exceptions import LLMError, LLMTimeoutError, WorkflowError
from config.settings import Settings, get_settings
from memory.chroma_store import ChromaStore
from models.database import Database
from models.novel import Novel, Volume
from models.chapter import Chapter, Outline
from models.character import Character, WorldSetting
from models.enums import (
    NovelStatus, ChapterStatus, CharacterRole, CharacterStatus,
)
from tools.agent_sdk_client import AgentSDKClient
from tools.text_utils import count_chinese_chars

from agents.planner_agent import PlannerAgent
from agents.writer_agent import WriterAgent
from agents.editor_agent import EditorAgent
from agents.reviewer_agent import ReviewerAgent
from agents.memory_manager_agent import MemoryManagerAgent

from workflow.state import NovelWorkflowState
from workflow.conditions import (
    route_after_init,
    route_after_plan,
    route_after_review,
    route_after_memory_update,
    route_after_advance,
)

logger = logging.getLogger(__name__)

# Maximum retries per node for recoverable errors
_MAX_NODE_RETRIES = 2

# Module-level callback reference for sub-step progress reporting.
# Set by run_workflow(), used by plan_novel() to emit sub-step events.
_active_callback = None


def _make_thinking_forwarder(node_label: str):
    """Create an on_event callback that forwards thinking to the TUI console.

    The callback is passed to agent LLM calls so that extended thinking
    content appears in the TUI chat log during workflow execution.
    """
    cb = _active_callback
    if cb is None:
        return None

    console = getattr(cb, "_console", None)
    if console is None or not hasattr(console, "show_thinking"):
        return None

    def _on_event(event: dict):
        etype = event.get("type")
        if etype == "thinking":
            text = event.get("text", "")
            if text:
                console.show_thinking(text)
        elif etype == "text":
            console.update_status(f"{node_label} · 生成中")

    return _on_event


# ---------------------------------------------------------------------------
# Shared resource management — created once per run_workflow() call
# ---------------------------------------------------------------------------

class _WorkflowResources:
    """Lazily-initialized, shared resources for all workflow nodes."""

    def __init__(self):
        self._settings = None
        self._db = None
        self._chroma = None
        self._llm = None

    @property
    def settings(self):
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    @property
    def db(self):
        if self._db is None:
            self._db = Database(self.settings.sqlite_db_path)
        return self._db

    @property
    def chroma(self):
        if self._chroma is None:
            self._chroma = ChromaStore(self.settings.chroma_persist_dir)
        return self._chroma

    @property
    def llm(self):
        if self._llm is None:
            self._llm = AgentSDKClient(self.settings)
        return self._llm

    def close(self):
        if self._db is not None:
            self._db.close()


_resources: _WorkflowResources | None = None


def _get_resources() -> _WorkflowResources:
    global _resources
    if _resources is None:
        _resources = _WorkflowResources()
    return _resources


# ---------------------------------------------------------------------------
# Node functions (all async for Agent SDK compatibility)
# ---------------------------------------------------------------------------

async def initialize(state: NovelWorkflowState) -> dict:
    """Initialize shared resources and validate inputs."""
    logger.info("Entering node: initialize")
    r = _get_resources()
    mode = state.get("mode", "continue")
    novel_id = state.get("novel_id", 0)

    logger.info("Initializing workflow: mode=%s, novel_id=%s", mode, novel_id)

    # Base config from settings
    base_updates = {
        "max_revisions": r.settings.max_revisions,
        "global_review_interval": r.settings.global_review_interval,
        "retry_count": 0,
        "last_node": "initialize",
    }

    if mode == "continue":
        novel = r.db.get_novel(novel_id)
        if not novel:
            return {**base_updates, "error": f"Novel {novel_id} not found"}

        chapter_list = state.get("chapter_list", [])

        if chapter_list:
            # chapter_list mode: write specific chapters
            return {
                **base_updates,
                "novel_id": novel_id,
                "genre": novel.genre,
                "style_guide": novel.style_guide or "",
                "current_chapter": chapter_list[0],
                "target_chapters": max(chapter_list),
                "chapter_list": chapter_list,
                "chapter_list_index": 0,
                "chapters_written": 0,
                "revision_count": 0,
                "publish_mode": state.get("publish_mode", r.settings.default_publish_mode),
                "should_stop": False,
                "error": "",
            }

        last_ch = r.db.get_last_chapter_number(novel_id)
        target = state.get("target_chapters", 0)
        actual_target = last_ch + target if target > 0 else 0

        return {
            **base_updates,
            "novel_id": novel_id,
            "genre": novel.genre,
            "style_guide": novel.style_guide or "",
            "current_chapter": last_ch + 1,
            "target_chapters": actual_target,
            "chapters_written": 0,
            "revision_count": 0,
            "publish_mode": state.get("publish_mode", r.settings.default_publish_mode),
            "should_stop": False,
            "error": "",
        }

    elif mode == "new":
        genre = state.get("genre", "")
        premise = state.get("premise", "")
        if not genre:
            return {**base_updates, "error": "Genre is required for new novel"}
        if len(premise) < 2:
            return {**base_updates, "error": "Premise is required"}

        return {
            **base_updates,
            "genre": genre,
            "premise": premise,
            "ideas": state.get("ideas", ""),
            "current_chapter": 1,
            "target_chapters": state.get("target_chapters", 10),
            "chapters_written": 0,
            "revision_count": 0,
            "publish_mode": state.get("publish_mode", r.settings.default_publish_mode),
            "should_stop": False,
            "error": "",
        }

    elif mode == "plan_only":
        genre = state.get("genre", "")
        premise = state.get("premise", "")
        if not genre:
            return {**base_updates, "error": "Genre is required for new novel"}
        if len(premise) < 2:
            return {**base_updates, "error": "Premise is required"}

        return {
            **base_updates,
            "genre": genre,
            "premise": premise,
            "ideas": state.get("ideas", ""),
            "current_chapter": 1,
            "target_chapters": state.get("target_chapters", 30),
            "chapters_written": 0,
            "revision_count": 0,
            "should_stop": False,
            "error": "",
        }

    return {**base_updates, "error": f"Unknown mode: {mode}"}


async def plan_novel(state: NovelWorkflowState) -> dict:
    """Generate novel outline, characters, world settings (new novel only)."""
    logger.info("Entering node: plan_novel")
    r = _get_resources()
    planner = PlannerAgent(llm_client=r.llm, settings=r.settings)

    genre = state.get("genre", "玄幻")
    premise = state.get("premise", "")
    ideas = state.get("ideas", "")
    target = state.get("target_chapters", 10)
    cpv = state.get("chapters_per_volume", 30)

    logger.info("Planning novel: genre=%s, chapters=%d, chapters_per_volume=%d", genre, target, cpv)

    # Sub-step progress callback that forwards to the active workflow callback
    def _planning_progress(step: str):
        if _active_callback is not None:
            _active_callback.on_node_exit(f"plan_novel:{step}", state)

    try:
        outline_data = await planner.generate_outline(
            genre=genre,
            premise=premise,
            target_chapters=target,
            ideas=ideas,
            chapters_per_volume=cpv,
            progress_callback=_planning_progress,
        )
    except LLMError as e:
        return {"error": f"Planning failed: {e}", "last_node": "plan_novel"}
    except Exception as e:
        return {"error": f"Planning failed: {e}", "last_node": "plan_novel"}

    # Always use the exact user-provided premise as the novel title
    if premise:
        outline_data["title"] = premise

    # Persist novel to database

    # Serialize planning_metadata for on-demand outline generation
    planning_meta_json = None
    planning_meta = outline_data.get("planning_metadata")
    if planning_meta:
        planning_meta_json = json.dumps(planning_meta, ensure_ascii=False)

    novel = Novel(
        title=outline_data.get("title", "未命名小说"),
        genre=genre,
        synopsis=outline_data.get("synopsis", ""),
        style_guide=outline_data.get("style_guide", ""),
        target_chapter_count=target,
        chapters_per_volume=cpv,
        planning_metadata=planning_meta_json,
        status=NovelStatus.WRITING,
    )
    novel_id = r.db.create_novel(novel)
    logger.info("Novel created: id=%d, title=%s", novel_id, novel.title)

    # Persist volumes and chapter outlines
    for vol_data in outline_data.get("volumes", []):
        volume = Volume(
            novel_id=novel_id,
            volume_number=vol_data.get("volume_number", 1),
            title=vol_data.get("title", ""),
            synopsis=vol_data.get("synopsis", ""),
            target_chapters=len(vol_data.get("chapters", [])),
        )
        vol_id = r.db.create_volume(volume)

        for ch_data in vol_data.get("chapters", []):
            ch_num = ch_data.get("chapter_number", 0)
            if ch_num == 0:
                continue
            outline = Outline(
                novel_id=novel_id,
                volume_id=vol_id,
                chapter_number=ch_num,
                outline_text=ch_data.get("outline", ""),
                key_scenes=json.dumps(ch_data.get("key_scenes", []), ensure_ascii=False),
                characters_involved=json.dumps(
                    ch_data.get("characters_involved", []), ensure_ascii=False
                ),
                emotional_tone=ch_data.get("emotional_tone", ""),
                hook_type=ch_data.get("hook_type", "cliffhanger"),
            )
            r.db.create_outline(outline)

    # Persist characters
    for char_data in outline_data.get("characters", []):
        role_str = char_data.get("role", "supporting")
        try:
            role = CharacterRole(role_str)
        except ValueError:
            role = CharacterRole.SUPPORTING
        character = Character(
            novel_id=novel_id,
            name=char_data.get("name", ""),
            role=role,
            description=char_data.get("description", ""),
            background=char_data.get("background", ""),
            abilities=char_data.get("abilities", ""),
            first_appearance=char_data.get("first_appearance", 1),
        )
        r.db.create_character(character)

    # Persist world settings
    for ws_data in outline_data.get("world_settings", []):
        ws = WorldSetting(
            novel_id=novel_id,
            category=ws_data.get("category", "other"),
            name=ws_data.get("name", ""),
            description=ws_data.get("description", ""),
        )
        r.db.create_world_setting(ws)
        r.chroma.add_world_event(
            novel_id=novel_id,
            chapter_number=0,
            event_description=f"[{ws.category}] {ws.name}: {ws.description}",
        )

    return {
        "novel_id": novel_id,
        "outline_data": outline_data,
        "style_guide": outline_data.get("style_guide", ""),
        "last_node": "plan_novel",
    }


# Maximum chapters to generate outlines for in a single LLM call.
# Larger values slow down the call and risk incomplete output.
_OUTLINE_BATCH_SIZE = 5


async def load_chapter_context(state: NovelWorkflowState) -> dict:
    """Load the current chapter's outline from the database.

    If no outline exists for the current chapter, triggers on-demand outline
    generation in batches of _OUTLINE_BATCH_SIZE chapters until the current
    chapter's outline is available (or all batches in the volume are exhausted).
    """
    logger.info("Entering node: load_chapter_context")
    r = _get_resources()

    novel_id = state["novel_id"]
    current_ch = state["current_chapter"]

    outline = r.db.get_outline(novel_id, current_ch)
    if outline:
        return {
            "chapter_outline": outline.outline_text,
            "emotional_tone": outline.emotional_tone,
            "hook_type": outline.hook_type or "cliffhanger",
            "revision_count": 0,
            "last_node": "load_chapter_context",
        }

    # No outline found — try on-demand generation
    novel = r.db.get_novel(novel_id)
    if novel and novel.planning_metadata:
        logger.info("No outline for chapter %d, generating outlines on-demand", current_ch)

        # Allow state to override the default batch size
        batch_size = state.get("outline_batch_size") or _OUTLINE_BATCH_SIZE

        try:
            meta = json.loads(novel.planning_metadata)
            cpv = novel.chapters_per_volume or 30
            vol_num = (current_ch - 1) // cpv + 1
            vol_start = (vol_num - 1) * cpv + 1
            vol_end = vol_start + cpv - 1

            # Find volume metadata
            vol_meta_list = meta.get("volumes", [])
            vol_meta = None
            for vm in vol_meta_list:
                if vm.get("volume_number") == vol_num:
                    vol_meta = vm
                    break
            if not vol_meta:
                vol_meta = {"title": f"第{vol_num}卷", "synopsis": ""}

            # Build architecture dict from metadata
            characters = r.db.get_characters(novel_id)
            architecture = {
                "title": novel.title,
                "synopsis": novel.synopsis,
                "style_guide": novel.style_guide,
                "characters": [
                    {"name": c.name, "role": c.role.value, "description": c.description,
                     "background": c.background, "abilities": c.abilities, "arc": ""}
                    for c in characters
                ],
                "world_settings": [
                    {"category": ws.category, "name": ws.name, "description": ws.description}
                    for ws in r.db.get_world_settings(novel_id)
                ],
                "volumes": vol_meta_list,
                "plot_backbone": meta.get("plot_backbone", ""),
            }

            # Ensure volume record exists
            volumes = r.db.get_volumes(novel_id)
            vol_id = None
            for v in volumes:
                if v.volume_number == vol_num:
                    vol_id = v.id
                    break
            if vol_id is None:
                vol_id = r.db.create_volume(Volume(
                    novel_id=novel_id,
                    volume_number=vol_num,
                    title=vol_meta.get("title", f"第{vol_num}卷"),
                    synopsis=vol_meta.get("synopsis", ""),
                    target_chapters=cpv,
                ))

            # Generate outlines in batches of batch_size
            from agents.conflict_design_agent import ConflictDesignAgent
            conflict_agent = ConflictDesignAgent(llm_client=r.llm, settings=r.settings)

            batch_start = current_ch  # Start from the chapter we actually need
            while batch_start <= vol_end:
                batch_end = min(batch_start + batch_size - 1, vol_end)
                batch_count = batch_end - batch_start + 1

                # Skip this batch if all its outlines already exist
                has_missing = any(
                    r.db.get_outline(novel_id, ch) is None
                    for ch in range(batch_start, batch_end + 1)
                )
                if not has_missing:
                    batch_start = batch_end + 1
                    continue

                # Emit progress event
                if _active_callback is not None:
                    _active_callback.on_node_exit(
                        f"load_chapter_context:generating_outlines_{batch_start}_{batch_end}",
                        state,
                    )

                logger.info(
                    "Generating outlines batch: chapter %d-%d (%d chapters)",
                    batch_start, batch_end, batch_count,
                )

                # Gather previously written chapter summaries for continuity
                recent_summaries = r.chroma.get_recent_summaries(
                    novel_id, batch_start, count=10
                )
                summary_lines = [
                    f"第{s['chapter_number']}章：{s['summary']}"
                    for s in recent_summaries
                ]
                previously_written = "\n".join(summary_lines) if summary_lines else ""

                try:
                    vol_data = await conflict_agent.design_volume(
                        genre=novel.genre,
                        volume_number=vol_num,
                        volume_title=vol_meta.get("title", ""),
                        volume_synopsis=vol_meta.get("synopsis", ""),
                        chapters_per_volume=batch_count,
                        chapter_start=batch_start,
                        architecture=architecture,
                        genre_research=meta.get("genre_brief", {}),
                        previously_written_summaries=previously_written,
                    )

                    # Persist outlines
                    saved = 0
                    for ch_data in vol_data.get("chapters", []):
                        ch_num = ch_data.get("chapter_number", 0)
                        if ch_num == 0:
                            continue
                        if r.db.get_outline(novel_id, ch_num):
                            continue
                        new_outline = Outline(
                            novel_id=novel_id,
                            volume_id=vol_id,
                            chapter_number=ch_num,
                            outline_text=ch_data.get("outline", ""),
                            key_scenes=json.dumps(
                                ch_data.get("key_scenes", []), ensure_ascii=False
                            ),
                            characters_involved=json.dumps(
                                ch_data.get("characters_involved", []), ensure_ascii=False
                            ),
                            emotional_tone=ch_data.get("emotional_tone", ""),
                            hook_type=ch_data.get("hook_type", "cliffhanger"),
                        )
                        r.db.create_outline(new_outline)
                        saved += 1

                    logger.info(
                        "Batch %d-%d: generated %d outlines, saved %d new",
                        batch_start, batch_end, len(vol_data.get("chapters", [])), saved,
                    )
                except Exception as e:
                    logger.warning("Outline batch %d-%d failed: %s", batch_start, batch_end, e)

                # After the first batch (which covers current_ch), check if we got
                # the outline we need. If so, stop generating further batches —
                # they'll be generated on-demand when those chapters are reached.
                outline = r.db.get_outline(novel_id, current_ch)
                if outline:
                    break

                batch_start = batch_end + 1

            # Re-fetch the outline for current chapter
            outline = r.db.get_outline(novel_id, current_ch)
            if outline:
                return {
                    "chapter_outline": outline.outline_text,
                    "emotional_tone": outline.emotional_tone,
                    "hook_type": outline.hook_type or "cliffhanger",
                    "revision_count": 0,
                    "last_node": "load_chapter_context",
                }

        except Exception as e:
            logger.warning("On-demand outline generation failed: %s", e)

    # Fallback: build an informative placeholder using available data
    logger.warning("No outline for chapter %d, building context-based placeholder", current_ch)
    placeholder_parts = [f"第{current_ch}章：推进主线剧情。"]
    try:
        characters = r.db.get_characters(novel_id)
        if characters:
            active_chars = [c for c in characters if c.status.value == "active"]
            main_chars = [c for c in active_chars if c.role.value in ("protagonist", "antagonist")]
            if main_chars:
                char_info = "、".join(f"{c.name}（{c.description[:30]}）" for c in main_chars[:4])
                placeholder_parts.append(f"核心角色：{char_info}")
        events = r.db.get_unresolved_events(novel_id)
        if events:
            event_descs = "；".join(e.description[:40] for e in events[:3])
            placeholder_parts.append(f"待推进伏笔：{event_descs}")
    except Exception:
        pass

    return {
        "chapter_outline": "\n".join(placeholder_parts),
        "emotional_tone": "",
        "hook_type": "cliffhanger",
        "revision_count": 0,
        "last_node": "load_chapter_context",
    }


async def retrieve_memory(state: NovelWorkflowState) -> dict:
    """Assemble memory context for the writer."""
    logger.info("Entering node: retrieve_memory")
    r = _get_resources()

    novel_id = state["novel_id"]
    current_ch = state["current_chapter"]
    chapter_outline = state.get("chapter_outline", "")

    memory_mgr = MemoryManagerAgent(db=r.db, chroma=r.chroma, llm_client=r.llm, settings=r.settings)

    try:
        context_coro = memory_mgr.retriever.assemble_context_async(
            novel_id, current_ch, chapter_outline
        )
        ending_coro = asyncio.to_thread(
            memory_mgr.get_previous_ending, novel_id, current_ch
        )
        context, previous_ending = await asyncio.gather(context_coro, ending_coro)
    except Exception as e:
        logger.warning("Memory retrieval failed, using empty context: %s", e)
        context = ""
        previous_ending = ""

    return {
        "context_prompt": context,
        "previous_ending": previous_ending,
        "last_node": "retrieve_memory",
    }


async def write_chapter(state: NovelWorkflowState) -> dict:
    """Generate chapter draft using the Writer agent."""
    logger.info("Entering node: write_chapter")
    r = _get_resources()
    writer = WriterAgent(llm_client=r.llm, settings=r.settings)

    try:
        result = await writer.write_chapter(
            genre=state.get("genre", ""),
            style_guide=state.get("style_guide", ""),
            chapter_number=state["current_chapter"],
            chapter_outline=state.get("chapter_outline", ""),
            context_prompt=state.get("context_prompt", ""),
            previous_chapter_ending=state.get("previous_ending", ""),
            emotional_tone=state.get("emotional_tone", ""),
            hook_type=state.get("hook_type", "cliffhanger"),
            target_chapters=state.get("target_chapters", 0),
            on_event=_make_thinking_forwarder("写作"),
        )
    except LLMError as e:
        return {"error": str(e), "last_node": "write_chapter"}

    return {
        "draft_title": result["title"],
        "draft_content": result["content"],
        "draft_char_count": result["char_count"],
        "last_node": "write_chapter",
    }


async def edit_chapter(state: NovelWorkflowState) -> dict:
    """Polish chapter and adjust word count via Editor agent."""
    logger.info("Entering node: edit_chapter")
    r = _get_resources()
    editor = EditorAgent(llm_client=r.llm, settings=r.settings)

    # Use review issues if this is a re-edit after failed review
    review_issues = None
    review_result = state.get("review_result")
    if review_result and not review_result.get("passed", True):
        review_issues = review_result.get("issues", [])

    # On first edit, use draft content; on re-edit, use previously edited content
    if state.get("revision_count", 0) > 0 and state.get("edited_content"):
        content = state["edited_content"]
        char_count = state["edited_char_count"]
    else:
        content = state.get("draft_content", "")
        char_count = state.get("draft_char_count", 0)

    try:
        result = await editor.edit_chapter(
            chapter_content=content,
            chapter_outline=state.get("chapter_outline", ""),
            char_count=char_count,
            review_issues=review_issues,
            on_event=_make_thinking_forwarder("编辑"),
        )
    except LLMError as e:
        return {"error": str(e), "last_node": "edit_chapter"}

    return {
        "edited_content": result["content"],
        "edited_char_count": result["char_count"],
        "edit_notes": result["edit_notes"],
        "last_node": "edit_chapter",
    }


async def review_chapter(state: NovelWorkflowState) -> dict:
    """Multi-dimensional quality review via Reviewer agent."""
    logger.info("Entering node: review_chapter")
    r = _get_resources()
    reviewer = ReviewerAgent(llm_client=r.llm, settings=r.settings)

    try:
        result = await reviewer.review_chapter(
            chapter_content=state.get("edited_content", ""),
            chapter_outline=state.get("chapter_outline", ""),
            context_prompt=state.get("context_prompt", ""),
            char_count=state.get("edited_char_count"),
            on_event=_make_thinking_forwarder("审核"),
        )
    except LLMError as e:
        # If review fails, force pass to avoid blocking
        logger.warning("Review LLM call failed, force passing: %s", e)
        result = {"passed": True, "score": 0.0, "summary": f"[审核跳过] LLM调用失败: {e}"}

    revision_count = state.get("revision_count", 0) + 1
    max_revisions = state.get("max_revisions", r.settings.max_revisions)
    passed = result.get("passed", False)

    if not passed and revision_count >= max_revisions:
        logger.warning(
            "Chapter %d: max revisions reached (score=%.1f). Force accepting.",
            state["current_chapter"], result.get("score", 0),
        )
        result["passed"] = True
        result["summary"] = (
            f"[强制通过] 已达最大修订次数({max_revisions})。"
            + result.get("summary", "")
        )

    return {
        "review_result": result,
        "revision_count": revision_count,
        "last_node": "review_chapter",
    }


async def save_chapter(state: NovelWorkflowState) -> dict:
    """Persist the reviewed chapter to the database."""
    logger.info("Entering node: save_chapter")
    r = _get_resources()

    novel_id = state["novel_id"]
    current_ch = state["current_chapter"]
    review = state.get("review_result", {})

    existing = r.db.get_chapter(novel_id, current_ch)
    if existing:
        existing.title = state.get("draft_title", f"第{current_ch}章")
        existing.content = state.get("edited_content", "")
        existing.char_count = state.get("edited_char_count", 0)
        existing.status = ChapterStatus.REVIEWED
        existing.review_score = review.get("score")
        existing.review_notes = review.get("summary", "")
        existing.revision_count = state.get("revision_count", 0)
        r.db.update_chapter(existing)
    else:
        chapter = Chapter(
            novel_id=novel_id,
            chapter_number=current_ch,
            title=state.get("draft_title", f"第{current_ch}章"),
            content=state.get("edited_content", ""),
            char_count=state.get("edited_char_count", 0),
            outline=state.get("chapter_outline", ""),
            status=ChapterStatus.REVIEWED,
            review_score=review.get("score"),
            review_notes=review.get("summary", ""),
            revision_count=state.get("revision_count", 0),
        )
        r.db.create_chapter(chapter)

    logger.info(
        "Chapter %d saved: %d chars, score=%.1f",
        current_ch, state.get("edited_char_count", 0), review.get("score", 0),
    )

    return {"last_node": "save_chapter"}


async def update_memory(state: NovelWorkflowState) -> dict:
    """Update memory stores after chapter is saved."""
    logger.info("Entering node: update_memory")
    r = _get_resources()

    memory_mgr = MemoryManagerAgent(db=r.db, chroma=r.chroma, llm_client=r.llm, settings=r.settings)

    novel_id = state["novel_id"]
    current_ch = state["current_chapter"]
    content = state.get("edited_content", "")

    try:
        await memory_mgr.update_memory(novel_id, current_ch, content)
    except Exception as e:
        logger.warning("Memory update failed (non-fatal): %s", e)

    chapters_written = state.get("chapters_written", 0) + 1

    return {"chapters_written": chapters_written, "last_node": "update_memory"}


async def global_review(state: NovelWorkflowState) -> dict:
    """Periodic global consistency review (every N chapters)."""
    logger.info("Entering node: global_review")
    r = _get_resources()

    memory_mgr = MemoryManagerAgent(db=r.db, chroma=r.chroma, llm_client=r.llm, settings=r.settings)

    try:
        review_data = await memory_mgr.global_review(state["novel_id"])
        inconsistencies = review_data.get("inconsistencies", [])
        if inconsistencies:
            logger.warning("Global review found %d inconsistencies:", len(inconsistencies))
            for issue in inconsistencies:
                logger.warning("  - %s", issue)
    except Exception as e:
        logger.warning("Global review failed (non-fatal): %s", e)

    return {"last_node": "global_review"}


async def advance_chapter(state: NovelWorkflowState) -> dict:
    """Advance to the next chapter number."""
    logger.info("Entering node: advance_chapter")
    current = state["current_chapter"]
    target = state.get("target_chapters", 0)
    chapter_list = state.get("chapter_list", [])

    if chapter_list:
        # chapter_list mode: advance through the list
        idx = state.get("chapter_list_index", 0) + 1
        if idx >= len(chapter_list):
            logger.info("All %d selected chapters completed!", len(chapter_list))
            return {"should_stop": True, "chapter_list_index": idx, "last_node": "advance_chapter"}
        next_ch = chapter_list[idx]
        logger.info("Advancing to chapter %d (list index %d)", next_ch, idx)
        return {
            "current_chapter": next_ch,
            "chapter_list_index": idx,
            "last_node": "advance_chapter",
        }

    next_ch = current + 1

    if target > 0 and next_ch > target:
        logger.info("All %d chapters completed!", target)
        return {"should_stop": True, "current_chapter": next_ch, "last_node": "advance_chapter"}

    logger.info("Advancing to chapter %d", next_ch)
    return {"current_chapter": next_ch, "last_node": "advance_chapter"}


async def handle_error(state: NovelWorkflowState) -> dict:
    """Handle errors — retry recoverable ones, stop on fatal ones."""
    logger.info("Entering node: handle_error")
    error = state.get("error", "Unknown error")
    last_node = state.get("last_node", "")
    retry_count = state.get("retry_count", 0)

    # Determine if error is recoverable (LLM timeout, transient failures)
    is_recoverable = any(
        keyword in error.lower()
        for keyword in ["timeout", "rate limit", "connection", "temporary"]
    )

    if is_recoverable and retry_count < _MAX_NODE_RETRIES:
        logger.warning(
            "Recoverable error in %s (retry %d/%d): %s",
            last_node, retry_count + 1, _MAX_NODE_RETRIES, error,
        )
        return {
            "error": "",
            "retry_count": retry_count + 1,
            "should_stop": False,
        }

    # Fatal error or max retries exceeded
    logger.error("Workflow error (fatal): %s", error)
    return {"should_stop": True}


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(checkpointer=None) -> StateGraph:
    """Build and return the compiled LangGraph workflow.

    Args:
        checkpointer: Optional LangGraph checkpointer for state persistence.
    """
    graph = StateGraph(NovelWorkflowState)

    # Add all nodes
    graph.add_node("initialize", initialize)
    graph.add_node("plan_novel", plan_novel)
    graph.add_node("load_chapter_context", load_chapter_context)
    graph.add_node("retrieve_memory", retrieve_memory)
    graph.add_node("write_chapter", write_chapter)
    graph.add_node("edit_chapter", edit_chapter)
    graph.add_node("review_chapter", review_chapter)
    graph.add_node("save_chapter", save_chapter)
    graph.add_node("update_memory", update_memory)
    graph.add_node("global_review", global_review)
    graph.add_node("advance_chapter", advance_chapter)
    graph.add_node("handle_error", handle_error)

    # Entry point
    graph.set_entry_point("initialize")

    # Conditional: after init -> plan_novel (new) or load_chapter_context (continue)
    graph.add_conditional_edges(
        "initialize",
        route_after_init,
        {
            "plan_novel": "plan_novel",
            "load_chapter_context": "load_chapter_context",
            "handle_error": "handle_error",
        },
    )

    # plan_novel -> load_chapter_context (write mode) or END (plan_only mode)
    graph.add_conditional_edges(
        "plan_novel",
        route_after_plan,
        {
            "load_chapter_context": "load_chapter_context",
            "__end__": END,
        },
    )

    # Linear: load_context -> retrieve_memory -> write -> edit -> review
    graph.add_edge("load_chapter_context", "retrieve_memory")
    graph.add_edge("retrieve_memory", "write_chapter")
    graph.add_edge("write_chapter", "edit_chapter")
    graph.add_edge("edit_chapter", "review_chapter")

    # Conditional: after review -> save (pass) or edit (fail, up to max)
    graph.add_conditional_edges(
        "review_chapter",
        route_after_review,
        {
            "save_chapter": "save_chapter",
            "edit_chapter": "edit_chapter",
        },
    )

    # save -> update_memory
    graph.add_edge("save_chapter", "update_memory")

    # Conditional: after memory update -> global_review (every N ch) or advance
    graph.add_conditional_edges(
        "update_memory",
        route_after_memory_update,
        {
            "global_review": "global_review",
            "advance_chapter": "advance_chapter",
        },
    )

    # global_review -> advance
    graph.add_edge("global_review", "advance_chapter")

    # Conditional: after advance -> next chapter or END
    graph.add_conditional_edges(
        "advance_chapter",
        route_after_advance,
        {
            "load_chapter_context": "load_chapter_context",
            "__end__": END,
        },
    )

    # Error -> END
    graph.add_edge("handle_error", END)

    compile_kwargs = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer

    return graph.compile(**compile_kwargs)


async def run_workflow(
    mode: str = "new",
    novel_id: Optional[int] = None,
    genre: str = "",
    premise: str = "",
    ideas: str = "",
    target_chapters: int = 10,
    chapters_per_volume: int = 30,
    chapter_list: Optional[list[int]] = None,
    publish_mode: str = "draft",
    outline_batch_size: Optional[int] = None,
    checkpointer=None,
    thread_id: Optional[str] = None,
    callback=None,
) -> dict:
    """Build and run the full workflow asynchronously.

    Args:
        mode: "new" to create a novel, "continue" to add chapters.
        novel_id: Required for "continue" mode.
        genre: Novel genre (for "new" mode).
        premise: Story premise (for "new" mode).
        ideas: Optional author notes / extra ideas for the planner (for "new"/"plan_only").
        target_chapters: Number of chapters to write.
        chapters_per_volume: Chapters per volume (for "new"/"plan_only" mode).
        chapter_list: Specific chapter numbers to write (for "continue" mode).
        publish_mode: "draft", "publish", or "pre-publish".
        outline_batch_size: Override default outline batch size (default 5).
        checkpointer: Optional LangGraph checkpointer for persistence.
        thread_id: Optional thread ID for checkpoint resume.
        callback: Optional WorkflowCallback for progress reporting.

    Returns:
        Final workflow state dict.
    """
    app = build_graph(checkpointer=checkpointer)

    initial_state: NovelWorkflowState = {
        "mode": mode,
        "novel_id": novel_id or 0,
        "genre": genre,
        "premise": premise,
        "ideas": ideas,
        "target_chapters": target_chapters,
        "chapters_per_volume": chapters_per_volume,
        "publish_mode": publish_mode,
    }

    if chapter_list:
        initial_state["chapter_list"] = chapter_list
        initial_state["chapter_list_index"] = 0

    if outline_batch_size is not None:
        initial_state["outline_batch_size"] = outline_batch_size

    logger.info("Starting workflow: mode=%s, genre=%s, chapters=%d", mode, genre, target_chapters)

    # Calculate recursion limit based on number of chapters.
    # Each chapter cycle uses ~8 nodes; revisions and global reviews can add more.
    num_chapters = len(chapter_list) if chapter_list else target_chapters
    recursion_limit = max(50, num_chapters * 15 + 30)

    config = {"recursion_limit": recursion_limit}
    if thread_id:
        config["configurable"] = {"thread_id": thread_id}

    global _resources
    _resources = _WorkflowResources()
    try:
        if callback is not None:
            global _active_callback
            _active_callback = callback
            try:
                final_state = await _run_with_callback(app, initial_state, config or None, callback)
            finally:
                _active_callback = None
        else:
            final_state = await app.ainvoke(initial_state, config=config or None)
    finally:
        _resources.close()
        _resources = None

    logger.info("Workflow completed")
    return final_state


async def _run_with_callback(app, initial_state: dict, config, callback) -> dict:
    """Run the workflow using astream() and emit progress callbacks.

    Args:
        app: Compiled LangGraph application.
        initial_state: Initial workflow state.
        config: LangGraph config dict (may include thread_id).
        callback: WorkflowCallback instance.

    Returns:
        Accumulated final state dict.
    """
    accumulated: dict = {}
    prev_chapters_written = 0

    async for event in app.astream(initial_state, config=config):
        # Each event is {node_name: state_update_dict}
        for node_name, node_update in event.items():
            if node_name == "__end__":
                continue

            # Merge update into accumulated state
            if isinstance(node_update, dict):
                accumulated.update(node_update)

            # Fire node callback
            callback.on_node_exit(node_name, accumulated)

            # Detect chapter completion
            chapters_written = accumulated.get("chapters_written", 0)
            if chapters_written > prev_chapters_written:
                chapter_list = accumulated.get("chapter_list", [])
                total_count = len(chapter_list) if chapter_list else accumulated.get("target_chapters", 0)
                callback.on_chapter_complete(
                    chapters_written,
                    total_count,
                    accumulated.get("edited_char_count", 0),
                )
                prev_chapters_written = chapters_written

            # Detect error
            if accumulated.get("error"):
                callback.on_error(node_name, accumulated["error"])

    callback.on_workflow_complete(accumulated)
    return accumulated
