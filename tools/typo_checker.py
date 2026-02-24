"""Chinese typo detection using common error patterns."""

import re
from dataclasses import dataclass


@dataclass
class TypoIssue:
    """A detected typo or language issue."""
    position: int  # Approximate character position
    original: str
    suggestion: str
    reason: str


# Common Chinese homophone/similar-character errors
_COMMON_TYPOS = {
    "的地得": [
        (r"高兴的跑", "高兴地跑", "形容动作应用'地'"),
        (r"开心的笑", "开心地笑", "形容动作应用'地'"),
        (r"飞快的跑", "飞快地跑", "形容动作应用'地'"),
        (r"慢慢的走", "慢慢地走", "形容动作应用'地'"),
        (r"安静的坐", "安静地坐", "形容动作应用'地'"),
        (r"轻轻的说", "轻轻地说", "形容动作应用'地'"),
    ],
    "常见错字": [
        (r"既使", "即使", "应为'即使'"),
        (r"凑和", "凑合", "应为'凑合'"),
        (r"迫不急待", "迫不及待", "应为'迫不及待'"),
        (r"一愁莫展", "一筹莫展", "应为'一筹莫展'"),
        (r"再接再历", "再接再厉", "应为'再接再厉'"),
        (r"走头无路", "走投无路", "应为'走投无路'"),
        (r"融汇贯通", "融会贯通", "应为'融会贯通'"),
        (r"事实胜于雄辨", "事实胜于雄辩", "应为'雄辩'"),
        (r"一如继往", "一如既往", "应为'一如既往'"),
        (r"一诺千斤", "一诺千金", "应为'一诺千金'"),
        (r"甘败下风", "甘拜下风", "应为'甘拜下风'"),
        (r"自暴自起", "自暴自弃", "应为'自暴自弃'"),
        (r"按步就班", "按部就班", "应为'按部就班'"),
        (r"金璧辉煌", "金碧辉煌", "应为'金碧辉煌'"),
        (r"震耳欲聋", "振聋发聩", "注意区分'震'和'振'"),
    ],
    "标点符号": [
        (r"[.]{3}", "……", "中文省略号应使用'……'"),
        (r'(?<![a-zA-Z])"', "\u201c", "中文应使用中文引号"),
    ],
}

# AI writing pattern detection
_AI_PATTERNS = [
    (r"突然.{0,20}突然", "同一段落中多次使用'突然'"),
    (r"此刻.{0,50}此刻", "多次使用'此刻'"),
    (r"就在这时.{0,50}就在这时", "多次使用'就在这时'"),
    (r"不由自主地.{0,50}不由自主地", "多次使用'不由自主地'"),
    (r"情不自禁地.{0,50}情不自禁地", "多次使用'情不自禁地'"),
    (r"一股强大的", "'一股强大的'是常见AI模式"),
]


def check_typos(text: str) -> list[TypoIssue]:
    """Check text for common Chinese typos and errors.

    Returns a list of detected issues with positions and suggestions.
    """
    issues = []

    # Check common typo patterns
    for category, patterns in _COMMON_TYPOS.items():
        for pattern, suggestion, reason in patterns:
            for match in re.finditer(pattern, text):
                issues.append(TypoIssue(
                    position=match.start(),
                    original=match.group(),
                    suggestion=suggestion,
                    reason=reason,
                ))

    return issues


def check_ai_patterns(text: str) -> list[str]:
    """Check for common AI writing patterns.

    Returns a list of detected pattern descriptions.
    """
    detected = []
    for pattern, description in _AI_PATTERNS:
        if re.search(pattern, text):
            detected.append(description)
    return detected


def check_punctuation(text: str) -> list[TypoIssue]:
    """Check for punctuation issues in Chinese text."""
    issues = []

    # Check for English punctuation in Chinese context
    for match in re.finditer(r"(?<=[\u4e00-\u9fff])[,.](?=[\u4e00-\u9fff])", text):
        issues.append(TypoIssue(
            position=match.start(),
            original=match.group(),
            suggestion="，" if match.group() == "," else "。",
            reason="中文语境应使用中文标点",
        ))

    # Check for missing space issues or double punctuation
    for match in re.finditer(r"[。！？]{2,}", text):
        if match.group() != "……" and match.group() != "？！":
            issues.append(TypoIssue(
                position=match.start(),
                original=match.group(),
                suggestion=match.group()[0],
                reason="重复标点符号",
            ))

    return issues
