from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from backend.core.auth import require_api_key, require_approver
from backend.domain.schemas import AnalysisRequest, ChatRequest, Decision

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])
Officer = Annotated[str, Depends(require_approver)]


@router.post("/analyses", status_code=201)
def create_analysis(body: AnalysisRequest, request: Request):
    return request.app.state.service.create(body)


@router.get("/analyses")
def list_analyses(request: Request, limit: int = Query(default=20, ge=1, le=100)):
    return request.app.state.service.list(limit)


@router.get("/analyses/{run_id}")
def get_analysis(run_id: str, request: Request):
    return request.app.state.service.get(run_id)


@router.post("/analyses/{run_id}/decision")
def decision(run_id: str, body: Decision, request: Request, actor: Officer):
    return request.app.state.service.decide(run_id, body, actor)


@router.post("/analyses/{run_id}/dispatch")
def dispatch(run_id: str, request: Request, actor: Officer):
    return request.app.state.service.dispatch(run_id)


@router.get("/analyses/{run_id}/audit")
def audit(run_id: str, request: Request):
    return request.app.state.service.audit(run_id)


@router.post("/analyses/{run_id}/chat")
def chat(run_id: str, body: ChatRequest, request: Request):
    return request.app.state.service.chat(run_id, body.message)
