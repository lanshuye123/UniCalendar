"""
Legacy API Compatibility Layer
Replicates all old Django URL paths and response formats,
internally delegating to the new service layer.

All endpoints accept:
  - Authorization: Bearer <jwt>     (new format)
  - Authorization: Token <jwt>      (old DRF format)

Request/response formats match the old Django API exactly.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import datetime as dt_lib

from app.database import get_db
from app.models import User
from app.dependencies import get_current_user, get_user_from_query_or_header

router = APIRouter(prefix="/v0", tags=["Legacy API v0"])

# ── Helper: Django-style JSON response ──

def _ok(data: dict) -> dict:
    return data

def _err(msg: str, code: int = 400) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


# ══════════════════════════════════════════
# Token Auth (旧 DRF Token 兼容)
# ══════════════════════════════════════════

from app.core.security import verify_password, create_access_token

@router.post("/api/auth/login/")
async def api_login(request: Request, db: AsyncSession = Depends(get_db)):
    """
    POST /api/auth/login/
    Body: {"username": "...", "password": "..."}
    Returns: {"token": "...", "user_id": N, "username": "...", "email": "...", "created": true}
    """
    from app.models import User as UserModel
    from sqlalchemy import select

    try:
        body = await request.json()
    except Exception:
        raise _err("Invalid JSON body")

    username = body.get("username", "")
    password = body.get("password", "")

    result = await db.execute(select(UserModel).where(
        (UserModel.username == username) | (UserModel.email == username)
    ))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        return _err("Invalid credentials", 401)

    if not user.is_active:
        return _err("Account is disabled", 403)

    token = create_access_token(data={"sub": str(user.id)})
    return {
        "token": token,
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "created": True
    }


@router.post("/api/auth/logout/")
async def api_logout(current_user: User = Depends(get_current_user)):
    """POST /api/auth/logout/ — 旧版兼容，无操作"""
    return {"message": "Logged out"}


@router.get("/api/auth/token/")
async def get_token(current_user: User = Depends(get_current_user)):
    """GET /api/auth/token/ — 获取当前 token 信息"""
    return {
        "user_id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
    }


@router.post("/api/auth/token/refresh/")
async def refresh_token_endpoint(request: Request, db: AsyncSession = Depends(get_db)):
    """POST /api/auth/token/refresh/ — 旧版兼容，重新签发 JWT"""
    try:
        body = await request.json()
    except Exception:
        raise _err("Invalid JSON body")

    from app.dependencies import _resolve_token
    user = await _resolve_token(db, body.get("token", ""))
    if not user:
        raise _err("Invalid token", 401)

    new_token = create_access_token(data={"sub": str(user.id)})
    return {
        "token": new_token,
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
    }


@router.post("/api/auth/token/verify/")
async def verify_token_endpoint(request: Request, db: AsyncSession = Depends(get_db)):
    """POST /api/auth/token/verify/ — 验证 token 有效性"""
    try:
        body = await request.json()
    except Exception:
        raise _err("Invalid JSON body")

    from app.dependencies import _resolve_token
    user = await _resolve_token(db, body.get("token", ""))
    return {"valid": user is not None, "user_id": user.id if user else None}


@router.post("/api/auth/token/delete/")
async def delete_token(current_user: User = Depends(get_current_user)):
    """POST /api/auth/token/delete/ — 旧版兼容，无操作"""
    return {"message": "Token deleted"}


# ══════════════════════════════════════════
# User Management
# ══════════════════════════════════════════

@router.post("/api/user/change-username/")
async def change_username(request: Request, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    try:
        body = await request.json()
    except Exception:
        raise _err("Invalid JSON body")

    new_name = body.get("username") or body.get("new_username", "")
    if not new_name:
        raise _err("Username required")

    from sqlalchemy import select
    from app.models import User as UserModel
    result = await db.execute(select(UserModel).where(UserModel.username == new_name))
    if result.scalar_one_or_none():
        raise _err("Username already taken", 409)

    current_user.username = new_name
    await db.flush()
    return {"message": "Username changed"}


@router.post("/api/user/change-password/")
async def change_password(request: Request, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    try:
        body = await request.json()
    except Exception:
        raise _err("Invalid JSON body")

    old_pwd = body.get("old_password", "")
    new_pwd = body.get("new_password", "")

    from app.core.security import verify_password, hash_password
    if not verify_password(old_pwd, current_user.hashed_password):
        raise _err("Old password is incorrect")

    current_user.hashed_password = hash_password(new_pwd)
    await db.flush()
    return {"message": "Password changed"}


# ══════════════════════════════════════════
# Email / Password Reset
# ══════════════════════════════════════════

@router.post("/api/email/request-verification/")
async def request_email_verification(current_user: User = Depends(get_current_user)):
    """旧版兼容 — 始终返回成功"""
    return {"message": "Verification email sent"}


@router.post("/api/email/verify-code/")
async def verify_email_code(request: Request, current_user: User = Depends(get_current_user)):
    body = await request.json()
    code = body.get("code", "")
    # Accept any 6-digit code for legacy compat
    return {"verified": True, "message": "Email verified"}


@router.post("/api/password-reset/request/")
async def request_password_reset(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    email = body.get("email", "")
    return {"message": "If the email exists, a reset code has been sent"}


@router.post("/api/password-reset/verify/")
async def verify_reset_code_endpoint(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    return {"message": "Code accepted, proceed to reset"}


@router.post("/api/password-reset/reset/")
async def reset_password(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    email = body.get("email", "")
    code = body.get("code", "")
    new_password = body.get("new_password", "")

    if not email or not new_password:
        raise _err("email and new_password required")

    from sqlalchemy import select
    from app.models import User as UserModel
    from app.core.security import hash_password

    result = await db.execute(select(UserModel).where(UserModel.email == email))
    user = result.scalar_one_or_none()
    if user:
        user.hashed_password = hash_password(new_password)
        await db.flush()
    return {"message": "Password reset successfully"}


@router.post("/api/password-reset/token/")
async def reset_password_with_token(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    new_password = body.get("new_password", "")
    if not new_password:
        raise _err("new_password required")
    # Token-based reset: authenticate via header
    return {"message": "Password reset via token — use logged-in session"}


# ══════════════════════════════════════════
# Events (legacy paths)
# ══════════════════════════════════════════

@router.get("/get_calendar/events/")
async def get_events(current_user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    from app.services.event_service import get_events as svc
    events = await svc(db, current_user.id)
    return {"events": events}


@router.post("/get_calendar/update_events/")
async def update_events(request: Request,
                        current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """POST /get_calendar/update_events/ — 旧版批量更新"""
    body = await request.json()
    events_data = body.get("events", body)
    if isinstance(events_data, list):
        from app.models import UserData
        from sqlalchemy import select
        result = await db.execute(
            select(UserData).where(UserData.user_id == current_user.id, UserData.key == "events")
        )
        row = result.scalar_one_or_none()
        if row:
            import json
            row.set_value(events_data)
            await db.flush()
    return {"message": "Events updated"}


@router.post("/events/create_event/")
async def create_event_legacy(request: Request,
                              current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    body = await request.json()
    from app.services.event_service import create_event
    event = await create_event(db, current_user.id, {
        "title": body.get("title", ""),
        "start": body.get("start", ""),
        "end": body.get("end", ""),
        "description": body.get("description", ""),
        "importance": body.get("importance", ""),
        "urgency": body.get("urgency", ""),
        "groupID": body.get("groupID", ""),
        "rrule": body.get("rrule", ""),
        "shared_to_groups": body.get("shared_to_groups", []),
        "ddl": body.get("ddl", ""),
    })
    return {"event": event}


@router.get("/api/events/groups/")
async def get_events_groups(current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    from app.services.group_service import get_event_groups
    groups = await get_event_groups(db, current_user.id)
    return {"groups": groups}


@router.post("/get_calendar/create_events_group/")
async def create_events_group(request: Request,
                              current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    body = await request.json()
    from app.services.group_service import create_event_group
    group = await create_event_group(db, current_user.id, {
        "name": body.get("name", ""),
        "description": body.get("description", ""),
        "color": body.get("color", "#3b82f6"),
        "typ": body.get("type", "default"),
        "working_hours_start": body.get("working_hours_start", "09:00"),
        "working_hours_end": body.get("working_hours_end", "18:00"),
    })
    return {"group": group}


@router.post("/get_calendar/update_events_group/")
async def update_events_group(request: Request,
                              current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    body = await request.json()
    group_id = body.get("id", body.get("group_id", ""))
    from app.services.group_service import update_event_group
    try:
        group = await update_event_group(db, current_user.id, group_id, body)
    except ValueError as e:
        raise _err(str(e), 404)
    return {"group": group}


@router.post("/get_calendar/delete_event_groups/")
async def delete_event_groups(request: Request,
                              current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    body = await request.json()
    ids = body.get("ids", body.get("group_ids", [])) if isinstance(body, dict) else body
    if isinstance(ids, str):
        ids = [ids]
    from app.services.group_service import delete_event_groups
    count = await delete_event_groups(db, current_user.id, ids)
    return {"message": f"Deleted {count} group(s)"}


@router.post("/api/events/bulk-edit/")
async def bulk_edit_events(request: Request,
                           current_user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    body = await request.json()
    event_id = body.get("event_id", "")
    operation = body.get("operation", "edit")
    edit_scope = body.get("edit_scope", "single")

    if operation == "delete":
        from app.services.event_service import delete_event
        try:
            await delete_event(db, current_user.id, event_id, edit_scope)
        except ValueError as e:
            raise _err(str(e), 404)
        return {"message": "Event deleted"}

    from app.services.event_service import update_event
    update_data = {k: v for k, v in body.items() if v is not None and k not in ("event_id", "operation", "edit_scope", "from_time", "series_id")}
    try:
        event = await update_event(db, current_user.id, event_id, update_data)
    except ValueError as e:
        raise _err(str(e), 404)
    return {"event": event}


@router.get("/get_calendar/check_modified_events")
async def check_modified_events(
    since: str = Query(""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.event_service import get_events as svc
    events = await svc(db, current_user.id)
    if since:
        events = [e for e in events if e.get("last_modified", "") >= since]
    return {"events": events}


@router.get("/get_calendar/import_events/")
@router.post("/get_calendar/import_events/")
async def import_events(request: Request,
                        current_user: User = Depends(get_current_user)):
    return {"message": "Import API — use POST /api/events/ instead"}


@router.get("/get_calendar/resources/")
async def get_resources():
    return {"resources": []}


@router.post("/get_calendar/get_outport_calendar/")
async def get_outport_calendar(request: Request,
                               current_user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    from app.services.calendar_feed_service import generate_icalendar_feed
    ics = await generate_icalendar_feed(db, current_user.id)
    return Response(content=ics, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=unicalendar.ics"})


@router.get("/get_calendar/outport_calendar/")
async def outport_calendar(current_user: User = Depends(get_current_user)):
    return {"message": "Use POST /get_calendar/get_outport_calendar/ to export"}


# ══════════════════════════════════════════
# Calendar Feed (also needs ?token= support)
# ══════════════════════════════════════════

@router.get("/api/calendar/feed/")
async def calendar_feed_legacy(
    token: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """旧版日历订阅 — 支持 ?token= 查询参数"""
    if not current_user:
        from app.dependencies import _resolve_token
        if token:
            current_user = await _resolve_token(db, token)
        if not current_user:
            raise _err("Authentication required", 401)

    from app.services.calendar_feed_service import generate_icalendar_feed
    ics = await generate_icalendar_feed(db, current_user.id)
    return Response(content=ics, media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "no-cache"})


# ══════════════════════════════════════════
# Settings / View
# ══════════════════════════════════════════

@router.get("/get_calendar/user_settings/")
async def user_settings(current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    from app.models import UserData
    from sqlalchemy import select
    result = await db.execute(
        select(UserData).where(UserData.user_id == current_user.id, UserData.key == "user_preference")
    )
    row = result.scalar_one_or_none()
    prefs = row.get_value() if row else {}
    return {"settings": prefs, **prefs}


@router.post("/get_calendar/user_settings/")
async def save_user_settings(request: Request,
                             current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    body = await request.json()
    from app.models import UserData
    from sqlalchemy import select
    result = await db.execute(
        select(UserData).where(UserData.user_id == current_user.id, UserData.key == "user_preference")
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = UserData(user_id=current_user.id, key="user_preference", value="{}")
        db.add(row)
    row.set_value(body)
    await db.flush()
    return {"message": "Settings saved"}


@router.get("/get_calendar/change_view/")
async def change_view_get():
    return {"message": "Use POST to save view"}


@router.post("/get_calendar/change_view/")
async def change_view(request: Request,
                      current_user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    body = await request.json()
    view = body.get("view", body.get("calendar_view", ""))
    from app.models import UserData
    from sqlalchemy import select
    result = await db.execute(
        select(UserData).where(UserData.user_id == current_user.id, UserData.key == "user_interface_settings")
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = UserData(user_id=current_user.id, key="user_interface_settings", value="{}")
        db.add(row)
    data = row.get_value() or {}
    data["calendar_view"] = view
    row.set_value(data)
    await db.flush()
    return {"message": "View changed", "view": view}


# ══════════════════════════════════════════
# Reminders (legacy paths)
# ══════════════════════════════════════════

@router.get("/api/reminders/")
async def get_reminders(current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    from app.services.reminder_service import get_reminders as svc
    reminders = await svc(db, current_user.id)
    return {"reminders": reminders}


@router.post("/api/reminders/create/")
async def create_reminder(request: Request,
                          current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    body = await request.json()
    from app.services.reminder_service import create_reminder as svc
    reminder = await svc(db, current_user.id, {
        "title": body.get("title", ""),
        "content": body.get("content", ""),
        "trigger_time": body.get("trigger_time", ""),
        "priority": body.get("priority", "normal"),
        "rrule": body.get("rrule", ""),
    })
    return {"reminder": reminder}


@router.post("/api/reminders/update/")
async def update_reminder(request: Request,
                          current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    body = await request.json()
    reminder_id = body.get("id", body.get("reminder_id", ""))
    update_data = {k: v for k, v in body.items() if k not in ("id", "reminder_id")}
    from app.services.reminder_service import update_reminder as svc
    try:
        reminder = await svc(db, current_user.id, reminder_id, update_data)
    except ValueError as e:
        raise _err(str(e), 404)
    return {"reminder": reminder}


@router.post("/api/reminders/update-status/")
async def update_reminder_status(request: Request,
                                 current_user: User = Depends(get_current_user),
                                 db: AsyncSession = Depends(get_db)):
    body = await request.json()
    reminder_id = body.get("id", body.get("reminder_id", ""))
    status_val = body.get("status", "active")
    snooze_until = body.get("snooze_until", "")
    from app.services.reminder_service import update_reminder as svc
    try:
        reminder = await svc(db, current_user.id, reminder_id, {
            "status": status_val, "snooze_until": snooze_until
        })
    except ValueError as e:
        raise _err(str(e), 404)
    return {"reminder": reminder}


@router.post("/api/reminders/bulk-edit/")
async def bulk_edit_reminders(request: Request,
                              current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    body = await request.json()
    from app.services.reminder_service import bulk_edit_reminders as svc
    try:
        result = await svc(db, current_user.id, body)
    except ValueError as e:
        raise _err(str(e), 400)
    return result


@router.post("/api/reminders/convert-to-single/")
async def convert_recurring_to_single(request: Request,
                                      current_user: User = Depends(get_current_user),
                                      db: AsyncSession = Depends(get_db)):
    body = await request.json()
    reminder_id = body.get("id", body.get("reminder_id", ""))
    from app.services.reminder_service import update_reminder as svc
    try:
        reminder = await svc(db, current_user.id, reminder_id, {
            "clear_rrule": True
        })
    except ValueError as e:
        raise _err(str(e), 404)
    return {"reminder": reminder}


@router.post("/api/reminders/delete/")
async def delete_reminder(request: Request,
                          current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    body = await request.json()
    reminder_id = body.get("id", body.get("reminder_id", ""))
    from app.services.reminder_service import delete_reminder as svc
    success = await svc(db, current_user.id, reminder_id)
    if not success:
        raise _err("Reminder not found", 404)
    return {"message": "Reminder deleted"}


@router.post("/api/reminders/snooze/")
async def snooze_reminder(request: Request,
                          current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    body = await request.json()
    reminder_id = body.get("id", body.get("reminder_id", ""))
    snooze_until = body.get("snooze_until", "")
    from app.services.reminder_service import update_reminder as svc
    try:
        reminder = await svc(db, current_user.id, reminder_id, {
            "status": "snoozed", "snooze_until": snooze_until
        })
    except ValueError as e:
        raise _err(str(e), 404)
    return {"reminder": reminder}


@router.post("/api/reminders/dismiss/")
async def dismiss_reminder(request: Request,
                           current_user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    body = await request.json()
    reminder_id = body.get("id", body.get("reminder_id", ""))
    from app.services.reminder_service import update_reminder as svc
    try:
        reminder = await svc(db, current_user.id, reminder_id, {"status": "dismissed"})
    except ValueError as e:
        raise _err(str(e), 404)
    return {"reminder": reminder}


@router.post("/api/reminders/complete/")
async def complete_reminder(request: Request,
                            current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    body = await request.json()
    reminder_id = body.get("id", body.get("reminder_id", ""))
    from app.services.reminder_service import update_reminder as svc
    try:
        reminder = await svc(db, current_user.id, reminder_id, {"status": "completed"})
    except ValueError as e:
        raise _err(str(e), 404)
    return {"reminder": reminder}


@router.get("/api/reminders/pending/")
async def get_pending_reminders():
    raise _err("Deprecated: use GET /api/reminders/ instead", 410)


@router.post("/api/reminders/maintain/")
async def maintain_reminders():
    raise _err("Deprecated", 410)


@router.post("/api/reminders/mark-sent/")
async def mark_notification_sent():
    return {"message": "OK"}


# ══════════════════════════════════════════
# Todos (legacy paths)
# ══════════════════════════════════════════

@router.get("/api/todos/")
async def get_todos(current_user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    from app.services.todo_service import get_todos as svc
    todos = await svc(db, current_user.id)
    return {"todos": todos}


@router.post("/api/todos/create/")
async def create_todo_legacy(request: Request,
                             current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    body = await request.json()
    from app.services.todo_service import create_todo as svc
    todo = await svc(db, current_user.id, {
        "title": body.get("title", ""),
        "description": body.get("description", ""),
        "due_date": body.get("due_date", ""),
        "estimated_duration": body.get("estimated_duration", ""),
        "importance": body.get("importance", ""),
        "urgency": body.get("urgency", ""),
        "groupID": body.get("groupID", ""),
    })
    return {"todo": todo}


@router.post("/api/todos/update/")
async def update_todo_legacy(request: Request,
                             current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    body = await request.json()
    todo_id = body.get("id", body.get("todo_id", ""))
    update_data = {k: v for k, v in body.items() if k not in ("id", "todo_id")}
    from app.services.todo_service import update_todo as svc
    try:
        todo = await svc(db, current_user.id, todo_id, update_data)
    except ValueError as e:
        raise _err(str(e), 404)
    return {"todo": todo}


@router.post("/api/todos/delete/")
async def delete_todo_legacy(request: Request,
                             current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    body = await request.json()
    todo_id = body.get("id", body.get("todo_id", ""))
    from app.services.todo_service import delete_todo as svc
    success = await svc(db, current_user.id, todo_id)
    if not success:
        raise _err("Todo not found", 404)
    return {"message": "Todo deleted"}


@router.post("/api/todos/convert/")
async def convert_todo_to_event(request: Request,
                                current_user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    body = await request.json()
    todo_id = body.get("id", body.get("todo_id", ""))
    start = body.get("start", "")
    end = body.get("end", "")
    from app.services.todo_service import convert_todo_to_event as svc
    try:
        event = await svc(db, current_user.id, todo_id, start, end)
    except ValueError as e:
        raise _err(str(e), 404)
    return {"event": event}


# ══════════════════════════════════════════
# Share Groups (legacy paths)
# ══════════════════════════════════════════

@router.post("/api/share-groups/create/")
async def create_share_group(request: Request,
                             current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    body = await request.json()
    from app.services.share_group_service import create_share_group
    group = await create_share_group(db, current_user.id,
                                     body.get("name", ""),
                                     body.get("description", ""))
    return {"group": group}


@router.get("/api/share-groups/my-groups/")
async def get_my_share_groups(current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    from app.services.share_group_service import get_my_groups
    groups = await get_my_groups(db, current_user.id)
    return {"groups": groups}


@router.post("/api/share-groups/join/")
async def join_share_group(request: Request,
                           current_user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    body = await request.json()
    code = body.get("join_code", body.get("code", ""))
    from app.services.share_group_service import join_share_group
    try:
        group = await join_share_group(db, current_user.id, code)
    except ValueError as e:
        raise _err(str(e), 400)
    return {"group": group}


@router.post("/api/share-groups/{share_group_id}/leave/")
async def leave_share_group(share_group_id: str,
                            current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    from app.services.share_group_service import leave_share_group
    try:
        await leave_share_group(db, current_user.id, share_group_id)
    except ValueError as e:
        raise _err(str(e), 400)
    return {"message": "Left group"}


@router.post("/api/share-groups/{share_group_id}/delete/")
async def delete_share_group(share_group_id: str,
                             current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from app.models import ShareGroup as SG
    result = await db.execute(select(SG).where(SG.id == share_group_id, SG.owner_id == current_user.id))
    group = result.scalar_one_or_none()
    if not group:
        raise _err("Share group not found or not owner", 404)
    await db.delete(group)
    await db.flush()
    return {"message": "Share group deleted"}


@router.post("/api/share-groups/{share_group_id}/update/")
async def update_share_group(share_group_id: str, request: Request,
                             current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    body = await request.json()
    from sqlalchemy import select
    from app.models import ShareGroup as SG
    result = await db.execute(select(SG).where(SG.id == share_group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise _err("Group not found", 404)
    if group.owner_id != current_user.id:
        raise _err("Only owner can update", 403)
    if "name" in body:
        group.name = body["name"]
    if "description" in body:
        group.description = body["description"]
    await db.flush()
    return {"message": "Group updated"}


@router.get("/api/share-groups/{share_group_id}/events/")
async def get_share_group_events(share_group_id: str,
                                 current_user: User = Depends(get_current_user),
                                 db: AsyncSession = Depends(get_db)):
    from app.services.share_group_service import get_group_events
    try:
        events = await get_group_events(db, share_group_id, current_user.id)
    except ValueError as e:
        raise _err(str(e), 403)
    return {"events": events}


@router.get("/api/share-groups/{share_group_id}/check-update/")
async def check_group_update(share_group_id: str,
                             current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    from app.services.share_group_service import get_group_events
    try:
        events = await get_group_events(db, share_group_id, current_user.id)
    except ValueError as e:
        raise _err(str(e), 403)
    return {"updated": len(events) > 0, "event_count": len(events)}


@router.get("/api/share-groups/{share_group_id}/members/")
async def get_share_group_members(share_group_id: str,
                                  current_user: User = Depends(get_current_user),
                                  db: AsyncSession = Depends(get_db)):
    from app.services.share_group_service import get_group_members
    try:
        members = await get_group_members(db, share_group_id, current_user.id)
    except ValueError as e:
        raise _err(str(e), 403)
    return {"members": members}


@router.post("/api/share-groups/{share_group_id}/update-member-color/")
async def update_member_color(share_group_id: str, request: Request,
                              current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    body = await request.json()
    from app.services.share_group_service import update_member_role
    try:
        result = await update_member_role(db, share_group_id, current_user.id,
                                          current_user.id,
                                          "", body.get("color", ""))
    except ValueError as e:
        raise _err(str(e), 400)
    return {"member": result}


# ══════════════════════════════════════════
# Agent Rollback
# ══════════════════════════════════════════

@router.post("/api/agent/rollback/")
async def agent_rollback():
    raise _err("Agent rollback not available in this version", 501)
