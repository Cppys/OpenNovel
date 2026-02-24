"""LangGraph checkpointing utilities for workflow state persistence."""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_checkpointer(db_path: Optional[Path | str] = None):
    """Create a SqliteSaver checkpointer for workflow state persistence.

    Falls back to MemorySaver if sqlite checkpointer is unavailable.

    Args:
        db_path: Path to the SQLite checkpoint database file.

    Returns:
        A LangGraph checkpointer instance.
    """
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        if db_path is None:
            from config.settings import Settings
            settings = Settings()
            db_path = Path(settings.sqlite_db_path).parent / "checkpoints.db"

        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        checkpointer = SqliteSaver.from_conn_string(str(db_path))
        logger.info("SqliteSaver checkpointer: %s", db_path)
        return checkpointer

    except ImportError:
        logger.warning(
            "langgraph.checkpoint.sqlite not available — falling back to MemorySaver. "
            "Install langgraph[sqlite] for persistent checkpointing."
        )
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()


def resume_workflow(thread_id: str, checkpointer=None) -> Optional[dict]:
    """Load the latest state snapshot for a given thread to resume a workflow.

    Args:
        thread_id: The workflow thread ID to resume.
        checkpointer: Checkpointer instance. Creates a default one if not provided.

    Returns:
        The latest state dict for the thread, or None if not found.
    """
    if checkpointer is None:
        checkpointer = get_checkpointer()

    try:
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = checkpointer.get_tuple(config)
        if checkpoint_tuple and checkpoint_tuple.checkpoint:
            state = checkpoint_tuple.checkpoint.get("channel_values", {})
            logger.info("Resuming workflow thread '%s'", thread_id)
            return state
        logger.warning("No checkpoint found for thread '%s'", thread_id)
        return None
    except Exception as e:
        logger.error("Failed to load checkpoint for thread '%s': %s", thread_id, e)
        return None


def list_checkpoints(checkpointer=None) -> list[dict]:
    """List all saved workflow checkpoints with their metadata.

    Args:
        checkpointer: Checkpointer instance. Creates a default one if not provided.

    Returns:
        List of checkpoint info dicts with thread_id, checkpoint_id, and timestamp.
    """
    if checkpointer is None:
        checkpointer = get_checkpointer()

    results = []
    try:
        for cp_tuple in checkpointer.list(config=None):
            cfg = cp_tuple.config or {}
            cp = cp_tuple.checkpoint or {}
            results.append({
                "thread_id": cfg.get("configurable", {}).get("thread_id", ""),
                "checkpoint_id": cp.get("id", ""),
                "ts": cp.get("ts", ""),
            })
    except Exception as e:
        logger.error("Failed to list checkpoints: %s", e)

    return results
