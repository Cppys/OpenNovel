"""Style analysis for detecting AI-generated text patterns."""

from dataclasses import dataclass

from tools.text_utils import (
    count_chinese_chars,
    extract_dialogue_ratio,
    calculate_sentence_length_variance,
    calculate_unique_sentence_starters,
    split_into_paragraphs,
)


@dataclass
class StyleReport:
    """Style analysis results."""
    char_count: int
    dialogue_ratio: float
    sentence_length_std: float
    unique_starters_ratio: float
    paragraph_count: int
    avg_paragraph_length: float
    issues: list[str]
    score: float  # 0-10


def analyze_style(text: str) -> StyleReport:
    """Analyze text for human-like writing style.

    Checks multiple dimensions and returns a report with a score.
    """
    issues = []

    char_count = count_chinese_chars(text)
    dialogue_ratio = extract_dialogue_ratio(text)
    sentence_std = calculate_sentence_length_variance(text)
    unique_starters = calculate_unique_sentence_starters(text)
    paragraphs = split_into_paragraphs(text)
    paragraph_count = len(paragraphs)

    avg_para_len = 0.0
    if paragraph_count > 0:
        avg_para_len = sum(count_chinese_chars(p) for p in paragraphs) / paragraph_count

    # Check dialogue ratio (target 20-40%)
    if dialogue_ratio < 0.10:
        issues.append(f"对话比例过低 ({dialogue_ratio:.1%})，建议增加角色对话")
    elif dialogue_ratio > 0.50:
        issues.append(f"对话比例过高 ({dialogue_ratio:.1%})，建议增加叙述和描写")

    # Check sentence length variance (target std > 5)
    if sentence_std < 3.0:
        issues.append(f"句式长度过于单一 (标准差={sentence_std:.1f})，需要长短句混用")
    elif sentence_std < 5.0:
        issues.append(f"句式变化稍显不足 (标准差={sentence_std:.1f})，建议增加变化")

    # Check unique sentence starters (target > 70%)
    if unique_starters < 0.50:
        issues.append(f"句首重复率过高 (独特率={unique_starters:.1%})，存在明显AI痕迹")
    elif unique_starters < 0.70:
        issues.append(f"句首多样性不足 (独特率={unique_starters:.1%})，建议丰富开头")

    # Check paragraph variation
    if paragraph_count > 0:
        para_lengths = [count_chinese_chars(p) for p in paragraphs]
        if para_lengths:
            para_max = max(para_lengths)
            para_min = min(para_lengths)
            if para_max > 0 and para_min / para_max > 0.8:
                issues.append("段落长度过于均匀，缺少节奏变化")

    # Calculate overall score
    score = 10.0
    # Deductions
    if sentence_std < 3.0:
        score -= 2.0
    elif sentence_std < 5.0:
        score -= 1.0

    if unique_starters < 0.50:
        score -= 2.0
    elif unique_starters < 0.70:
        score -= 1.0

    if dialogue_ratio < 0.10 or dialogue_ratio > 0.50:
        score -= 1.0

    if len(issues) > 3:
        score -= 1.0

    score = max(0.0, score)

    return StyleReport(
        char_count=char_count,
        dialogue_ratio=dialogue_ratio,
        sentence_length_std=sentence_std,
        unique_starters_ratio=unique_starters,
        paragraph_count=paragraph_count,
        avg_paragraph_length=avg_para_len,
        issues=issues,
        score=score,
    )
