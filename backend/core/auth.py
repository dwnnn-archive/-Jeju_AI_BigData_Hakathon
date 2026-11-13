import secrets

from fastapi import Header, HTTPException, Request


def require_api_key(request: Request, x_api_key: str | None = Header(default=None)):
    configured = request.app.state.settings.api_token
    if configured and configured.get_secret_value():
        if not secrets.compare_digest(x_api_key or "", configured.get_secret_value()):
            raise HTTPException(401, "Valid X-API-Key required")


def require_approver(request: Request, x_approver_token: str | None = Header(default=None)):
    configured = request.app.state.settings.approver_token
    if not configured or not configured.get_secret_value():
        raise HTTPException(503, "Approval is disabled until APPROVER_TOKEN is configured")
    if not secrets.compare_digest(x_approver_token or "", configured.get_secret_value()):
        raise HTTPException(401, "Valid X-Approver-Token required")
    return request.app.state.settings.approver_id
