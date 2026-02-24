"""Tests for Chinese text utility functions."""

import pytest


class TestCountChineseChars:
    def test_empty_string(self):
        from tools.text_utils import count_chinese_chars
        assert count_chinese_chars("") == 0

    def test_pure_chinese(self):
        from tools.text_utils import count_chinese_chars
        assert count_chinese_chars("你好世界") == 4

    def test_mixed_chinese_and_english(self):
        from tools.text_utils import count_chinese_chars
        assert count_chinese_chars("Hello你好world") == 2

    def test_chinese_punctuation_excluded(self):
        from tools.text_utils import count_chinese_chars
        # Chinese punctuation (。！？) is not in CJK Unified Ideographs range
        assert count_chinese_chars("你好。！？") == 2

    def test_numbers_excluded(self):
        from tools.text_utils import count_chinese_chars
        assert count_chinese_chars("123456") == 0

    def test_spaces_excluded(self):
        from tools.text_utils import count_chinese_chars
        assert count_chinese_chars("   ") == 0

    def test_extended_cjk_counted(self):
        from tools.text_utils import count_chinese_chars
        # Characters in extension A block (U+3400-U+4DBF) should count
        text = "你好" * 10
        assert count_chinese_chars(text) == 20


class TestCountTotalChars:
    def test_whitespace_excluded(self):
        from tools.text_utils import count_total_chars
        assert count_total_chars("hello world") == 10

    def test_chinese_counted(self):
        from tools.text_utils import count_total_chars
        assert count_total_chars("你好 世界") == 4

    def test_empty_string(self):
        from tools.text_utils import count_total_chars
        assert count_total_chars("") == 0

    def test_only_whitespace(self):
        from tools.text_utils import count_total_chars
        assert count_total_chars("   \t\n") == 0


class TestGetChapterEnding:
    def test_short_text_returns_all(self):
        from tools.text_utils import get_chapter_ending
        text = "短文本内容"
        assert get_chapter_ending(text, char_limit=500) == text

    def test_long_text_returns_tail(self):
        from tools.text_utils import get_chapter_ending
        text = "a" * 1000
        result = get_chapter_ending(text, char_limit=100)
        assert len(result) == 100
        assert result == "a" * 100

    def test_empty_string(self):
        from tools.text_utils import get_chapter_ending
        assert get_chapter_ending("") == ""

    def test_exact_limit_length(self):
        from tools.text_utils import get_chapter_ending
        text = "x" * 500
        assert get_chapter_ending(text, char_limit=500) == text

    def test_default_limit_is_500(self):
        from tools.text_utils import get_chapter_ending
        text = "y" * 600
        result = get_chapter_ending(text)
        assert len(result) == 500


class TestExtractDialogueRatio:
    def test_no_dialogue_returns_zero(self):
        from tools.text_utils import extract_dialogue_ratio
        text = "这是一段没有对话的叙述文字。主角在思考问题。故事继续发展。"
        assert extract_dialogue_ratio(text) == 0.0

    def test_empty_returns_zero(self):
        from tools.text_utils import extract_dialogue_ratio
        assert extract_dialogue_ratio("") == 0.0

    def test_all_non_chinese_returns_zero(self):
        from tools.text_utils import extract_dialogue_ratio
        # If no Chinese chars, total is 0, ratio is 0
        assert extract_dialogue_ratio("hello world") == 0.0

    def test_with_chinese_quotes(self):
        from tools.text_utils import extract_dialogue_ratio
        # "\u201c你好！\u201d" = "你好！"
        text = "\u201c你好\u201d他说。然后走开了。"
        ratio = extract_dialogue_ratio(text)
        assert 0.0 < ratio <= 1.0


class TestCalculateSentenceLengthVariance:
    def test_single_sentence_returns_zero(self):
        from tools.text_utils import calculate_sentence_length_variance
        assert calculate_sentence_length_variance("只有一句话") == 0.0

    def test_empty_returns_zero(self):
        from tools.text_utils import calculate_sentence_length_variance
        assert calculate_sentence_length_variance("") == 0.0

    def test_two_equal_sentences_zero_variance(self):
        from tools.text_utils import calculate_sentence_length_variance
        # Two sentences of the same length have zero variance
        text = "你好世界。你好世界。"
        result = calculate_sentence_length_variance(text)
        assert result == 0.0

    def test_varied_sentences_positive_variance(self):
        from tools.text_utils import calculate_sentence_length_variance
        # Mix of very short and very long sentences
        text = "短。" + "这是一个非常长的句子，包含了很多的内容和描述！" * 3
        result = calculate_sentence_length_variance(text)
        assert result > 0.0


class TestCalculateUniqueSentenceStarters:
    def test_empty_returns_zero(self):
        from tools.text_utils import calculate_unique_sentence_starters
        assert calculate_unique_sentence_starters("") == 0.0

    def test_all_same_starters(self):
        from tools.text_utils import calculate_unique_sentence_starters
        # All 3 sentences start with the same 2-char prefix "你好"
        text = "你好世界。你好朋友们。你好陌生人。"
        result = calculate_unique_sentence_starters(text)
        # unique_starters = {"你好"} = 1 out of 3 sentences → ratio ≈ 0.33
        assert result <= 1.0 / 3 + 0.01

    def test_all_unique_starters(self):
        from tools.text_utils import calculate_unique_sentence_starters
        text = "我出发了。他回来了。她笑了。"
        result = calculate_unique_sentence_starters(text)
        assert result == 1.0


class TestSplitIntoParagraphs:
    def test_empty_returns_empty(self):
        from tools.text_utils import split_into_paragraphs
        assert split_into_paragraphs("") == []

    def test_single_paragraph(self):
        from tools.text_utils import split_into_paragraphs
        result = split_into_paragraphs("只有一段。")
        assert len(result) == 1

    def test_multiple_paragraphs_double_newline(self):
        from tools.text_utils import split_into_paragraphs
        text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
        result = split_into_paragraphs(text)
        assert len(result) == 3

    def test_single_newline_splits(self):
        from tools.text_utils import split_into_paragraphs
        text = "第一行。\n第二行。"
        result = split_into_paragraphs(text)
        assert len(result) >= 2

    def test_whitespace_only_lines_excluded(self):
        from tools.text_utils import split_into_paragraphs
        text = "内容一。\n   \n内容二。"
        result = split_into_paragraphs(text)
        # Should not include the whitespace-only line
        assert all(p.strip() for p in result)
