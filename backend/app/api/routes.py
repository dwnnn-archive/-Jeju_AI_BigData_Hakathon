import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app.core.auth import require_api_key, require_approver
from app.domain.schemas import (
    AnalysisRequest,
    ChatRequest,
    DispatchRequest,
    LoginCheck,
    ReviewDecision,
)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])
Officer = Annotated[str, Depends(require_approver)]


@router.post("/auth/check")
def check_login(body: LoginCheck, actor: Officer):
    """Verify an officer ID + approval token pair without recording any decision."""
    if not secrets.compare_digest(body.approver_id.encode("utf-8"), actor.encode("utf-8")):
        raise HTTPException(401, "Valid officer ID and X-Approver-Token required")
    return {"approver_id": actor}


@router.post("/analyses", status_code=202)
def create_analysis(
    body: AnalysisRequest,
    request: Request,
    idempotency_key: str = Header(min_length=36, max_length=36),
):
    return request.app.state.service.submit(body, idempotency_key)


@router.get("/analyses")
def list_analyses(request: Request, limit: int = Query(default=20, ge=1, le=100)):
    return request.app.state.service.list(limit)


@router.get("/analyses/{run_id}")
def get_analysis(run_id: str, request: Request):
    return request.app.state.service.get(run_id)


@router.post("/analyses/{run_id}/decision")
def decision(run_id: str, body: ReviewDecision, request: Request, actor: Officer):
    return request.app.state.service.decide(
        run_id, body.action, body.reason, body.result_token, actor
    )


@router.post("/analyses/{run_id}/dispatch")
def dispatch(run_id: str, body: DispatchRequest, request: Request, actor: Officer):
    return request.app.state.service.dispatch(run_id, body.result_token)


@router.get("/analyses/{run_id}/audit")
def audit(run_id: str, request: Request):
    return request.app.state.service.audit(run_id)


@router.post("/analyses/{run_id}/chat")
def chat(run_id: str, body: ChatRequest, request: Request):
    return request.app.state.service.chat(run_id, body.message)
