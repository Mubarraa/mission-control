from fastapi import FastAPI

from mission_control.api.errors import install_error_handlers
from mission_control.api.routers import assignments, auth, crew, inbox, matching, missions, org, skills
from mission_control.clock import Clock


def create_app(clock: Clock | None = None) -> FastAPI:
    app = FastAPI(
        title="Mission Control API",
        version="0.1.0",
        description="Multi-tenant mission planning, approval and crew matching.",
    )
    app.state.clock = clock or Clock()
    install_error_handlers(app)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # assignments before missions: `/missions/{ref}/assignments` must win over `/missions/{ref}/{action}`
    for module in (auth, org, skills, crew, inbox, assignments, matching, missions):
        app.include_router(module.router, prefix="/v1")

    return app
