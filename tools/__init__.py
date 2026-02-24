"""Tools package — Agent SDK client, text utilities, and JSON parsing."""

from tools.agent_sdk_client import AgentSDKClient
from tools.llm_client import parse_json_response
from tools.text_utils import (
    count_chinese_chars,
    count_total_chars,
    get_chapter_ending,
    extract_dialogue_ratio,
    calculate_sentence_length_variance,
    calculate_unique_sentence_starters,
    split_into_paragraphs,
)

__all__ = [
    "AgentSDKClient",
    "parse_json_response",
    "count_chinese_chars",
    "count_total_chars",
    "get_chapter_ending",
    "extract_dialogue_ratio",
    "calculate_sentence_length_variance",
    "calculate_unique_sentence_starters",
    "split_into_paragraphs",
]
