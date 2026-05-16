import uuid
import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import String, ForeignKey, Text, DateTime, Boolean, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.ext.hybrid import hybrid_property

from app.database import Base


def utcnow() -> datetime:
    return datetime.utcnow()


def new_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user_data: Mapped[list["UserData"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    oauth_clients: Mapped[list["OAuthClient"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    def dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "is_active": self.is_active,
            "is_verified": self.is_verified,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class UserData(Base):
    """Key-value data store — replaces Django's UserData ORM model"""
    __tablename__ = "user_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship(back_populates="user_data")

    @hybrid_property
    def json_value(self) -> dict | list:
        return json.loads(self.value) if self.value else {}

    @json_value.setter
    def json_value(self, data: dict | list):
        self.value = json.dumps(data, ensure_ascii=False, default=str)

    def get_value(self) -> dict | list:
        return json.loads(self.value) if self.value else {}

    def set_value(self, data: dict | list):
        self.value = json.dumps(data, ensure_ascii=False, default=str)
        self.updated_at = utcnow()


class EventGroup(Base):
    __tablename__ = "event_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(20), default="#3b82f6")
    typ: Mapped[str] = mapped_column(String(50), default="default")
    working_hours_start: Mapped[str] = mapped_column(String(10), default="09:00")
    working_hours_end: Mapped[str] = mapped_column(String(10), default="18:00")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ShareGroup(Base):
    __tablename__ = "share_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    join_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    members: Mapped[list["GroupMembership"]] = relationship(back_populates="share_group", cascade="all, delete-orphan")


class GroupMembership(Base):
    __tablename__ = "group_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    share_group_id: Mapped[str] = mapped_column(ForeignKey("share_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")  # owner, admin, member
    color: Mapped[str] = mapped_column(String(20), default="")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    share_group: Mapped["ShareGroup"] = relationship(back_populates="members")


class GroupCalendarData(Base):
    __tablename__ = "group_calendar_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    share_group_id: Mapped[str] = mapped_column(ForeignKey("share_groups.id", ondelete="CASCADE"), unique=True, nullable=False)
    events_data: Mapped[str] = mapped_column(Text, default="[]")
    last_synced_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    @hybrid_property
    def events(self) -> list:
        return json.loads(self.events_data) if self.events_data else []

    @events.setter
    def events(self, data: list):
        self.events_data = json.dumps(data, ensure_ascii=False, default=str)


class VerificationCode(Base):
    __tablename__ = "verification_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(6), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, default="email")  # email, password_reset
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    @classmethod
    def expires_in_minutes(cls, minutes: int = 15) -> datetime:
        return utcnow() + timedelta(minutes=minutes)


# Re-export OAuth models
from app.models.oauth import OAuthClient, OAuthAuthorizationCode, OAuthToken  # noqa: E402

__all__ = [
    "User", "UserData", "EventGroup", "ShareGroup", "GroupMembership",
    "GroupCalendarData", "VerificationCode",
    "OAuthClient", "OAuthAuthorizationCode", "OAuthToken",
]
