"""Item lifecycle as an explicit finite state machine.

The domain has 13 reachable states, encoded today in the database as the pair
(items.column_name, items.status). This module is the single source of truth
for what those states are and how items move between them.

Storage stays unchanged: ItemState.from_columns / to_columns translate to and
from the existing two-string encoding. No migration needed.

Adding a state: add to ItemState, add its (column, status) mapping in
_STATE_TO_COLUMNS, and add at least one transition in TRANSITIONS.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Optional


class ItemState(StrEnum):
    BACKLOG = "backlog"
    CANCELLED = "cancelled"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    CONFLICT = "conflict"
    RESOLVING_CONFLICTS = "resolving_conflicts"
    CLARIFY = "clarify"
    MERGE_BLOCKED = "merge_blocked"
    REVIEW = "review"
    DONE = "done"
    ARCHIVED = "archived"


class Event(StrEnum):
    ENQUEUE = "enqueue"
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    REQUEUE = "requeue"
    ASK = "ask"
    ANSWER = "answer"
    CONFLICT_DETECTED = "conflict_detected"
    RESOLVE_CONFLICTS = "resolve_conflicts"
    COMPLETE = "complete"
    REQUEST_MERGE = "request_merge"
    MERGE_BLOCKED = "merge_blocked"
    RETRY_MERGE = "retry_merge"
    REQUEST_CHANGES = "request_changes"
    FAIL = "fail"
    ARCHIVE = "archive"


_STATE_TO_COLUMNS: dict[ItemState, tuple[str, Optional[str]]] = {
    ItemState.BACKLOG: ("todo", None),
    ItemState.CANCELLED: ("todo", "cancelled"),
    ItemState.QUEUED: ("doing", "queued"),
    ItemState.RUNNING: ("doing", "running"),
    ItemState.PAUSED: ("doing", "paused"),
    ItemState.FAILED: ("doing", "failed"),
    ItemState.CONFLICT: ("review", "conflict"),
    ItemState.RESOLVING_CONFLICTS: ("doing", "resolving_conflicts"),
    ItemState.CLARIFY: ("questions", None),
    ItemState.MERGE_BLOCKED: ("questions", "merge_blocked"),
    ItemState.REVIEW: ("review", None),
    ItemState.DONE: ("done", None),
    ItemState.ARCHIVED: ("archive", None),
}

_COLUMNS_TO_STATE: dict[tuple[str, Optional[str]], ItemState] = {
    cols: state for state, cols in _STATE_TO_COLUMNS.items()
}


TRANSITIONS: dict[tuple[ItemState, Event], ItemState] = {
    (ItemState.BACKLOG, Event.START): ItemState.RUNNING,
    (ItemState.BACKLOG, Event.ENQUEUE): ItemState.QUEUED,
    (ItemState.BACKLOG, Event.CANCEL): ItemState.CANCELLED,

    (ItemState.QUEUED, Event.START): ItemState.RUNNING,
    (ItemState.QUEUED, Event.CANCEL): ItemState.CANCELLED,
    (ItemState.QUEUED, Event.REQUEUE): ItemState.BACKLOG,

    (ItemState.RUNNING, Event.PAUSE): ItemState.PAUSED,
    (ItemState.RUNNING, Event.ASK): ItemState.CLARIFY,
    (ItemState.RUNNING, Event.COMPLETE): ItemState.REVIEW,
    (ItemState.RUNNING, Event.FAIL): ItemState.FAILED,
    (ItemState.RUNNING, Event.CANCEL): ItemState.CANCELLED,

    (ItemState.PAUSED, Event.RESUME): ItemState.RUNNING,
    (ItemState.PAUSED, Event.CANCEL): ItemState.CANCELLED,
    (ItemState.PAUSED, Event.REQUEUE): ItemState.BACKLOG,

    (ItemState.CLARIFY, Event.ANSWER): ItemState.RUNNING,
    (ItemState.CLARIFY, Event.CANCEL): ItemState.CANCELLED,

    (ItemState.CONFLICT, Event.RETRY_MERGE): ItemState.REVIEW,
    (ItemState.CONFLICT, Event.REQUEUE): ItemState.BACKLOG,
    (ItemState.CONFLICT, Event.CANCEL): ItemState.CANCELLED,

    (ItemState.RESOLVING_CONFLICTS, Event.COMPLETE): ItemState.REVIEW,
    (ItemState.RESOLVING_CONFLICTS, Event.CONFLICT_DETECTED): ItemState.CONFLICT,
    (ItemState.RESOLVING_CONFLICTS, Event.FAIL): ItemState.FAILED,
    (ItemState.RESOLVING_CONFLICTS, Event.CANCEL): ItemState.CANCELLED,

    (ItemState.FAILED, Event.REQUEUE): ItemState.BACKLOG,
    (ItemState.FAILED, Event.START): ItemState.RUNNING,
    (ItemState.FAILED, Event.CANCEL): ItemState.CANCELLED,

    (ItemState.REVIEW, Event.REQUEST_MERGE): ItemState.DONE,
    (ItemState.REVIEW, Event.MERGE_BLOCKED): ItemState.MERGE_BLOCKED,
    (ItemState.REVIEW, Event.REQUEST_CHANGES): ItemState.RUNNING,
    (ItemState.REVIEW, Event.RESOLVE_CONFLICTS): ItemState.RESOLVING_CONFLICTS,
    (ItemState.REVIEW, Event.CONFLICT_DETECTED): ItemState.CONFLICT,
    (ItemState.REVIEW, Event.REQUEUE): ItemState.BACKLOG,
    (ItemState.REVIEW, Event.CANCEL): ItemState.CANCELLED,

    (ItemState.MERGE_BLOCKED, Event.RETRY_MERGE): ItemState.REVIEW,
    (ItemState.MERGE_BLOCKED, Event.CANCEL): ItemState.CANCELLED,

    (ItemState.DONE, Event.ARCHIVE): ItemState.ARCHIVED,
    (ItemState.DONE, Event.REQUEUE): ItemState.BACKLOG,

    (ItemState.CANCELLED, Event.REQUEUE): ItemState.BACKLOG,
    (ItemState.CANCELLED, Event.START): ItemState.RUNNING,
    (ItemState.ARCHIVED, Event.REQUEUE): ItemState.BACKLOG,
}


class InvalidTransition(Exception):
    def __init__(self, state: ItemState, event: Event):
        super().__init__(f"no transition from {state.value} on {event.value}")
        self.state = state
        self.event = event


class UnknownStateEncoding(Exception):
    def __init__(self, column_name: str, status: Optional[str]):
        super().__init__(
            f"no ItemState for (column_name={column_name!r}, status={status!r})"
        )
        self.column_name = column_name
        self.status = status


def transition(state: ItemState, event: Event) -> ItemState:
    try:
        return TRANSITIONS[(state, event)]
    except KeyError:
        raise InvalidTransition(state, event) from None


def can_transition(state: ItemState, event: Event) -> bool:
    return (state, event) in TRANSITIONS


def to_columns(state: ItemState) -> tuple[str, Optional[str]]:
    return _STATE_TO_COLUMNS[state]


def from_columns(column_name: str, status: Optional[str]) -> ItemState:
    try:
        return _COLUMNS_TO_STATE[(column_name, status)]
    except KeyError:
        raise UnknownStateEncoding(column_name, status) from None
