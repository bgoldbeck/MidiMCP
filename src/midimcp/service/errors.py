"""Composition service errors (stable codes for MCP/API results)."""

from __future__ import annotations

from midimcp.store.errors import StoreError


class ServiceError(StoreError):
    code = "SERVICE_ERROR"


class TrackNotFound(ServiceError):
    code = "TRACK_NOT_FOUND"


class NoteNotFound(ServiceError):
    code = "NOTE_NOT_FOUND"


class InvalidRange(ServiceError):
    code = "INVALID_RANGE"


class InvalidOperation(ServiceError):
    code = "INVALID_OPERATION"


class LockViolation(ServiceError):
    code = "LOCKED"

    def __init__(self, message: str, lock_ids: list[str]) -> None:
        super().__init__(message)
        self.lock_ids = lock_ids

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "lockIds": self.lock_ids,
            "hint": "locked material can only change after the user unlocks it",
        }
