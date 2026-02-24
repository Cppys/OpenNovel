"""Tests for workflow routing conditions and state definitions."""

import pytest


class TestRouteAfterInit:
    def test_new_mode_routes_to_plan_novel(self):
        from workflow.conditions import route_after_init
        state = {"mode": "new"}
        assert route_after_init(state) == "plan_novel"

    def test_continue_mode_routes_to_load_chapter_context(self):
        from workflow.conditions import route_after_init
        state = {"mode": "continue"}
        assert route_after_init(state) == "load_chapter_context"

    def test_error_state_routes_to_handle_error_regardless_of_mode(self):
        from workflow.conditions import route_after_init
        state = {"mode": "new", "error": "Something went wrong"}
        assert route_after_init(state) == "handle_error"

    def test_empty_error_string_does_not_route_to_error_handler(self):
        from workflow.conditions import route_after_init
        state = {"mode": "new", "error": ""}
        assert route_after_init(state) == "plan_novel"

    def test_missing_mode_defaults_to_load_chapter_context(self):
        from workflow.conditions import route_after_init
        state = {}
        assert route_after_init(state) == "load_chapter_context"


class TestRouteAfterReview:
    def test_passed_review_routes_to_save_chapter(self):
        from workflow.conditions import route_after_review
        state = {"review_result": {"passed": True}, "revision_count": 0, "max_revisions": 3}
        assert route_after_review(state) == "save_chapter"

    def test_failed_review_under_limit_routes_to_edit(self):
        from workflow.conditions import route_after_review
        state = {"review_result": {"passed": False}, "revision_count": 1, "max_revisions": 3}
        assert route_after_review(state) == "edit_chapter"

    def test_failed_review_at_max_revisions_routes_to_save(self):
        from workflow.conditions import route_after_review
        state = {"review_result": {"passed": False}, "revision_count": 3, "max_revisions": 3}
        assert route_after_review(state) == "save_chapter"

    def test_failed_review_exceeding_max_revisions_routes_to_save(self):
        from workflow.conditions import route_after_review
        state = {"review_result": {"passed": False}, "revision_count": 5, "max_revisions": 3}
        assert route_after_review(state) == "save_chapter"

    def test_empty_review_result_routes_to_edit(self):
        from workflow.conditions import route_after_review
        state = {"review_result": {}, "revision_count": 0, "max_revisions": 3}
        assert route_after_review(state) == "edit_chapter"

    def test_default_max_revisions_is_3(self):
        from workflow.conditions import route_after_review
        # revision_count == 3, no explicit max_revisions (defaults to 3) → save
        state = {"review_result": {"passed": False}, "revision_count": 3}
        assert route_after_review(state) == "save_chapter"


class TestRouteAfterMemoryUpdate:
    def test_at_interval_routes_to_global_review(self):
        from workflow.conditions import route_after_memory_update
        state = {"chapters_written": 5, "global_review_interval": 5}
        assert route_after_memory_update(state) == "global_review"

    def test_not_at_interval_routes_to_advance_chapter(self):
        from workflow.conditions import route_after_memory_update
        state = {"chapters_written": 3, "global_review_interval": 5}
        assert route_after_memory_update(state) == "advance_chapter"

    def test_zero_chapters_written_routes_to_advance(self):
        from workflow.conditions import route_after_memory_update
        state = {"chapters_written": 0, "global_review_interval": 5}
        assert route_after_memory_update(state) == "advance_chapter"

    def test_multiple_of_interval_routes_to_global_review(self):
        from workflow.conditions import route_after_memory_update
        state = {"chapters_written": 10, "global_review_interval": 5}
        assert route_after_memory_update(state) == "global_review"

    def test_non_multiple_of_interval_routes_to_advance(self):
        from workflow.conditions import route_after_memory_update
        state = {"chapters_written": 7, "global_review_interval": 5}
        assert route_after_memory_update(state) == "advance_chapter"

    def test_default_interval_is_5(self):
        from workflow.conditions import route_after_memory_update
        state = {"chapters_written": 5}  # no explicit global_review_interval
        assert route_after_memory_update(state) == "global_review"


class TestRouteAfterAdvance:
    def test_should_stop_flag_routes_to_end(self):
        from workflow.conditions import route_after_advance
        state = {"should_stop": True, "current_chapter": 3, "target_chapters": 10}
        assert route_after_advance(state) == "__end__"

    def test_current_exceeds_target_routes_to_end(self):
        from workflow.conditions import route_after_advance
        state = {"should_stop": False, "current_chapter": 11, "target_chapters": 10}
        assert route_after_advance(state) == "__end__"

    def test_current_within_target_routes_to_load_context(self):
        from workflow.conditions import route_after_advance
        state = {"should_stop": False, "current_chapter": 5, "target_chapters": 10}
        assert route_after_advance(state) == "load_chapter_context"

    def test_current_equals_target_routes_to_load_context(self):
        from workflow.conditions import route_after_advance
        # current == target means current is not yet exceeded
        state = {"should_stop": False, "current_chapter": 10, "target_chapters": 10}
        assert route_after_advance(state) == "load_chapter_context"

    def test_zero_target_routes_to_load_context(self):
        from workflow.conditions import route_after_advance
        # target=0 disables the target check
        state = {"should_stop": False, "current_chapter": 100, "target_chapters": 0}
        assert route_after_advance(state) == "load_chapter_context"

    def test_should_stop_overrides_target_check(self):
        from workflow.conditions import route_after_advance
        state = {"should_stop": True, "current_chapter": 1, "target_chapters": 100}
        assert route_after_advance(state) == "__end__"


class TestNovelWorkflowState:
    def test_state_is_a_plain_dict_at_runtime(self):
        from workflow.state import NovelWorkflowState
        state: NovelWorkflowState = {
            "novel_id": 1,
            "mode": "new",
            "genre": "玄幻",
            "current_chapter": 1,
            "target_chapters": 10,
        }
        assert isinstance(state, dict)
        assert state["novel_id"] == 1
        assert state["mode"] == "new"

    def test_state_supports_partial_initialization(self):
        from workflow.state import NovelWorkflowState
        # total=False makes all fields optional
        state: NovelWorkflowState = {"novel_id": 42}
        assert state.get("mode") is None
        assert state.get("genre") is None

    def test_state_allows_all_declared_fields(self):
        from workflow.state import NovelWorkflowState
        state: NovelWorkflowState = {
            "novel_id": 1,
            "mode": "continue",
            "genre": "都市",
            "premise": "一个普通人的故事",
            "current_chapter": 3,
            "target_chapters": 10,
            "chapters_written": 2,
            "revision_count": 0,
            "max_revisions": 3,
            "global_review_interval": 5,
            "should_stop": False,
            "retry_count": 0,
        }
        assert state["chapters_written"] == 2
        assert state["max_revisions"] == 3
        assert state["should_stop"] is False


class TestWorkflowGraphBuild:
    def test_build_graph_returns_compiled_graph(self):
        from workflow.graph import build_graph
        graph = build_graph()
        assert graph is not None

    def test_build_graph_with_memory_checkpointer(self):
        from langgraph.checkpoint.memory import MemorySaver
        from workflow.graph import build_graph
        checkpointer = MemorySaver()
        graph = build_graph(checkpointer=checkpointer)
        assert graph is not None
