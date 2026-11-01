"""Domain errors. The API layer maps these to RFC 7807 problem+json responses."""

from typing import Any


class DomainError(Exception):
    status: int = 400
    code: str = "error"
    title: str = "Bad request"

    def __init__(self, detail: str, code: str | None = None, **extra: Any) -> None:
        super().__init__(detail)
        self.detail = detail
        if code:
            self.code = code
        self.extra = extra


class Unauthenticated(DomainError):
    status, code, title = 401, "auth.unauthenticated", "Unauthenticated"


class Forbidden(DomainError):
    status, code, title = 403, "auth.forbidden", "Forbidden"


class NotFound(DomainError):
    status, code, title = 404, "not_found", "Not found"


class Conflict(DomainError):
    status, code, title = 409, "conflict", "Conflict"


class ValidationFailed(DomainError):
    status, code, title = 422, "validation", "Validation failed"
