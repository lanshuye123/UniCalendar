import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import User
from app.models.oauth import OAuthClient, OAuthAuthorizationCode, OAuthToken
from app.core.security import hash_password, create_access_token, create_refresh_token


async def create_oauth_client(db: AsyncSession, user_id: int, data: dict) -> dict:
    """Register a new OAuth client application."""
    client_id = _generate_client_id()
    client_secret = _generate_client_secret() if data.get("is_confidential", True) else ""

    import json
    client = OAuthClient(
        client_id=client_id,
        client_secret=client_secret,
        client_name=data["client_name"],
        user_id=user_id,
        redirect_uris=json.dumps(data["redirect_uris"]),
        grant_types=",".join(data.get("grant_types", ["authorization_code", "refresh_token"])),
        default_scopes=",".join(data.get("default_scopes", ["read:events", "read:todos", "read:reminders"])),
        is_confidential=data.get("is_confidential", True),
    )
    db.add(client)
    await db.flush()
    return {
        "client_id": client.client_id,
        "client_secret": client_secret,
        "client_name": client.client_name,
        "redirect_uris": client.get_redirect_uris(),
        "grant_types": client.get_grant_types(),
        "default_scopes": client.get_default_scopes(),
        "is_confidential": client.is_confidential,
        "is_active": client.is_active,
        "created_at": client.created_at,
    }


async def list_oauth_clients(db: AsyncSession, user_id: int) -> list:
    result = await db.execute(
        select(OAuthClient).where(OAuthClient.user_id == user_id)
    )
    clients = result.scalars().all()
    return [
        {
            "client_id": c.client_id,
            "client_name": c.client_name,
            "redirect_uris": c.get_redirect_uris(),
            "is_active": c.is_active,
            "created_at": c.created_at,
        }
        for c in clients
    ]


async def delete_oauth_client(db: AsyncSession, user_id: int, client_id: str) -> bool:
    result = await db.execute(
        select(OAuthClient).where(OAuthClient.client_id == client_id, OAuthClient.user_id == user_id)
    )
    client = result.scalar_one_or_none()
    if not client:
        return False
    await db.delete(client)
    await db.flush()
    return True


async def get_oauth_client(db: AsyncSession, client_id: str) -> Optional[OAuthClient]:
    result = await db.execute(
        select(OAuthClient).where(OAuthClient.client_id == client_id, OAuthClient.is_active == True)
    )
    return result.scalar_one_or_none()


async def verify_client_secret(client: OAuthClient, client_secret: str) -> bool:
    """Verify client secret for confidential clients."""
    if not client.is_confidential:
        return True
    return secrets.compare_digest(client.client_secret, client_secret)


async def create_authorization_code(
    db: AsyncSession,
    client_id: str,
    user_id: int,
    redirect_uri: str,
    scopes: list[str],
    code_challenge: Optional[str] = None,
    code_challenge_method: Optional[str] = None,
    nonce: Optional[str] = None,
) -> str:
    """Create a short-lived authorization code."""
    code = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    auth_code = OAuthAuthorizationCode(
        code=code,
        client_id=client_id,
        user_id=user_id,
        redirect_uri=redirect_uri,
        scopes=",".join(scopes),
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        nonce=nonce,
        expires_at=expires_at,
    )
    db.add(auth_code)
    await db.flush()
    return code


async def exchange_auth_code(
    db: AsyncSession,
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: Optional[str] = None,
) -> Optional[dict]:
    """Exchange an authorization code for access/refresh tokens."""
    result = await db.execute(
        select(OAuthAuthorizationCode).where(
            OAuthAuthorizationCode.code == code,
            OAuthAuthorizationCode.client_id == client_id,
            OAuthAuthorizationCode.used == False,
        )
    )
    auth_code = result.scalar_one_or_none()
    if not auth_code:
        return None

    if auth_code.expires_at < datetime.utcnow():
        return None

    if auth_code.redirect_uri != redirect_uri:
        return None

    # PKCE verification
    if auth_code.code_challenge:
        if not code_verifier:
            return None
        challenge = _compute_code_challenge(code_verifier)
        if challenge != auth_code.code_challenge:
            return None

    # Mark code as used
    auth_code.used = True
    await db.flush()

    # Create tokens
    scopes = auth_code.scopes.split(",") if auth_code.scopes else []
    return await _create_tokens(db, client_id, auth_code.user_id, scopes)


async def refresh_access_token(
    db: AsyncSession,
    refresh_token: str,
    client_id: str,
) -> Optional[dict]:
    """Refresh an access token using a refresh token."""
    result = await db.execute(
        select(OAuthToken).where(
            OAuthToken.refresh_token == refresh_token,
            OAuthToken.client_id == client_id,
            OAuthToken.is_revoked == False,
        )
    )
    token = result.scalar_one_or_none()
    if not token or token.is_refresh_token_expired():
        return None

    # Revoke old tokens
    token.is_revoked = True
    await db.flush()

    scopes = token.get_scopes()
    return await _create_tokens(db, client_id, token.user_id, scopes)


async def revoke_token(db: AsyncSession, token_str: str) -> bool:
    """Revoke an access or refresh token."""
    result = await db.execute(
        select(OAuthToken).where(
            (OAuthToken.access_token == token_str) | (OAuthToken.refresh_token == token_str),
            OAuthToken.is_revoked == False,
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        return False
    token.is_revoked = True
    await db.flush()
    return True


async def introspect_token(db: AsyncSession, token_str: str) -> dict:
    """Introspect an access token — RFC 7662."""
    result = await db.execute(
        select(OAuthToken).where(
            OAuthToken.access_token == token_str,
            OAuthToken.is_revoked == False,
        )
    )
    token = result.scalar_one_or_none()
    if not token or token.is_access_token_expired():
        return {"active": False}

    user_result = await db.execute(select(User).where(User.id == token.user_id))
    user = user_result.scalar_one_or_none()

    return {
        "active": True,
        "client_id": token.client_id,
        "username": user.username if user else None,
        "scope": token.scopes,
        "token_type": token.token_type,
        "exp": int(token.access_token_expires_at.timestamp()),
        "iat": int(token.created_at.timestamp()),
    }


async def clear_expired_tokens(db: AsyncSession):
    """Clean up expired authorization codes and tokens."""
    now = datetime.utcnow()
    # Clean expired auth codes
    result = await db.execute(
        select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.expires_at < now)
    )
    for code in result.scalars().all():
        await db.delete(code)

    # Clean expired tokens
    result = await db.execute(
        select(OAuthToken).where(
            OAuthToken.access_token_expires_at < now,
            OAuthToken.refresh_token_expires_at < now,
        )
    )
    for token in result.scalars().all():
        await db.delete(token)

    await db.flush()


async def _create_tokens(db: AsyncSession, client_id: str, user_id: int, scopes: list[str]) -> dict:
    access_token = secrets.token_urlsafe(32)
    refresh_token = create_refresh_token()
    expires_at = datetime.utcnow() + timedelta(minutes=30)
    refresh_expires_at = datetime.utcnow() + timedelta(days=30)

    token = OAuthToken(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        client_id=client_id,
        user_id=user_id,
        scopes=",".join(scopes),
        access_token_expires_at=expires_at,
        refresh_token_expires_at=refresh_expires_at,
    )
    db.add(token)
    await db.flush()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": 1800,
        "scope": " ".join(scopes),
    }


def _generate_client_id() -> str:
    return secrets.token_urlsafe(24)


def _generate_client_secret() -> str:
    return secrets.token_urlsafe(48)


def _compute_code_challenge(verifier: str) -> str:
    import base64
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
