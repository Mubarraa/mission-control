from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from mission_control.domain.errors import DomainError

PROBLEM = "application/problem+json"


def _problem(status: int, code: str, title: str, detail: str, **extra) -> JSONResponse:
    body = {"type": f"https://mission-control.dev/problems/{code}", "title": title, "status": status}
    body.update({"detail": detail, "code": code, **extra})
    return JSONResponse(body, status_code=status, media_type=PROBLEM)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:
        return _problem(exc.status, exc.code, exc.title, exc.detail, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]), "message": e["msg"]}
            for e in exc.errors()
        ]
        detail = "; ".join(f"{e['field']}: {e['message']}" for e in errors)
        return _problem(422, "validation", "Validation failed", detail, errors=errors)
