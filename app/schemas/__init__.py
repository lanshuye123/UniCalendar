from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Any
from datetime import datetime


# ---- Auth ----
class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=150)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class UserLogin(BaseModel):
    login: str = Field(..., description="Username or email")
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool
    is_verified: bool
    created_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetVerify(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=6, max_length=128)


class ChangePassword(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=128)


class ChangeUsername(BaseModel):
    new_username: str = Field(..., min_length=2, max_length=150)


class EmailVerificationRequest(BaseModel):
    """Request to send a verification email"""


class EmailVerificationVerify(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


# ---- Events ----
class EventCreate(BaseModel):
    title: str = Field(..., max_length=500)
    start: str = Field(..., description="ISO datetime string")
    end: str = Field(..., description="ISO datetime string")
    description: str = ""
    importance: str = ""  # high, medium, low
    urgency: str = ""  # high, medium, low
    groupID: str = ""
    rrule: str = ""
    shared_to_groups: List[str] = []
    ddl: str = ""


class EventUpdate(BaseModel):
    title: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    description: Optional[str] = None
    importance: Optional[str] = None
    urgency: Optional[str] = None
    groupID: Optional[str] = None
    rrule: Optional[str] = None
    shared_to_groups: Optional[List[str]] = None
    ddl: Optional[str] = None
    update_scope: str = "single"  # single, all, future
    clear_rrule: bool = False


class BulkEditRequest(BaseModel):
    event_id: str
    operation: str = "edit"  # edit, delete
    edit_scope: str = "single"  # single, all, future, from_time
    title: Optional[str] = None
    description: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    importance: Optional[str] = None
    urgency: Optional[str] = None
    groupID: Optional[str] = None
    rrule: Optional[str] = None
    ddl: Optional[str] = None
    shared_to_groups: Optional[List[str]] = None
    from_time: Optional[str] = None
    series_id: Optional[str] = None


class EventDelete(BaseModel):
    event_id: str
    delete_scope: str = "single"  # single, all, future


# ---- Todos ----
class TodoCreate(BaseModel):
    title: str = Field(..., max_length=500)
    description: str = ""
    due_date: str = ""
    estimated_duration: str = ""
    importance: str = ""
    urgency: str = ""
    groupID: str = ""


class TodoUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    estimated_duration: Optional[str] = None
    importance: Optional[str] = None
    urgency: Optional[str] = None
    groupID: Optional[str] = None
    status: Optional[str] = None  # pending, in_progress, completed, cancelled


class TodoConvert(BaseModel):
    todo_id: str
    start: str = ""
    end: str = ""


# ---- Reminders ----
class ReminderCreate(BaseModel):
    title: str = Field(..., max_length=500)
    content: str = ""
    trigger_time: str = Field(..., description="ISO datetime string")
    priority: str = "normal"  # low, normal, high, urgent
    rrule: str = ""


class ReminderUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    trigger_time: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None  # active, snoozed, dismissed, completed
    rrule: Optional[str] = None
    clear_rrule: bool = False


class ReminderBulkEdit(BaseModel):
    reminder_id: str
    operation: str = "edit"  # edit, delete
    edit_scope: str = "single"  # single, all, from_this, from_time
    title: Optional[str] = None
    content: Optional[str] = None
    trigger_time: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    rrule: Optional[str] = None
    from_time: Optional[str] = None
    series_id: Optional[str] = None


class ReminderStatusUpdate(BaseModel):
    reminder_id: str
    status: str  # snoozed, dismissed, completed
    snooze_until: Optional[str] = None


# ---- Event Groups ----
class EventGroupCreate(BaseModel):
    name: str = Field(..., max_length=200)
    description: str = ""
    color: str = "#3b82f6"
    typ: str = "default"
    working_hours_start: str = "09:00"
    working_hours_end: str = "18:00"


class EventGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    typ: Optional[str] = None
    working_hours_start: Optional[str] = None
    working_hours_end: Optional[str] = None


# ---- Share Groups ----
class ShareGroupCreate(BaseModel):
    name: str = Field(..., max_length=200)
    description: str = ""


class ShareGroupJoin(BaseModel):
    join_code: str = Field(..., max_length=20)


class ShareGroupMemberUpdate(BaseModel):
    user_id: int
    role: str = "member"  # admin, member
    color: str = ""


# ---- OAuth ----
class OAuthClientCreate(BaseModel):
    client_name: str = Field(..., min_length=1, max_length=200)
    redirect_uris: List[str] = Field(..., min_length=1)
    grant_types: List[str] = ["authorization_code", "refresh_token"]
    default_scopes: List[str] = ["read:events", "read:todos", "read:reminders"]
    is_confidential: bool = True


class OAuthClientResponse(BaseModel):
    client_id: str
    client_secret: str  # Only shown on creation
    client_name: str
    redirect_uris: list
    grant_types: list
    default_scopes: list
    is_confidential: bool
    is_active: bool
    created_at: Optional[datetime] = None


class OAuthClientListResponse(BaseModel):
    client_id: str
    client_name: str
    redirect_uris: list
    is_active: bool
    created_at: Optional[datetime] = None


class TokenIntrospectionRequest(BaseModel):
    token: str
    token_type_hint: Optional[str] = None


class TokenRevocationRequest(BaseModel):
    token: str
    token_type_hint: Optional[str] = None


# ---- Generic ----
class MessageResponse(BaseModel):
    message: str
    detail: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    error_description: Optional[str] = None
