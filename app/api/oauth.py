import urllib.parse
from fastapi import APIRouter, Depends, HTTPException, status, Query, Form, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.models.oauth import OAuthClient, OAuthToken
from app.schemas import (
    OAuthClientCreate, OAuthClientResponse, OAuthClientListResponse,
    TokenIntrospectionRequest, TokenRevocationRequest,
    MessageResponse,
)
from app.services import oauth_service

router = APIRouter(prefix="/oauth", tags=["OAuth Provider"])

# Available scopes
AVAILABLE_SCOPES = [
    "read:events", "write:events",
    "read:todos", "write:todos",
    "read:reminders", "write:reminders",
    "read:groups", "write:groups",
    "read:calendar", "offline_access",
]


# ---- OAuth Client Management (for authenticated users to register apps) ----

@router.post("/clients", response_model=OAuthClientResponse)
async def register_client(
    data: OAuthClientCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Register a new OAuth client application."""
    invalid_scopes = [s for s in data.default_scopes if s not in AVAILABLE_SCOPES]
    if invalid_scopes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scopes: {', '.join(invalid_scopes)}"
        )

    client = await oauth_service.create_oauth_client(db, current_user.id, {
        "client_name": data.client_name,
        "redirect_uris": data.redirect_uris,
        "grant_types": data.grant_types,
        "default_scopes": data.default_scopes,
        "is_confidential": data.is_confidential,
    })
    return OAuthClientResponse(**client)


@router.get("/clients")
async def list_clients(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all registered OAuth clients for the current user."""
    clients = await oauth_service.list_oauth_clients(db, current_user.id)
    return {"clients": clients, "count": len(clients)}


@router.delete("/clients/{client_id}")
async def delete_client(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a registered OAuth client."""
    success = await oauth_service.delete_oauth_client(db, current_user.id, client_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return {"message": "Client deleted"}


# ---- OAuth 2.0 Authorization Endpoint ----

@router.get("/authorize")
async def authorize(
    request: Request,
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    scope: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    code_challenge: Optional[str] = Query(None),
    code_challenge_method: Optional[str] = Query(None),
    nonce: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    OAuth 2.0 Authorization Endpoint.
    If user is not logged in, redirect to login page.
    If user is logged in, show consent screen (or auto-approve).
    """
    # Validate response_type
    if response_type != "code":
        return _oauth_error(redirect_uri, "unsupported_response_type",
                            f"Only 'code' response type is supported", state)

    # Validate client
    client = await oauth_service.get_oauth_client(db, client_id)
    if not client:
        return _oauth_error(redirect_uri, "unauthorized_client",
                            "Client not found or inactive", state)

    # Validate redirect_uri
    allowed_uris = client.get_redirect_uris()
    if redirect_uri not in allowed_uris:
        return HTMLResponse(
            content=f"<h1>Invalid redirect_uri</h1><p>Allowed: {allowed_uris}</p>",
            status_code=400
        )

    if not current_user:
        # Redirect to login page
        login_url = f"/auth/login?redirect={urllib.parse.quote(str(request.url))}"
        return RedirectResponse(url=login_url, status_code=302)

    # Parse scopes
    requested_scopes = scope.split() if scope else client.get_default_scopes()
    invalid_scopes = [s for s in requested_scopes if s not in AVAILABLE_SCOPES]
    if invalid_scopes:
        return _oauth_error(redirect_uri, "invalid_scope",
                            f"Invalid scopes: {', '.join(invalid_scopes)}", state)

    # Validate PKCE
    if code_challenge:
        if code_challenge_method != "S256":
            return _oauth_error(redirect_uri, "invalid_request",
                                "Only S256 code_challenge_method is supported", state)

    # Create authorization code and redirect
    code = await oauth_service.create_authorization_code(
        db, client_id, current_user.id, redirect_uri,
        requested_scopes, code_challenge, code_challenge_method, nonce
    )

    redirect_params = {"code": code}
    if state:
        redirect_params["state"] = state

    redirect_url = f"{redirect_uri}?{urllib.parse.urlencode(redirect_params)}"
    return RedirectResponse(url=redirect_url, status_code=302)


# ---- OAuth 2.0 Token Endpoint ----

@router.post("/token")
async def token(
    request: Request,
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    client_id: str = Form(...),
    client_secret: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """
    OAuth 2.0 Token Endpoint.
    Supports: authorization_code, refresh_token grant types.
    """
    # Validate client
    client = await oauth_service.get_oauth_client(db, client_id)
    if not client:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "invalid_client", "error_description": "Client not found"}
        )

    # Verify client secret for confidential clients
    if client.is_confidential:
        if not client_secret:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "invalid_client", "error_description": "Client secret required"}
            )
        if not await oauth_service.verify_client_secret(client, client_secret):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "invalid_client", "error_description": "Invalid client secret"}
            )

    # Authorization code flow
    if grant_type == "authorization_code":
        if not code or not redirect_uri:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "invalid_request", "error_description": "code and redirect_uri required"}
            )

        tokens = await oauth_service.exchange_auth_code(db, code, client_id, redirect_uri, code_verifier)
        if not tokens:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "invalid_grant", "error_description": "Invalid or expired authorization code"}
            )
        return tokens

    # Refresh token flow
    elif grant_type == "refresh_token":
        if not refresh_token:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "invalid_request", "error_description": "refresh_token required"}
            )

        tokens = await oauth_service.refresh_access_token(db, refresh_token, client_id)
        if not tokens:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "invalid_grant", "error_description": "Invalid or expired refresh token"}
            )
        return tokens

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": "unsupported_grant_type", "error_description": f"Unsupported grant type: {grant_type}"}
    )


# ---- OAuth 2.0 Token Introspection (RFC 7662) ----

@router.post("/introspect")
async def introspect_token(
    data: TokenIntrospectionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Token introspection endpoint (RFC 7662)."""
    result = await oauth_service.introspect_token(db, data.token)
    return result


# ---- OAuth 2.0 Token Revocation (RFC 7009) ----

@router.post("/revoke")
async def revoke_token(
    data: TokenRevocationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Token revocation endpoint (RFC 7009)."""
    await oauth_service.revoke_token(db, data.token)
    return {}  # Always returns 200 OK


# ---- OAuth 2.0 UserInfo Endpoint (OpenID Connect-style) ----

@router.get("/userinfo")
async def userinfo(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """OAuth UserInfo endpoint — returns authenticated user info."""
    return {
        "sub": str(current_user.id),
        "username": current_user.username,
        "email": current_user.email,
        "email_verified": current_user.is_verified,
    }


# ---- Helper ----

def _oauth_error(redirect_uri: str, error: str, description: str, state: Optional[str] = None):
    params = {"error": error, "error_description": description}
    if state:
        params["state"] = state
    return RedirectResponse(url=f"{redirect_uri}?{urllib.parse.urlencode(params)}", status_code=302)
