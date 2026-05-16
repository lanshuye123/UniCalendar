"""
UniCalendar MCP Server
Standalone MCP service exposing calendar management tools to external clients
(Claude Desktop, Copilot, etc.) via MCP protocol.

Uses FastMCP library. Supports stdio mode (local) and HTTP mode (remote).
All Django dependencies removed — uses SQLAlchemy async data layer directly.

Usage:
  stdio mode (Claude Desktop):
    python mcp_server.py --token <JWT_TOKEN>

  HTTP mode (remote):
    python mcp_server.py --http --port 8100 --no-auth  (dev, requires --token)
    python mcp_server.py --http --port 8100             (prod, uses HTTP auth)
"""

import os
import sys
import json
import asyncio
import argparse
import contextvars
import datetime as dt_lib
from typing import Optional, List

# ---- FastMCP ----
from mcp.server.fastmcp import FastMCP

# ---- Internal imports ----
from app.database import async_session
from app.core.security import verify_jwt
from app.models import User
from sqlalchemy import select

# ---- Globals ----
_stdio_user_id: Optional[int] = None
_current_user_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    'mcp_current_user_id', default=None
)

# ---- Helpers ----

async def _get_user_id_from_token(token_str: str) -> Optional[int]:
    payload = verify_jwt(token_str)
    if payload and "sub" in payload:
        user_id = int(payload["sub"])
        async with async_session() as db:
            result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
            user = result.scalar_one_or_none()
            if user:
                return user_id
    return None


async def _get_current_user_id() -> int:
    uid = _current_user_var.get(None)
    if uid is not None:
        return uid
    if _stdio_user_id is not None:
        return _stdio_user_id
    raise ValueError("No authenticated user. Provide --token or Authorization header.")


async def _run_service(func, *args, **kwargs):
    """Run an async service function with the current user."""
    user_id = await _get_current_user_id()
    async with async_session() as db:
        return await func(db, user_id, *args, **kwargs)


# ---- MCP Server ----
mcp = FastMCP(
    "UniCalendar",
    instructions="UniCalendar calendar management MCP server — search, create, update, delete events/todos/reminders.",
    stateless_http=True,
    json_response=True,
)


# ============================================================
# MCP Tools
# ============================================================

@mcp.tool()
async def search_items(
    item_type: str = "all",
    keyword: Optional[str] = None,
    time_range: Optional[str] = None,
    status: Optional[str] = None,
    event_group: Optional[str] = None,
    limit: int = 20,
) -> str:
    """
    Search for events, todos, reminders.

    Args:
        item_type: "event", "todo", "reminder", or "all"
        keyword: Search keyword (title/description match)
        time_range: Preset like "today", "tomorrow", "this_week", "next_week", "this_month"
                    or Chinese: "今天","明天","本周","下周","本月"
                    or custom: "2024-01-01 ~ 2024-01-31"
        status: Status filter
        event_group: Event group filter (name or UUID)
        limit: Max results (default 20)
    """
    results = {"events": [], "todos": [], "reminders": []}
    user_id = await _get_current_user_id()

    async with async_session() as db:
        if item_type in ("all", "event"):
            from app.services.event_service import get_events
            events = await get_events(db, user_id)
            if keyword:
                kw = keyword.lower()
                events = [e for e in events if kw in (e.get("title", "") + e.get("description", "")).lower()]
            if time_range:
                events = _filter_by_time(events, time_range, time_key="start")
            if event_group:
                events = [e for e in events if e.get("groupID") == event_group]
            results["events"] = events[:limit]

        if item_type in ("all", "todo"):
            from app.services.todo_service import get_todos
            todos = await get_todos(db, user_id)
            if keyword:
                kw = keyword.lower()
                todos = [t for t in todos if kw in (t.get("title", "") + t.get("description", "")).lower()]
            if status:
                todos = [t for t in todos if t.get("status") == status]
            results["todos"] = todos[:limit]

        if item_type in ("all", "reminder"):
            from app.services.reminder_service import get_reminders
            reminders = await get_reminders(db, user_id)
            if keyword:
                kw = keyword.lower()
                reminders = [r for r in reminders if kw in (r.get("title", "") + r.get("content", "")).lower()]
            if status:
                reminders = [r for r in reminders if r.get("status") == status]
            if time_range:
                reminders = _filter_by_time(reminders, time_range, time_key="trigger_time")
            results["reminders"] = reminders[:limit]

    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool()
async def create_item(
    item_type: str,
    title: str,
    description: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    event_group: Optional[str] = None,
    importance: Optional[str] = None,
    urgency: Optional[str] = None,
    shared_to_groups: Optional[List[str]] = None,
    ddl: Optional[str] = None,
    due_date: Optional[str] = None,
    priority: Optional[str] = None,
    trigger_time: Optional[str] = None,
    content: Optional[str] = None,
    repeat: Optional[str] = None,
) -> str:
    """
    Create an event, todo, or reminder.

    Args:
        item_type: "event", "todo", or "reminder"
        title: Title (required)
        description: Description/notes
        start: Event start time (format: "2024-01-15T09:00")
        end: Event end time
        event_group: Event group (name will be resolved to UUID)
        importance: "high", "medium", "low"
        urgency: "high", "medium", "low"
        shared_to_groups: List of share group names/IDs
        ddl: Deadline date for event
        due_date: Todo due date (format: "2024-01-15")
        priority: Priority ("high","medium","low" for todos, "high","normal","low" for reminders)
        trigger_time: Reminder trigger time (format: "2024-01-15T09:00")
        content: Reminder content
        repeat: Repeat rule (simple: "daily","weekly","monthly","weekdays" or RRULE)
    """
    user_id = await _get_current_user_id()
    async with async_session() as db:
        if item_type == "event":
            from app.services.event_service import create_event
            event_data = {
                "title": title, "start": start or dt_lib.datetime.now().strftime("%Y-%m-%dT%H:%M"),
                "end": end or (dt_lib.datetime.now() + dt_lib.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
                "description": description or "", "importance": importance or "", "urgency": urgency or "",
                "groupID": event_group or "", "rrule": _normalize_repeat(repeat) if repeat else "",
                "shared_to_groups": shared_to_groups or [], "ddl": ddl or "",
            }
            result = await create_event(db, user_id, event_data)
            return json.dumps({"event": result}, ensure_ascii=False, indent=2)

        elif item_type == "todo":
            from app.services.todo_service import create_todo
            todo_data = {
                "title": title, "description": description or "",
                "due_date": due_date or "", "estimated_duration": "",
                "importance": importance or "", "urgency": urgency or "",
                "groupID": event_group or "",
            }
            result = await create_todo(db, user_id, todo_data)
            return json.dumps({"todo": result}, ensure_ascii=False, indent=2)

        elif item_type == "reminder":
            from app.services.reminder_service import create_reminder
            rem_data = {
                "title": title, "content": content or description or "",
                "trigger_time": trigger_time or dt_lib.datetime.now().strftime("%Y-%m-%dT%H:%M"),
                "priority": priority or "normal",
                "rrule": _normalize_repeat(repeat) if repeat else "",
            }
            result = await create_reminder(db, user_id, rem_data)
            return json.dumps({"reminder": result}, ensure_ascii=False, indent=2)

    return json.dumps({"error": "Unknown item_type"}, ensure_ascii=False)


@mcp.tool()
async def update_item(
    identifier: str,
    item_type: Optional[str] = None,
    edit_scope: str = "single",
    title: Optional[str] = None,
    description: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    event_group: Optional[str] = None,
    importance: Optional[str] = None,
    urgency: Optional[str] = None,
    priority: Optional[str] = None,
    status: Optional[str] = None,
    trigger_time: Optional[str] = None,
    content: Optional[str] = None,
    clear_repeat: bool = False,
) -> str:
    """
    Update an event, todo, or reminder. Only pass fields you want to change.

    Args:
        identifier: Item ID (UUID) or title for fuzzy match
        item_type: "event", "todo", "reminder" (optional, helps disambiguate)
        edit_scope: For recurring items — "single", "all", "future"
        title: New title
        description: New description
        start: New start time
        end: New end time
        event_group: New event group
        importance: New importance level
        urgency: New urgency level
        priority: New priority level
        status: New status ("pending","completed" for todos; "active","snoozed","dismissed","completed" for reminders)
        trigger_time: New reminder trigger time
        content: New reminder content
        clear_repeat: Set True to clear repeat rule
    """
    user_id = await _get_current_user_id()
    async with async_session() as db:
        update_data = {k: v for k, v in {
            "title": title, "description": description, "start": start, "end": end,
            "groupID": event_group, "importance": importance, "urgency": urgency,
            "priority": priority, "status": status, "trigger_time": trigger_time,
            "content": content,
        }.items() if v is not None}
        if clear_repeat:
            update_data["clear_rrule"] = True

        # Try to find the item by ID or fuzzy title
        actual_id = None
        actual_type = item_type

        # Try as event
        if not actual_type or actual_type == "event":
            from app.services.event_service import get_events, update_event
            events = await get_events(db, user_id)
            for e in events:
                if e.get("id") == identifier or e.get("title") == identifier:
                    actual_id = e["id"]
                    actual_type = "event"
                    break
            if actual_id and actual_type == "event":
                result = await update_event(db, user_id, actual_id, update_data)
                return json.dumps({"event": result}, ensure_ascii=False, indent=2)

        # Try as todo
        if not actual_type or actual_type == "todo":
            from app.services.todo_service import get_todos, update_todo
            todos = await get_todos(db, user_id)
            for t in todos:
                if t.get("id") == identifier or t.get("title") == identifier:
                    actual_id = t["id"]
                    actual_type = "todo"
                    break
            if actual_id and actual_type == "todo":
                result = await update_todo(db, user_id, actual_id, update_data)
                return json.dumps({"todo": result}, ensure_ascii=False, indent=2)

        # Try as reminder
        if not actual_type or actual_type == "reminder":
            from app.services.reminder_service import get_reminders, update_reminder
            reminders = await get_reminders(db, user_id)
            for r in reminders:
                if r.get("id") == identifier or r.get("title") == identifier:
                    actual_id = r["id"]
                    actual_type = "reminder"
                    break
            if actual_id and actual_type == "reminder":
                result = await update_reminder(db, user_id, actual_id, update_data)
                return json.dumps({"reminder": result}, ensure_ascii=False, indent=2)

    return json.dumps({"error": f"Item not found: {identifier}"}, ensure_ascii=False)


@mcp.tool()
async def delete_item(identifier: str, item_type: Optional[str] = None, delete_scope: str = "single") -> str:
    """
    Delete an event, todo, or reminder.

    Args:
        identifier: Item ID (UUID) or title
        item_type: "event", "todo", "reminder" (optional)
        delete_scope: For recurring items — "single", "all", "future"
    """
    user_id = await _get_current_user_id()
    async with async_session() as db:
        # Try each type
        types_to_try = [item_type] if item_type else ["event", "todo", "reminder"]
        for typ in types_to_try:
            if typ == "event":
                from app.services.event_service import get_events, delete_event
                events = await get_events(db, user_id)
                target = next((e for e in events if e.get("id") == identifier or e.get("title") == identifier), None)
                if target:
                    try:
                        await delete_event(db, user_id, target["id"], delete_scope)
                        return json.dumps({"deleted": True, "type": "event", "id": target["id"]})
                    except ValueError:
                        pass
            elif typ == "todo":
                from app.services.todo_service import get_todos, delete_todo
                todos = await get_todos(db, user_id)
                target = next((t for t in todos if t.get("id") == identifier or t.get("title") == identifier), None)
                if target:
                    await delete_todo(db, user_id, target["id"])
                    return json.dumps({"deleted": True, "type": "todo", "id": target["id"]})
            elif typ == "reminder":
                from app.services.reminder_service import get_reminders, delete_reminder
                reminders = await get_reminders(db, user_id)
                target = next((r for r in reminders if r.get("id") == identifier or r.get("title") == identifier), None)
                if target:
                    await delete_reminder(db, user_id, target["id"])
                    return json.dumps({"deleted": True, "type": "reminder", "id": target["id"]})

    return json.dumps({"error": f"Item not found: {identifier}"}, ensure_ascii=False)


@mcp.tool()
async def complete_todo(identifier: str) -> str:
    """
    Mark a todo as completed.

    Args:
        identifier: Todo ID (UUID) or title
    """
    user_id = await _get_current_user_id()
    async with async_session() as db:
        from app.services.todo_service import get_todos, update_todo
        todos = await get_todos(db, user_id)
        target = next((t for t in todos if t.get("id") == identifier or t.get("title") == identifier), None)
        if target:
            result = await update_todo(db, user_id, target["id"], {"status": "completed"})
            return json.dumps({"todo": result}, ensure_ascii=False, indent=2)
    return json.dumps({"error": f"Todo not found: {identifier}"}, ensure_ascii=False)


@mcp.tool()
async def get_event_groups() -> str:
    """Get all event groups for the authenticated user."""
    user_id = await _get_current_user_id()
    async with async_session() as db:
        from app.services.group_service import get_event_groups
        groups = await get_event_groups(db, user_id)
        return json.dumps({"groups": groups}, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_share_groups() -> str:
    """Get all share groups the user belongs to."""
    user_id = await _get_current_user_id()
    async with async_session() as db:
        from app.services.share_group_service import get_my_groups
        groups = await get_my_groups(db, user_id)
        return json.dumps({"groups": groups}, ensure_ascii=False, indent=2)


@mcp.tool()
async def check_schedule_conflicts(time_range: str = "this_week", include_share_groups: bool = True) -> str:
    """
    Check for schedule conflicts in a given time range.

    Args:
        time_range: "today", "this_week", "next_week", "this_month"
        include_share_groups: Whether to include shared group events
    """
    user_id = await _get_current_user_id()
    async with async_session() as db:
        from app.services.event_service import get_events
        events = await get_events(db, user_id)
        filtered = _filter_by_time(events, time_range, time_key="start")

        # Sort by start time and check for overlaps
        sorted_events = sorted(filtered, key=lambda e: e.get("start", ""))
        conflicts = []
        for i in range(len(sorted_events)):
            for j in range(i + 1, len(sorted_events)):
                a = sorted_events[i]
                b = sorted_events[j]
                try:
                    a_start = dt_lib.datetime.fromisoformat(a["start"].replace("Z", ""))
                    a_end = dt_lib.datetime.fromisoformat(a["end"].replace("Z", ""))
                    b_start = dt_lib.datetime.fromisoformat(b["start"].replace("Z", ""))
                    b_end = dt_lib.datetime.fromisoformat(b["end"].replace("Z", ""))
                    if a_start < b_end and b_start < a_end:
                        conflicts.append({
                            "event_a": a.get("title"),
                            "event_b": b.get("title"),
                            "overlap": f"{a['start']} - {a['end']} overlaps with {b['start']} - {b['end']}"
                        })
                except Exception:
                    continue

        return json.dumps({
            "time_range": time_range,
            "total_events": len(filtered),
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
        }, ensure_ascii=False, indent=2)


# ---- Helpers ----

def _filter_by_time(items: list, time_range: str, time_key: str = "start") -> list:
    now = dt_lib.datetime.now()
    today = now.date()
    tr = time_range.lower().strip()

    range_map = {
        "today": (dt_lib.datetime.combine(today, dt_lib.time(0, 0)),
                   dt_lib.datetime.combine(today, dt_lib.time(23, 59, 59))),
        "tomorrow": (dt_lib.datetime.combine(today + dt_lib.timedelta(days=1), dt_lib.time(0, 0)),
                      dt_lib.datetime.combine(today + dt_lib.timedelta(days=1), dt_lib.time(23, 59, 59))),
        "今天": (dt_lib.datetime.combine(today, dt_lib.time(0, 0)),
                  dt_lib.datetime.combine(today, dt_lib.time(23, 59, 59))),
        "明天": (dt_lib.datetime.combine(today + dt_lib.timedelta(days=1), dt_lib.time(0, 0)),
                  dt_lib.datetime.combine(today + dt_lib.timedelta(days=1), dt_lib.time(23, 59, 59))),
        "this_week": (dt_lib.datetime.combine(today - dt_lib.timedelta(days=today.weekday()), dt_lib.time(0, 0)),
                       dt_lib.datetime.combine(today + dt_lib.timedelta(days=6 - today.weekday()), dt_lib.time(23, 59, 59))),
        "本周": (dt_lib.datetime.combine(today - dt_lib.timedelta(days=today.weekday()), dt_lib.time(0, 0)),
                  dt_lib.datetime.combine(today + dt_lib.timedelta(days=6 - today.weekday()), dt_lib.time(23, 59, 59))),
        "next_week": (dt_lib.datetime.combine(today + dt_lib.timedelta(days=7 - today.weekday()), dt_lib.time(0, 0)),
                       dt_lib.datetime.combine(today + dt_lib.timedelta(days=13 - today.weekday()), dt_lib.time(23, 59, 59))),
        "下周": (dt_lib.datetime.combine(today + dt_lib.timedelta(days=7 - today.weekday()), dt_lib.time(0, 0)),
                  dt_lib.datetime.combine(today + dt_lib.timedelta(days=13 - today.weekday()), dt_lib.time(23, 59, 59))),
        "this_month": (dt_lib.datetime.combine(today.replace(day=1), dt_lib.time(0, 0)),
                        dt_lib.datetime.combine(
                            (today.replace(day=28) + dt_lib.timedelta(days=4)).replace(day=1) - dt_lib.timedelta(days=1),
                            dt_lib.time(23, 59, 59))),
        "本月": (dt_lib.datetime.combine(today.replace(day=1), dt_lib.time(0, 0)),
                  dt_lib.datetime.combine(
                      (today.replace(day=28) + dt_lib.timedelta(days=4)).replace(day=1) - dt_lib.timedelta(days=1),
                      dt_lib.time(23, 59, 59))),
    }

    if tr in range_map:
        start, end = range_map[tr]
        return [
            item for item in items
            if item.get(time_key) and start <= dt_lib.datetime.fromisoformat(item[time_key].replace("Z", "")) <= end
        ]

    if " ~ " in tr:
        parts = tr.split(" ~ ")
        try:
            s = dt_lib.datetime.fromisoformat(parts[0].strip() + "T00:00:00")
            e = dt_lib.datetime.fromisoformat(parts[1].strip() + "T23:59:59")
            return [
                item for item in items
                if item.get(time_key) and s <= dt_lib.datetime.fromisoformat(item[time_key].replace("Z", "")) <= e
            ]
        except Exception:
            pass

    return items


def _normalize_repeat(repeat: str) -> str:
    """Convert human-readable repeat patterns to RRULE."""
    mapping = {
        "daily": "FREQ=DAILY",
        "每天": "FREQ=DAILY",
        "weekly": "FREQ=WEEKLY",
        "每周": "FREQ=WEEKLY",
        "monthly": "FREQ=MONTHLY",
        "每月": "FREQ=MONTHLY",
        "yearly": "FREQ=YEARLY",
        "每年": "FREQ=YEARLY",
        "工作日": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
        "weekdays": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
        "weekend": "FREQ=WEEKLY;BYDAY=SA,SU",
        "周末": "FREQ=WEEKLY;BYDAY=SA,SU",
    }
    return mapping.get(repeat.lower(), repeat)


# ---- Entry Point ----

def _init_stdio_user(token_str: str = ""):
    global _stdio_user_id
    token_str = token_str or os.environ.get('MCP_USER_TOKEN', '')
    if not token_str:
        print("Error: No user token specified. Provide --token or set MCP_USER_TOKEN.", file=sys.stderr)
        sys.exit(1)
    user_id = asyncio.run(_get_user_id_from_token(token_str))
    if user_id is None:
        print(f"Error: Invalid token: {token_str[:8]}...", file=sys.stderr)
        sys.exit(1)
    _stdio_user_id = user_id
    print(f"Authenticated user ID: {user_id}", file=sys.stderr)


def _setup_http_auth():
    try:
        from mcp.server.auth.provider import AccessToken, TokenVerifier
        
        class JWTTokenVerifier(TokenVerifier):
            async def verify_token(self, token: str) -> Optional[AccessToken]:
                user_id = await _get_user_id_from_token(token)
                if user_id is None:
                    return None
                _current_user_var.set(user_id)
                return AccessToken(token=token, client_id=str(user_id), scopes=["user"])
        
        return JWTTokenVerifier()
    except ImportError as e:
        print(f"Warning: HTTP auth imports failed: {e}", file=sys.stderr)
        print("Please install mcp[cli] package", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(description="UniCalendar MCP Server")
    parser.add_argument('--http', action='store_true', help='Use HTTP transport (remote mode)')
    parser.add_argument('--token', type=str, default='', metavar='TOKEN', help='User JWT token')
    parser.add_argument('--port', type=int, default=8100, help='HTTP port (default 8100)')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='HTTP bind address')
    parser.add_argument('--no-auth', action='store_true', help='Disable HTTP auth (dev only, requires --token)')
    args = parser.parse_args()

    if args.http:
        transport = "streamable-http"
        mcp.settings.host = args.host
        mcp.settings.port = args.port

        token_str = os.environ.get('MCP_USER_TOKEN', '')
        if token_str:
            global _stdio_user_id
            user_id = asyncio.run(_get_user_id_from_token(token_str))
            if user_id:
                _stdio_user_id = user_id
                print(f"HTTP mode - fixed user ID: {user_id}", file=sys.stderr)

        if not args.no_auth:
            verifier = _setup_http_auth()
            if verifier:
                print("HTTP auth configured (supports Header or Query token=)", file=sys.stderr)
        else:
            if not _stdio_user_id:
                print("Error: --no-auth requires --token or MCP_USER_TOKEN", file=sys.stderr)
                sys.exit(1)
            print("Warning: HTTP auth disabled (dev only)", file=sys.stderr)

        # Inject query-param-to-header middleware
        from urllib.parse import parse_qs, unquote
        import uvicorn

        original_app = mcp.streamable_http_app()

        async def query_to_header_middleware(scope, receive, send):
            if scope["type"] == "http":
                raw_path = scope.get("path", "")
                decoded_path = unquote(raw_path)
                if "?" in decoded_path:
                    actual_path, fake_query = decoded_path.split("?", 1)
                    scope["path"] = actual_path
                    if fake_query:
                        scope["query_string"] = fake_query.encode("utf-8")
                query_string = scope.get("query_string", b"").decode("utf-8")
                query_params = parse_qs(query_string)
                token = query_params.get("token", [None])[0] or query_params.get("api_key", [None])[0]
                headers = list(scope.get("headers", []))
                if not token:
                    for k, v in headers:
                        if k.decode('utf-8').lower() == 'authorization':
                            auth_str = v.decode('utf-8')
                            if auth_str.lower().startswith('bearer '):
                                token = auth_str[7:].strip()
                            break
                if token and (query_params.get("token") or query_params.get("api_key")):
                    auth_exists = any(k.decode('utf-8').lower() == 'authorization' for k, v in headers)
                    if not auth_exists:
                        headers.append((b'authorization', f'Bearer {token}'.encode('utf-8')))
                        scope["headers"] = headers
                    try:
                        user_id = asyncio.run(_get_user_id_from_token(token))
                        if user_id:
                            _current_user_var.set(user_id)
                    except Exception as e:
                        print(f"Middleware auth error: {e}", file=sys.stderr)
            return await original_app(scope, receive, send)

        print(f"UniCalendar MCP Server (HTTP) starting at http://{args.host}:{args.port}/mcp", file=sys.stderr)
        uvicorn.run(query_to_header_middleware, host=args.host, port=args.port,
                    proxy_headers=True, forwarded_allow_ips="*")
        return

    else:
        transport = "stdio"
        _init_stdio_user(args.token)
        print("UniCalendar MCP Server (stdio) started", file=sys.stderr)

    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
