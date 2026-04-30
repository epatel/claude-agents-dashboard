"""Tests for src/domain/item_state.py — the Item finite state machine."""

import pytest

from src.domain.item_state import (
    Event,
    InvalidTransition,
    ItemState,
    TRANSITIONS,
    UnknownStateEncoding,
    can_transition,
    from_columns,
    to_columns,
    transition,
)


# --- column <-> state encoding -------------------------------------------------


class TestColumnEncoding:
    def test_every_state_roundtrips(self):
        for state in ItemState:
            cols = to_columns(state)
            assert from_columns(*cols) is state

    def test_known_db_pairs_map_to_states(self):
        # Pairs taken directly from the audit of workflow_service.py.
        cases = {
            ("todo", None): ItemState.BACKLOG,
            ("todo", "cancelled"): ItemState.CANCELLED,
            ("doing", "queued"): ItemState.QUEUED,
            ("doing", "running"): ItemState.RUNNING,
            ("doing", "paused"): ItemState.PAUSED,
            ("doing", "failed"): ItemState.FAILED,
            ("doing", "conflict"): ItemState.CONFLICT,
            ("doing", "resolving_conflicts"): ItemState.RESOLVING_CONFLICTS,
            ("questions", None): ItemState.CLARIFY,
            ("questions", "merge_blocked"): ItemState.MERGE_BLOCKED,
            ("review", None): ItemState.REVIEW,
            ("done", None): ItemState.DONE,
            ("archive", None): ItemState.ARCHIVED,
        }
        for cols, expected in cases.items():
            assert from_columns(*cols) is expected, f"{cols} should map to {expected}"

    def test_unknown_encoding_raises(self):
        with pytest.raises(UnknownStateEncoding) as exc:
            from_columns("doing", "totally_made_up")
        assert exc.value.column_name == "doing"
        assert exc.value.status == "totally_made_up"

    def test_unknown_column_raises(self):
        with pytest.raises(UnknownStateEncoding):
            from_columns("not_a_column", None)

    def test_no_two_states_share_an_encoding(self):
        encodings = [to_columns(s) for s in ItemState]
        assert len(encodings) == len(set(encodings)), "encoding collision between states"


# --- transition function -------------------------------------------------------


class TestTransition:
    @pytest.mark.parametrize("entry", list(TRANSITIONS.items()))
    def test_every_table_entry_resolves(self, entry):
        (state, event), expected = entry
        assert transition(state, event) is expected

    def test_can_transition_mirrors_table(self):
        for (state, event), _ in TRANSITIONS.items():
            assert can_transition(state, event) is True

    def test_illegal_transition_raises(self):
        with pytest.raises(InvalidTransition) as exc:
            transition(ItemState.DONE, Event.START)
        assert exc.value.state is ItemState.DONE
        assert exc.value.event is Event.START

    def test_can_transition_false_for_unknown(self):
        assert can_transition(ItemState.DONE, Event.START) is False
        assert can_transition(ItemState.ARCHIVED, Event.PAUSE) is False


# --- semantic flows: spot-check the real lifecycles ----------------------------


class TestRealWorldFlows:
    """End-to-end happy-path lifecycles, asserted as state sequences."""

    def _walk(self, start: ItemState, events: list[Event]) -> list[ItemState]:
        path = [start]
        cur = start
        for e in events:
            cur = transition(cur, e)
            path.append(cur)
        return path

    def test_normal_completion(self):
        path = self._walk(ItemState.BACKLOG, [Event.START, Event.COMPLETE, Event.REQUEST_MERGE])
        assert path[-1] is ItemState.DONE

    def test_pause_resume(self):
        path = self._walk(ItemState.BACKLOG, [Event.START, Event.PAUSE, Event.RESUME])
        assert path == [
            ItemState.BACKLOG,
            ItemState.RUNNING,
            ItemState.PAUSED,
            ItemState.RUNNING,
        ]

    def test_clarify_loop(self):
        path = self._walk(ItemState.BACKLOG, [Event.START, Event.ASK, Event.ANSWER])
        assert path[-1] is ItemState.RUNNING

    def test_wip_queue_then_dequeue(self):
        path = self._walk(ItemState.BACKLOG, [Event.ENQUEUE, Event.START])
        assert path == [ItemState.BACKLOG, ItemState.QUEUED, ItemState.RUNNING]

    def test_merge_conflict_recovery(self):
        path = self._walk(
            ItemState.BACKLOG,
            [Event.START, Event.CONFLICT_DETECTED, Event.RESOLVE_CONFLICTS, Event.COMPLETE],
        )
        assert path[-1] is ItemState.REVIEW

    def test_merge_blocked_then_unblocked(self):
        path = self._walk(
            ItemState.BACKLOG,
            [Event.START, Event.COMPLETE, Event.MERGE_BLOCKED, Event.ANSWER, Event.REQUEST_MERGE],
        )
        assert path[-1] is ItemState.DONE

    def test_failed_can_be_requeued(self):
        path = self._walk(
            ItemState.BACKLOG,
            [Event.START, Event.FAIL, Event.REQUEUE, Event.START],
        )
        assert path[-1] is ItemState.RUNNING


# --- structural invariants of the state graph ---------------------------------


class TestGraphInvariants:
    def test_every_state_is_reachable_from_backlog(self):
        seen = {ItemState.BACKLOG}
        frontier = [ItemState.BACKLOG]
        while frontier:
            s = frontier.pop()
            for (src, _ev), dst in TRANSITIONS.items():
                if src is s and dst not in seen:
                    seen.add(dst)
                    frontier.append(dst)
        unreachable = set(ItemState) - seen
        assert not unreachable, f"unreachable states: {unreachable}"

    def test_terminal_states_can_be_requeued_or_archived(self):
        # DONE / CANCELLED / ARCHIVED are the natural absorbing states.
        # All three must offer a way out — otherwise users get stuck items.
        for terminal in (ItemState.DONE, ItemState.CANCELLED, ItemState.ARCHIVED):
            outs = {ev for (s, ev), _ in TRANSITIONS.items() if s is terminal}
            assert outs, f"{terminal} has no outgoing transitions"

    def test_cancel_available_from_every_active_state(self):
        # If an item is mid-flight, the user must always be able to cancel it.
        active = {
            ItemState.BACKLOG, ItemState.QUEUED, ItemState.RUNNING, ItemState.PAUSED,
            ItemState.CLARIFY, ItemState.CONFLICT, ItemState.RESOLVING_CONFLICTS,
            ItemState.FAILED, ItemState.REVIEW, ItemState.MERGE_BLOCKED,
        }
        for s in active:
            assert can_transition(s, Event.CANCEL), f"CANCEL not allowed from {s}"
