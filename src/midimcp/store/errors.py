"""Store errors. Each carries a stable machine-readable ``code`` for API/MCP results."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from midimcp.validation import ValidationReport


class StoreError(Exception):
    code = "STORE_ERROR"

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self)}


class InvalidProjectId(StoreError):
    code = "INVALID_PROJECT_ID"


class ProjectNotFound(StoreError):
    code = "PROJECT_NOT_FOUND"


class ProjectExists(StoreError):
    code = "PROJECT_EXISTS"


class ProjectMismatch(StoreError):
    code = "PROJECT_ID_MISMATCH"


class RevisionNotFound(StoreError):
    code = "REVISION_NOT_FOUND"


class RevisionConflict(StoreError):
    code = "REVISION_CONFLICT"

    def __init__(self, project_id: str, expected: int, current: int) -> None:
        super().__init__(
            f"project {project_id!r} is at revision {current}, not {expected}; "
            "reload with get_project and reapply the change"
        )
        self.project_id = project_id
        self.expected = expected
        self.current = current

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "expectedRevision": self.expected,
            "currentRevision": self.current,
            "retry": "reload the project, reapply the change, and resend with currentRevision",
        }


class ValidationFailed(StoreError):
    code = "VALIDATION_FAILED"

    def __init__(self, report: ValidationReport) -> None:
        codes = ", ".join(sorted({i.code for i in report.errors}))
        super().__init__(f"score has validation errors: {codes}")
        self.report = report

    def to_dict(self) -> dict:
        return {**super().to_dict(), "validation": self.report.to_dict()}


class OperationIdReused(StoreError):
    code = "OPERATION_ID_REUSED"


class UnsupportedFormat(StoreError):
    code = "UNSUPPORTED_FORMAT"


class CorruptProject(StoreError):
    code = "CORRUPT_PROJECT"
