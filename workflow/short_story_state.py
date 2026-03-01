"""LangGraph workflow state definition for short stories."""

from typing import TypedDict, Optional


class ShortStoryWorkflowState(TypedDict, total=False):
    """State shared by all short story workflow nodes.

    Fields:
    - Identity: story_id, mode
    - Planning: genre, premise, ideas, plan_data, style_guide
    - Writing: content, title, char_count, target_chars
    - Editing: edited_content, edited_char_count, edit_notes
    - Review: review_result, revision_count
    - Publishing: publish_mode, publish_result, category_ids, fanqie_item_id
    - Config: max_revisions
    - Control: error, should_stop, last_node, retry_count
    """

    # Identity
    story_id: int
    mode: str  # "new" or "continue"

    # Planning
    genre: str
    premise: str
    ideas: str
    plan_data: dict   # Full planner output
    style_guide: str
    target_chars: int  # Target word count (default 10000)

    # Writing
    title: str
    content: str
    char_count: int

    # Editing
    edited_content: str
    edited_char_count: int
    edit_notes: str

    # Review
    review_result: dict  # {passed, score, issues, summary}
    revision_count: int

    # Publishing
    publish_mode: str  # "draft" or "publish"
    publish_result: dict
    category_ids: list  # Fanqie category IDs
    fanqie_item_id: str

    # Config
    max_revisions: int

    # Control flow
    error: str
    should_stop: bool
    last_node: str
    retry_count: int
