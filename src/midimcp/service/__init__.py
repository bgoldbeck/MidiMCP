"""Composition service: the single mutation authority."""

from midimcp.service.composition import CompositionService, OperationResult, slugify
from midimcp.service.diff import ChangeSummary, check_locks, summarize_changes
from midimcp.service.errors import (
    InvalidOperation,
    InvalidRange,
    LockViolation,
    NoteNotFound,
    ServiceError,
    TrackNotFound,
)

__all__ = [
    "ChangeSummary",
    "CompositionService",
    "InvalidOperation",
    "InvalidRange",
    "LockViolation",
    "NoteNotFound",
    "OperationResult",
    "ServiceError",
    "TrackNotFound",
    "check_locks",
    "slugify",
    "summarize_changes",
]
