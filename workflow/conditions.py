"""Conditional routing functions for the LangGraph workflow."""

from workflow.state import NovelWorkflowState


def route_after_init(state: NovelWorkflowState) -> str:
    """Route after initialization: plan a new novel or load existing context."""
    if state.get("error"):
        return "handle_error"
    if state.get("mode") in ("new", "plan_only"):
        return "plan_novel"
    return "load_chapter_context"


def route_after_plan(state: NovelWorkflowState) -> str:
    """Route after plan_novel: plan_only mode ends here, otherwise continue to chapter writing."""
    if state.get("mode") == "plan_only":
        return "__end__"
    return "load_chapter_context"


def route_after_review(state: NovelWorkflowState) -> str:
    """Route after review: pass -> save, fail -> re-edit (up to max_revisions)."""
    review = state.get("review_result", {})
    revision_count = state.get("revision_count", 0)
    max_revisions = state.get("max_revisions", 3)

    if review.get("passed", False):
        return "save_chapter"

    # Max revisions reached -> force save with warning
    if revision_count >= max_revisions:
        return "save_chapter"

    # Failed review -> back to edit
    return "edit_chapter"


def route_after_memory_update(state: NovelWorkflowState) -> str:
    """Route after memory update: trigger global review every N chapters or advance."""
    chapters_written = state.get("chapters_written", 0)
    interval = state.get("global_review_interval", 5)

    if chapters_written > 0 and chapters_written % interval == 0:
        return "global_review"
    return "advance_chapter"


def route_after_advance(state: NovelWorkflowState) -> str:
    """Route after advancing chapter: more to write or done."""
    if state.get("should_stop", False):
        return "__end__"

    current = state.get("current_chapter", 0)
    target = state.get("target_chapters", 0)

    if target > 0 and current > target:
        return "__end__"

    return "load_chapter_context"
