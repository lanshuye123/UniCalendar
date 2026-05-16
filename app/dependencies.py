from fastapi import Depends, HTTPException, status, Request, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.database import get_db
from app.models import User, OAuthToken
from app.core.security import verify_jwt

bearer_scheme = HTTPBearer(auto_error=False)

# Legacy compat: also accept "Token <value>" header (old DRF format)
class LegacyTokenBearer(HTTPBearer):
    async def __call__(self, request: Request) -> Optional[HTTPAuthorizationCredentials]:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Token "):
            return HTTPAuthorizationCredentials(scheme="Token", credentials=auth[6:].strip())
        return await super().__call__(request)

token_scheme = LegacyTokenBearer(auto_error=False)


async def _resolve_token(db: AsyncSession, token: str) -> Optional[User]:
    """Resolve any token type to a User. Supports JWT and OAuth access tokens."""
    payload = verify_jwt(token)
    if payload and "sub" in payload:
        user_id = int(payload["sub"])
        result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
        return result.scalar_one_or_none()

    result = await db.execute(
        select(OAuthToken).where(
            OAuthToken.access_token == token,
            OAuthToken.is_revoked == False,
        )
    )
    oauth_token = result.scalar_one_or_none()
    if oauth_token and not oauth_token.is_access_token_expired():
        user_result = await db.execute(select(User).where(User.id == oauth_token.user_id, User.is_active == True))
        return user_result.scalar_one_or_none()

    return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(token_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Authenticate user via Bearer token or Token header (JWT or OAuth)."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user = await _resolve_token(db, credentials.credentials)
    if user:
        return user

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(token_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Like get_current_user but returns None instead of 401."""
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


async def get_user_from_query_or_header(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: str = Query(None, alias="token"),
) -> Optional[User]:
    """Auth via ?token= query param OR Authorization header (for calendar feeds etc)."""
    if token:
        return await _resolve_token(db, token)
    credentials = await token_scheme(request)
    if credentials:
        return await _resolve_token(db, credentials.credentials)
    return None


def require_scope(*required_scopes: str):
    """Dependency that checks OAuth token scopes."""
    async def _check(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(token_scheme),
        db: AsyncSession = Depends(get_db),
    ):
        if credentials is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

        token = credentials.credentials
        payload = verify_jwt(token)
        if payload and "sub" in payload:
            return  # JWT tokens have all scopes

        result = await db.execute(
            select(OAuthToken).where(
                OAuthToken.access_token == token,
                OAuthToken.is_revoked == False,
            )
        )
        oauth_token = result.scalar_one_or_none()
        if not oauth_token or oauth_token.is_access_token_expired():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

        token_scopes = set(oauth_token.get_scopes())
        for scope in required_scopes:
            if scope not in token_scopes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Missing required scope: {scope}"
                )

    return _check
