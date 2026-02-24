"""Chinese text utilities: character counting, segmentation, analysis."""

import re
from typing import Optional


def count_chinese_chars(text: str) -> int:
    """Count Chinese characters (CJK Unified Ideographs) in text.

    This matches how Fanqie Novel counts characters for chapter length requirements.
    Only counts actual Chinese characters, excluding punctuation, spaces, and Latin characters.
    """
    return len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))


def count_total_chars(text: str) -> int:
    """Count all non-whitespace characters including punctuation."""
    return len(re.sub(r"\s", "", text))


def get_chapter_ending(content: str, char_limit: int = 500) -> str:
    """Extract the ending portion of a chapter for continuity.

    Returns the last `char_limit` characters of the chapter content.
    """
    if not content:
        return ""
    if len(content) <= char_limit:
        return content
    return content[-char_limit:]


def extract_dialogue_ratio(text: str) -> float:
    """Calculate the ratio of dialogue text to total text.

    Dialogue is detected by Chinese quotation marks.
    Target ratio: 20-40% for natural web novels.
    """
    if not text:
        return 0.0
    # Match text within Chinese quotation marks
    dialogue_matches = re.findall(r'[\u201c\u201d"](.*?)[\u201c\u201d"]', text)
    dialogue_chars = sum(len(m) for m in dialogue_matches)
    total = count_chinese_chars(text)
    if total == 0:
        return 0.0
    return dialogue_chars / total


def calculate_sentence_length_variance(text: str) -> float:
    """Calculate the standard deviation of sentence lengths.

    Higher variance indicates more varied writing style.
    Target: std dev > 5 for human-like writing.
    """
    # Split by sentence-ending punctuation
    sentences = re.split(r"[。！？…\n]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) < 2:
        return 0.0

    lengths = [count_chinese_chars(s) for s in sentences]
    lengths = [l for l in lengths if l > 0]

    if len(lengths) < 2:
        return 0.0

    mean = sum(lengths) / len(lengths)
    variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
    return variance ** 0.5


def calculate_unique_sentence_starters(text: str) -> float:
    """Calculate the ratio of unique sentence starters.

    Target: > 70% unique for natural writing style.
    """
    sentences = re.split(r"[。！？…\n]+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) >= 2]

    if not sentences:
        return 0.0

    starters = [s[:2] for s in sentences]
    unique = len(set(starters))
    return unique / len(starters)


def split_into_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs."""
    paragraphs = re.split(r"\n\s*\n|\n", text)
    return [p.strip() for p in paragraphs if p.strip()]
