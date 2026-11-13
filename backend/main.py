from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from filelock import Timeout

from backend.api.routes import router
from backend.core.config import Settings
from backend.services.analysis import AnalysisService, AnalysisUnavailable, ConflictError


def create_app(settings: Settings | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings
        app.state.service = AnalysisService(settings)
        yield
        app.state.service.close()

    app = FastAPI(title="제주 출력제한 대응 API", version="0.1.0", lifespan=lifespan)
    app.include_router(router)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "jeju-curtailment-backend"}

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

    return app


app = create_app()
