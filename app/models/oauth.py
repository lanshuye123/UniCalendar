import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import String, ForeignKey, DateTime, Boolean, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class OAuthClient(Base):
    """OAuth 2.0 client application registered with this provider"""
    __tablename__ = "oauth_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    client_secret: Mapped[str] = mapped_column(String(128), nullable=False)
    client_name: Mapped[str] = mapped_column(String(200), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    redirect_uris: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of allowed redirect URIs
    grant_types: Mapped[str] = mapped_column(String(200), default="authorization_code,refresh_token")
    default_scopes: Mapped[str] = mapped_column(String(500), default="read:events read:todos read:reminders")
    is_confidential: Mapped[bool] = mapped_column(Boolean, default=True)  # True = confidential, False = public
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="oauth_clients")

    def get_redirect_uris(self) -> list:
        import json
        return json.loads(self.redirect_uris) if self.redirect_uris else []

    def get_grant_types(self) -> list:
        return [g.strip() for g in self.grant_types.split(",") if g.strip()]

    def get_default_scopes(self) -> list:
        return [s.strip() for s in self.default_scopes.split(",") if s.strip()]


class OAuthAuthorizationCode(Base):
    """Short-lived authorization code issued during OAuth authorization code flow"""
    __tablename__ = "oauth_authorization_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    scopes: Mapped[str] = mapped_column(Text, default="")
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=True)  # PKCE support
    code_challenge_method: Mapped[str] = mapped_column(String(10), nullable=True)  # S256
    nonce: Mapped[str] = mapped_column(String(128), nullable=True)  # OpenID Connect nonce
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OAuthToken(Base):
    """Access and refresh tokens issued by the OAuth provider"""
    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    access_token: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(String(256), unique=True, nullable=True, index=True)
    token_type: Mapped[str] = mapped_column(String(40), default="Bearer")
    client_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scopes: Mapped[str] = mapped_column(Text, default="")
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    access_token_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    refresh_token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def is_access_token_expired(self) -> bool:
        return utcnow() > self.access_token_expires_at

    def is_refresh_token_expired(self) -> bool:
        return self.refresh_token_expires_at is not None and utcnow() > self.refresh_token_expires_at

    def get_scopes(self) -> list:
        return [s.strip() for s in self.scopes.split(",") if s.strip()]
