import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from filelock import Timeout

from app.api.routes import router
from app.core.config import Settings
from app.services.analysis import AnalysisUnavailable, ConflictError
from app.services.jobs import JobService
from app.services.worker import start_worker


def create_app(settings: Settings | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings
        app.state.service = JobService(settings)
        if settings.worker_enabled:
            start_worker(app.state.service)
        yield
        app.state.service.close()

    app = FastAPI(title="제주 출력제한 대응 API", version="0.1.0", lifespan=lifespan)
    app.include_router(router)

    @app.middleware("http")
    async def no_stale_state(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "jeju-curtailment-backend"}

    @app.get("/ready")
    def readiness():
        service = app.state.service
        ready = bool(service.runner and service.runner.is_alive() and not service.worker_error)
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"ready": ready, "worker_error": service.worker_error},
        )

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse(status_code=404, content={"detail": "Analysis not found"})

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(AnalysisUnavailable)
    async def unavailable(request, exc):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Analysis failed; check provider configuration and input data",
                "analysis_id": exc.run_id,
            },
        )

    @app.exception_handler(Timeout)
    async def busy(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Analysis store busy; retry later"})

    @app.exception_handler(sqlite3.OperationalError)
    async def database_busy(request, exc):
        return JSONResponse(
            status_code=503, content={"detail": "Database unavailable; check state"}
        )

    return app


app = create_app()
