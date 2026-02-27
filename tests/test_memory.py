"""Tests for ChromaDB vector store operations."""

import pytest


@pytest.fixture
def chroma_store(tmp_path):
    """Return a ChromaStore backed by a temporary directory."""
    from memory.chroma_store import ChromaStore
    return ChromaStore(persist_dir=tmp_path / "chroma")


class TestChapterSummaries:
    def test_add_and_get_recent_summaries(self, chroma_store):
        chroma_store.add_chapter_summary(
            novel_id=1, chapter_number=1,
            summary="第一章的摘要内容",
            key_characters="主角",
            emotional_tone="紧张",
        )
        chroma_store.add_chapter_summary(
            novel_id=1, chapter_number=2,
            summary="第二章的摘要内容",
        )

        recent = chroma_store.get_recent_summaries(novel_id=1, current_chapter=3, count=2)
        assert len(recent) == 2
        assert recent[0]["chapter_number"] == 1
        assert recent[1]["chapter_number"] == 2

    def test_get_recent_respects_count_limit(self, chroma_store):
        for i in range(1, 6):
            chroma_store.add_chapter_summary(
                novel_id=2, chapter_number=i, summary=f"第{i}章摘要"
            )

        recent = chroma_store.get_recent_summaries(novel_id=2, current_chapter=6, count=2)
        assert len(recent) == 2
        assert recent[0]["chapter_number"] == 4
        assert recent[1]["chapter_number"] == 5

    def test_upsert_updates_existing_summary(self, chroma_store):
        chroma_store.add_chapter_summary(novel_id=3, chapter_number=1, summary="旧摘要")
        chroma_store.add_chapter_summary(novel_id=3, chapter_number=1, summary="新摘要")

        recent = chroma_store.get_recent_summaries(novel_id=3, current_chapter=2, count=1)
        assert len(recent) == 1
        assert recent[0]["summary"] == "新摘要"

    def test_get_all_summaries_sorted_by_chapter(self, chroma_store):
        for num in [3, 1, 2]:
            chroma_store.add_chapter_summary(
                novel_id=4, chapter_number=num, summary=f"第{num}章摘要"
            )

        all_summaries = chroma_store.get_all_summaries(novel_id=4)
        assert len(all_summaries) == 3
        assert [s["chapter_number"] for s in all_summaries] == [1, 2, 3]

    def test_get_all_returns_empty_for_unknown_novel(self, chroma_store):
        result = chroma_store.get_all_summaries(novel_id=9999)
        assert result == []

    def test_summaries_isolated_by_novel_id(self, chroma_store):
        chroma_store.add_chapter_summary(novel_id=10, chapter_number=1, summary="小说A摘要")
        chroma_store.add_chapter_summary(novel_id=11, chapter_number=1, summary="小说B摘要")

        a_summaries = chroma_store.get_all_summaries(novel_id=10)
        b_summaries = chroma_store.get_all_summaries(novel_id=11)
        assert len(a_summaries) == 1
        assert len(b_summaries) == 1
        assert a_summaries[0]["summary"] == "小说A摘要"


class TestCharacterStates:
    def test_add_and_get_latest_state(self, chroma_store):
        chroma_store.add_character_state(
            novel_id=1,
            character_name="张三",
            chapter_number=1,
            state_description="张三初次登场，英姿勃发",
        )

        result = chroma_store.get_latest_character_state(novel_id=1, character_name="张三")
        assert result is not None
        assert result["character_name"] == "张三"
        assert result["state"] == "张三初次登场，英姿勃发"
        assert result["chapter_number"] == 1

    def test_get_latest_returns_highest_chapter_number(self, chroma_store):
        for ch in [1, 5, 3]:
            chroma_store.add_character_state(
                novel_id=1,
                character_name="李四",
                chapter_number=ch,
                state_description=f"第{ch}章的状态",
            )

        result = chroma_store.get_latest_character_state(novel_id=1, character_name="李四")
        assert result["chapter_number"] == 5
        assert result["state"] == "第5章的状态"

    def test_get_latest_nonexistent_character_returns_none(self, chroma_store):
        result = chroma_store.get_latest_character_state(
            novel_id=1, character_name="不存在的角色"
        )
        assert result is None

    def test_characters_isolated_by_novel_id(self, chroma_store):
        chroma_store.add_character_state(
            novel_id=20, character_name="王五", chapter_number=1, state_description="小说A中的王五"
        )
        chroma_store.add_character_state(
            novel_id=21, character_name="王五", chapter_number=1, state_description="小说B中的王五"
        )

        result_a = chroma_store.get_latest_character_state(novel_id=20, character_name="王五")
        result_b = chroma_store.get_latest_character_state(novel_id=21, character_name="王五")
        assert result_a["state"] == "小说A中的王五"
        assert result_b["state"] == "小说B中的王五"

    def test_get_all_character_states(self, chroma_store):
        # Add states for multiple characters at different chapters
        chroma_store.add_character_state(
            novel_id=1, character_name="张三", chapter_number=1, state_description="张三第1章状态"
        )
        chroma_store.add_character_state(
            novel_id=1, character_name="张三", chapter_number=5, state_description="张三第5章状态"
        )
        chroma_store.add_character_state(
            novel_id=1, character_name="李四", chapter_number=3, state_description="李四第3章状态"
        )

        result = chroma_store.get_all_character_states(novel_id=1)
        assert len(result) == 2
        assert result["张三"]["state"] == "张三第5章状态"
        assert result["张三"]["chapter_number"] == 5
        assert result["李四"]["state"] == "李四第3章状态"
        assert result["李四"]["chapter_number"] == 3

    def test_get_all_character_states_empty(self, chroma_store):
        result = chroma_store.get_all_character_states(novel_id=9999)
        assert result == {}

    def test_get_all_character_states_isolated_by_novel(self, chroma_store):
        chroma_store.add_character_state(
            novel_id=30, character_name="赵六", chapter_number=1, state_description="小说A赵六"
        )
        chroma_store.add_character_state(
            novel_id=31, character_name="赵六", chapter_number=1, state_description="小说B赵六"
        )

        result_a = chroma_store.get_all_character_states(novel_id=30)
        result_b = chroma_store.get_all_character_states(novel_id=31)
        assert len(result_a) == 1
        assert result_a["赵六"]["state"] == "小说A赵六"
        assert len(result_b) == 1
        assert result_b["赵六"]["state"] == "小说B赵六"


class TestWorldEvents:
    def test_add_multiple_events_without_id_collision(self, chroma_store):
        for i in range(1, 4):
            chroma_store.add_world_event(
                novel_id=1,
                chapter_number=i,
                event_description=f"世界事件{i}",
                event_type="climax",
                importance="major",
            )

        results = chroma_store.events.get(where={"novel_id": 1})
        assert len(results["ids"]) == 3

    def test_add_event_stores_metadata(self, chroma_store):
        chroma_store.add_world_event(
            novel_id=2,
            chapter_number=3,
            event_description="重要世界事件",
            event_type="reveal",
            importance="critical",
        )

        results = chroma_store.events.get(
            where={"novel_id": 2},
            include=["documents", "metadatas"],
        )
        assert len(results["documents"]) == 1
        assert results["documents"][0] == "重要世界事件"
        assert results["metadatas"][0]["importance"] == "critical"


class TestDeleteNovelData:
    def test_delete_clears_chapter_summaries(self, chroma_store):
        chroma_store.add_chapter_summary(novel_id=5, chapter_number=1, summary="要删除的摘要")
        chroma_store.delete_novel_data(novel_id=5)

        result = chroma_store.get_all_summaries(novel_id=5)
        assert result == []

    def test_delete_clears_character_states(self, chroma_store):
        chroma_store.add_character_state(
            novel_id=5, character_name="王五", chapter_number=1, state_description="状态"
        )
        chroma_store.delete_novel_data(novel_id=5)

        result = chroma_store.get_latest_character_state(novel_id=5, character_name="王五")
        assert result is None

    def test_delete_only_affects_target_novel(self, chroma_store):
        chroma_store.add_chapter_summary(novel_id=10, chapter_number=1, summary="保留的摘要")
        chroma_store.add_chapter_summary(novel_id=11, chapter_number=1, summary="删除的摘要")

        chroma_store.delete_novel_data(novel_id=11)

        kept = chroma_store.get_all_summaries(novel_id=10)
        deleted = chroma_store.get_all_summaries(novel_id=11)
        assert len(kept) == 1
        assert kept[0]["summary"] == "保留的摘要"
        assert len(deleted) == 0

    def test_delete_nonexistent_novel_does_not_raise(self, chroma_store):
        # Deleting data for a novel with no records should not error
        chroma_store.delete_novel_data(novel_id=9999)
