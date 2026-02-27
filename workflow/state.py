"""LangGraph workflow state definition."""

from typing import TypedDict, Optional, Annotated
from operator import add


class NovelWorkflowState(TypedDict, total=False):
    """Global state shared by all workflow nodes.

    Fields are grouped logically:
    - Identity: novel_id, mode
    - Planning: genre, premise, outline_data, style_guide
    - Chapter tracking: current_chapter, target_chapters, chapters_written
    - Memory context: context_prompt, previous_ending
    - Draft pipeline: chapter_outline, draft_content, draft_title, draft_char_count
    - Edit pipeline: edited_content, edited_char_count, edit_notes
    - Review pipeline: review_result, revision_count
    - Publishing: publish_mode, publish_result
    - Config: max_revisions, global_review_interval (from Settings)
    - Control: error, should_stop, last_node, retry_count
    """

    # Identity
    novel_id: int
    mode: str  # "new" or "continue"

    # Planning (new novel)
    genre: str
    premise: str
    ideas: str   # Optional author notes / extra ideas for the planner
    outline_data: dict  # Full planner output
    style_guide: str
    chapters_per_volume: int  # Chapters per volume (default 30)

    # Chapter tracking
    current_chapter: int
    target_chapters: int
    chapters_written: int
    chapter_list: list       # Specific chapter numbers to write (e.g. [1,5,10])
    chapter_list_index: int  # Current index in chapter_list

    # Memory context (assembled before each chapter)
    context_prompt: str
    previous_ending: str
    emotional_tone: str
    hook_type: str

    # Draft pipeline
    chapter_outline: str  # Current chapter's outline text
    draft_content: str
    draft_title: str
    draft_char_count: int

    # Edit pipeline
    edited_content: str
    edited_char_count: int
    edit_notes: str

    # Review pipeline
    review_result: dict  # {passed, score, issues, summary}
    revision_count: int

    # Publishing
    publish_mode: str  # "draft", "publish", "pre-publish"
    publish_result: dict

    # Config (injected from Settings during initialization)
    max_revisions: int
    global_review_interval: int

    # Outline generation
    outline_batch_size: int  # Override default outline batch size (default 5)

    # Control flow
    error: str
    should_stop: bool
    last_node: str  # Track which node was last executed for error recovery
    retry_count: int  # Per-node retry counter for error recovery
