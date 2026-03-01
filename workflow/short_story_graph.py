"""LangGraph StateGraph: orchestrates the short story writing workflow.

Workflow nodes:
  initialize → plan → write → edit → review → save → publish
                                  ↑              │
                                  └──── (fail) ──┘

Simpler than the novel workflow — short stories are single-unit content
without volumes, chapters, or memory management.
"""

import json
import logging
import re
from typing import Optional

from langgraph.graph import StateGraph, END

from config.exceptions import LLMError, WorkflowError
from config.settings import Settings, get_settings
from models.database import Database
from models.enums import ShortStoryStatus
from tools.agent_sdk_client import AgentSDKClient
from tools.text_utils import count_chinese_chars

from agents.short_story_planner_agent import ShortStoryPlannerAgent
from agents.short_story_writer_agent import ShortStoryWriterAgent
from agents.short_story_editor_agent import ShortStoryEditorAgent
from agents.short_story_reviewer_agent import ShortStoryReviewerAgent

from workflow.short_story_state import ShortStoryWorkflowState

logger = logging.getLogger(__name__)

_MAX_NODE_RETRIES = 2


def _clean_story_title(title: str) -> str:
    """Sanitise a story title from AI output.

    Strips: 《》, leading/trailing quotes, excess whitespace, Markdown bold.
    """
    title = title.strip()
    title = re.sub(r'^《(.+?)》$', r'\1', title)
    title = title.strip('""\u201c\u201d\u2018\u2019\'')
    title = re.sub(r'\*{1,2}(.+?)\*{1,2}', r'\1', title)
    title = re.sub(r'\s+', ' ', title).strip()
    if len(title) > 30:
        title = title[:30]
    return title


# Module-level callback for progress reporting
_active_callback = None


def _make_thinking_forwarder(node_label: str):
    """Create an on_event callback that forwards thinking to the TUI."""
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
# Shared resources
# ---------------------------------------------------------------------------

class _ShortStoryResources:
    """Lazily-initialized shared resources for all workflow nodes."""

    def __init__(self):
        self._settings = None
        self._db = None
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
    def llm(self):
        if self._llm is None:
            self._llm = AgentSDKClient(self.settings)
        return self._llm

    def close(self):
        if self._db is not None:
            self._db.close()


_resources: _ShortStoryResources | None = None


def _get_resources() -> _ShortStoryResources:
    global _resources
    if _resources is None:
        _resources = _ShortStoryResources()
    return _resources


# ---------------------------------------------------------------------------
# Workflow nodes
# ---------------------------------------------------------------------------

async def initialize(state: ShortStoryWorkflowState) -> dict:
    """Validate inputs and initialize resources."""
    res = _get_resources()
    mode = state.get("mode", "new")
    target_chars = state.get("target_chars", 10000)

    updates = {
        "last_node": "initialize",
        "retry_count": 0,
        "revision_count": 0,
        "max_revisions": res.settings.max_revisions,
        "target_chars": target_chars,
    }

    if mode == "new":
        genre = state.get("genre", "")
        premise = state.get("premise", "")
        if not genre or not premise:
            return {**updates, "error": "genre and premise are required for new stories"}

        story_id = res.db.create_short_story(
            genre=genre,
            synopsis=premise,
        )
        updates["story_id"] = story_id
        logger.info("New short story created: id=%d, genre=%s", story_id, genre)

    elif mode == "continue":
        story_id = state.get("story_id", 0)
        if not story_id:
            return {**updates, "error": "story_id is required for continue mode"}
        story = res.db.get_short_story(story_id)
        if not story:
            return {**updates, "error": f"Short story {story_id} not found"}

        # Restore state from saved data
        if story.get("planning_data"):
            try:
                plan = json.loads(story["planning_data"])
                updates["plan_data"] = plan
                updates["title"] = plan.get("title", story.get("title", ""))
                updates["style_guide"] = plan.get("style_guide", "")
            except json.JSONDecodeError:
                pass

        if story.get("content"):
            updates["content"] = story["content"]
            updates["char_count"] = story.get("char_count", 0)

        updates["story_id"] = story_id
        logger.info("Continuing short story: id=%d", story_id)

    return updates


async def plan_story(state: ShortStoryWorkflowState) -> dict:
    """Generate the story concept and outline."""
    res = _get_resources()

    if _active_callback:
        _active_callback.update_status("规划短故事概念...")

    genre = state.get("genre", "")
    premise = state.get("premise", "")
    ideas = state.get("ideas", "")
    target_chars = state.get("target_chars", 10000)

    agent = ShortStoryPlannerAgent(res.llm, res.settings)
    try:
        plan = await agent.plan(
            genre=genre,
            premise=premise,
            ideas=ideas,
            target_chars=target_chars,
            on_event=_make_thinking_forwarder("规划"),
        )
    except (LLMError, Exception) as e:
        logger.error("Planning failed: %s", e)
        return {"error": f"Planning failed: {e}", "last_node": "plan_story"}

    # Save plan to database
    story_id = state.get("story_id", 0)
    title = _clean_story_title(plan.get("title", "未命名短故事"))
    style_guide = plan.get("style_guide", "")
    category_suggestion = plan.get("category_suggestion", "")

    res.db.update_short_story(
        story_id,
        title=title,
        genre=genre,
        synopsis=plan.get("synopsis", premise),
        planning_data=json.dumps(plan, ensure_ascii=False),
        style_guide=style_guide,
        status=ShortStoryStatus.WRITING.value,
    )

    logger.info("Story planned: title=%s, target=%d chars", title, target_chars)

    return {
        "plan_data": plan,
        "title": title,
        "style_guide": style_guide,
        "category_ids": [],  # Will be resolved during publish
        "last_node": "plan_story",
        "retry_count": 0,
    }


async def write_story(state: ShortStoryWorkflowState) -> dict:
    """Generate the full short story content."""
    res = _get_resources()

    if _active_callback:
        _active_callback.update_status("撰写短故事...")

    plan = state.get("plan_data", {})
    genre = state.get("genre", "")
    style_guide = state.get("style_guide", "")
    target_chars = state.get("target_chars", 10000)

    # Build outline and character info from plan
    plot_outline = ""
    characters = ""
    if plan:
        if isinstance(plan.get("plot_outline"), dict):
            plot_outline = json.dumps(plan["plot_outline"], ensure_ascii=False, indent=2)
        elif isinstance(plan.get("plot_outline"), str):
            plot_outline = plan["plot_outline"]

        if isinstance(plan.get("characters"), list):
            chars = []
            for c in plan["characters"]:
                if isinstance(c, dict):
                    chars.append(f"- {c.get('name', '?')}: {c.get('description', '')}")
                else:
                    chars.append(f"- {c}")
            characters = "\n".join(chars)
        elif isinstance(plan.get("characters"), str):
            characters = plan["characters"]

    agent = ShortStoryWriterAgent(res.llm, res.settings)
    try:
        result = await agent.write(
            genre=genre,
            style_guide=style_guide,
            plot_outline=plot_outline,
            characters=characters,
            target_chars=target_chars,
            on_event=_make_thinking_forwarder("撰写"),
        )
    except (LLMError, Exception) as e:
        logger.error("Writing failed: %s", e)
        return {"error": f"Writing failed: {e}", "last_node": "write_story"}

    title = result.get("title", state.get("title", ""))
    content = result.get("content", "")
    char_count = result.get("char_count", count_chinese_chars(content))

    # Save to database
    story_id = state.get("story_id", 0)
    res.db.update_short_story(
        story_id,
        title=title,
        content=content,
        char_count=char_count,
        status=ShortStoryStatus.EDITING.value,
    )

    logger.info("Story written: title=%s, chars=%d", title, char_count)

    return {
        "title": title,
        "content": content,
        "char_count": char_count,
        "last_node": "write_story",
        "retry_count": 0,
    }


async def edit_story(state: ShortStoryWorkflowState) -> dict:
    """Polish and refine the short story content."""
    res = _get_resources()

    if _active_callback:
        _active_callback.update_status("编辑润色中...")

    # Use edited content if available (from review feedback), else draft
    content = state.get("edited_content") or state.get("content", "")
    char_count = state.get("edited_char_count") or state.get("char_count", 0)

    # Include review issues if this is a revision pass
    review_issues = ""
    review = state.get("review_result")
    if review and not review.get("passed", True):
        issues = review.get("issues", [])
        if issues:
            parts = []
            for iss in issues:
                if isinstance(iss, dict):
                    parts.append(
                        f"- [{iss.get('severity', '?')}] {iss.get('category', '')}: "
                        f"{iss.get('description', '')}"
                    )
                else:
                    parts.append(f"- {iss}")
            review_issues = "\n".join(parts)

    agent = ShortStoryEditorAgent(res.llm, res.settings)
    try:
        result = await agent.edit(
            content=content,
            char_count=char_count,
            review_issues=review_issues,
            on_event=_make_thinking_forwarder("编辑"),
        )
    except (LLMError, Exception) as e:
        logger.error("Editing failed: %s", e)
        return {"error": f"Editing failed: {e}", "last_node": "edit_story"}

    edited_content = result.get("content", content)
    edited_char_count = result.get("char_count", count_chinese_chars(edited_content))

    logger.info("Story edited: chars %d→%d", char_count, edited_char_count)

    return {
        "edited_content": edited_content,
        "edited_char_count": edited_char_count,
        "edit_notes": result.get("edit_notes", ""),
        "last_node": "edit_story",
        "retry_count": 0,
    }


async def review_story(state: ShortStoryWorkflowState) -> dict:
    """Quality-check the short story content."""
    res = _get_resources()

    if _active_callback:
        _active_callback.update_status("审核中...")

    title = state.get("title", "")
    content = state.get("edited_content") or state.get("content", "")
    char_count = state.get("edited_char_count") or state.get("char_count", 0)

    agent = ShortStoryReviewerAgent(res.llm, res.settings)
    try:
        result = await agent.review(
            title=title,
            content=content,
            char_count=char_count,
            on_event=_make_thinking_forwarder("审核"),
        )
    except (LLMError, Exception) as e:
        logger.error("Review failed: %s", e)
        # Force pass on review failure to avoid blocking
        result = {
            "passed": True,
            "score": 6.0,
            "issues": [],
            "summary": f"Review error (forced pass): {e}",
        }

    revision_count = state.get("revision_count", 0)
    max_revisions = state.get("max_revisions", 3)

    # Force pass after max revisions
    if not result.get("passed") and revision_count >= max_revisions:
        logger.warning(
            "Force-passing after %d revisions (score=%.1f)",
            revision_count, result.get("score", 0),
        )
        result["passed"] = True
        result["summary"] = (
            f"[强制通过] 已达最大修订次数 {max_revisions}。"
            f"当前得分: {result.get('score', 0):.1f}"
        )

    if not result.get("passed"):
        revision_count += 1

    logger.info(
        "Review result: passed=%s, score=%.1f, revision=%d",
        result.get("passed"), result.get("score", 0), revision_count,
    )

    return {
        "review_result": result,
        "revision_count": revision_count,
        "last_node": "review_story",
        "retry_count": 0,
    }


async def save_story(state: ShortStoryWorkflowState) -> dict:
    """Persist final content to database."""
    res = _get_resources()

    if _active_callback:
        _active_callback.update_status("保存中...")

    story_id = state.get("story_id", 0)
    title = state.get("title", "")
    content = state.get("edited_content") or state.get("content", "")
    char_count = state.get("edited_char_count") or state.get("char_count", 0)
    review = state.get("review_result", {})

    res.db.update_short_story(
        story_id,
        title=title,
        content=content,
        char_count=char_count,
        status=ShortStoryStatus.DRAFT.value,
        review_score=review.get("score"),
        review_notes=review.get("summary", ""),
        revision_count=state.get("revision_count", 0),
    )

    logger.info("Story saved: id=%d, title=%s, chars=%d", story_id, title, char_count)

    return {
        "last_node": "save_story",
        "retry_count": 0,
    }


async def handle_error(state: ShortStoryWorkflowState) -> dict:
    """Handle errors and attempt recovery."""
    error = state.get("error", "")
    retry_count = state.get("retry_count", 0)
    last_node = state.get("last_node", "")

    logger.error("Error in node '%s': %s (retry=%d)", last_node, error, retry_count)

    if retry_count < _MAX_NODE_RETRIES:
        return {
            "error": "",
            "retry_count": retry_count + 1,
        }

    # Unrecoverable — stop
    logger.error("Max retries exceeded for '%s', stopping workflow", last_node)
    return {"should_stop": True}


# ---------------------------------------------------------------------------
# Conditional routing
# ---------------------------------------------------------------------------

def route_after_init(state: ShortStoryWorkflowState) -> str:
    if state.get("error"):
        return "handle_error"
    mode = state.get("mode", "new")
    if mode == "new":
        return "plan_story"
    # Continue mode — skip to write if no content, else edit
    if state.get("content"):
        return "edit_story"
    return "write_story"


def route_after_plan(state: ShortStoryWorkflowState) -> str:
    if state.get("error"):
        return "handle_error"
    return "write_story"


def route_after_write(state: ShortStoryWorkflowState) -> str:
    if state.get("error"):
        return "handle_error"
    return "edit_story"


def route_after_edit(state: ShortStoryWorkflowState) -> str:
    if state.get("error"):
        return "handle_error"
    return "review_story"


def route_after_review(state: ShortStoryWorkflowState) -> str:
    if state.get("error"):
        return "handle_error"
    review = state.get("review_result", {})
    if review.get("passed", False):
        return "save_story"
    # Failed review — go back to edit
    return "edit_story"


def route_after_save(state: ShortStoryWorkflowState) -> str:
    return END


def route_after_error(state: ShortStoryWorkflowState) -> str:
    if state.get("should_stop"):
        return END
    # Retry from the last node
    last = state.get("last_node", "")
    valid = {
        "initialize", "plan_story", "write_story",
        "edit_story", "review_story", "save_story",
    }
    if last in valid:
        return last
    return END


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_short_story_graph() -> StateGraph:
    """Build and compile the short story workflow graph."""
    graph = StateGraph(ShortStoryWorkflowState)

    # Add nodes
    graph.add_node("initialize", initialize)
    graph.add_node("plan_story", plan_story)
    graph.add_node("write_story", write_story)
    graph.add_node("edit_story", edit_story)
    graph.add_node("review_story", review_story)
    graph.add_node("save_story", save_story)
    graph.add_node("handle_error", handle_error)

    # Set entry point
    graph.set_entry_point("initialize")

    # Add conditional edges
    graph.add_conditional_edges("initialize", route_after_init)
    graph.add_conditional_edges("plan_story", route_after_plan)
    graph.add_conditional_edges("write_story", route_after_write)
    graph.add_conditional_edges("edit_story", route_after_edit)
    graph.add_conditional_edges("review_story", route_after_review)
    graph.add_conditional_edges("save_story", route_after_save)
    graph.add_conditional_edges("handle_error", route_after_error)

    return graph.compile()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_short_story_workflow(
    genre: str = "",
    premise: str = "",
    ideas: str = "",
    target_chars: int = 10000,
    story_id: int = 0,
    mode: str = "new",
    publish_mode: str = "draft",
    callback=None,
) -> dict:
    """Run the short story workflow end-to-end.

    Args:
        genre:        Story genre/category (e.g. "悬疑惊悚", "脑洞").
        premise:      Story premise/concept in 1-3 sentences.
        ideas:        Optional extra ideas or requirements.
        target_chars: Target character count (default 10000).
        story_id:     Existing story ID (for continue mode).
        mode:         "new" or "continue".
        publish_mode: "draft" or "publish".
        callback:     Optional progress callback object.

    Returns:
        Final workflow state dict.
    """
    global _active_callback, _resources
    _active_callback = callback
    _resources = _ShortStoryResources()

    try:
        graph = build_short_story_graph()

        initial_state: ShortStoryWorkflowState = {
            "mode": mode,
            "genre": genre,
            "premise": premise,
            "ideas": ideas,
            "target_chars": target_chars,
            "publish_mode": publish_mode,
        }

        if story_id:
            initial_state["story_id"] = story_id

        result = await graph.ainvoke(initial_state)
        return dict(result)

    finally:
        _resources.close()
        _resources = None
        _active_callback = None
