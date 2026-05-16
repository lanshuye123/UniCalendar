import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import UserData


async def _get_user_data(db: AsyncSession, user_id: int, key: str):
    result = await db.execute(
        select(UserData).where(UserData.user_id == user_id, UserData.key == key)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = UserData(user_id=user_id, key=key, value="[]")
        db.add(row)
        await db.flush()
    return row, row.get_value()


async def get_todos(db: AsyncSession, user_id: int) -> list:
    _, todos = await _get_user_data(db, user_id, "todos")
    return todos if isinstance(todos, list) else []


async def create_todo(db: AsyncSession, user_id: int, data: dict) -> dict:
    row, todos = await _get_user_data(db, user_id, "todos")
    if not isinstance(todos, list):
        todos = []

    new_todo = {
        "id": str(uuid.uuid4()),
        "title": data["title"],
        "description": data.get("description", ""),
        "due_date": data.get("due_date", ""),
        "estimated_duration": data.get("estimated_duration", ""),
        "importance": data.get("importance", ""),
        "urgency": data.get("urgency", ""),
        "groupID": data.get("groupID", ""),
        "status": "pending",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_modified": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    todos.append(new_todo)
    row.set_value(todos)
    await db.flush()
    return new_todo


async def update_todo(db: AsyncSession, user_id: int, todo_id: str, data: dict) -> dict:
    row, todos = await _get_user_data(db, user_id, "todos")
    if not isinstance(todos, list):
        todos = []

    target = next((t for t in todos if t["id"] == todo_id), None)
    if not target:
        raise ValueError("Todo not found")

    for field in ["title", "description", "due_date", "estimated_duration", "importance", "urgency", "groupID", "status"]:
        if field in data and data[field] is not None:
            target[field] = data[field]

    target["last_modified"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row.set_value(todos)
    await db.flush()
    return target


async def delete_todo(db: AsyncSession, user_id: int, todo_id: str) -> bool:
    row, todos = await _get_user_data(db, user_id, "todos")
    if not isinstance(todos, list):
        return False

    new_todos = [t for t in todos if t["id"] != todo_id]
    if len(new_todos) < len(todos):
        row.set_value(new_todos)
        await db.flush()
        return True
    return False


async def convert_todo_to_event(db: AsyncSession, user_id: int, todo_id: str, start: str = "", end: str = "") -> dict:
    row, todos = await _get_user_data(db, user_id, "todos")
    if not isinstance(todos, list):
        raise ValueError("No todos found")

    target = next((t for t in todos if t["id"] == todo_id), None)
    if not target:
        raise ValueError("Todo not found")

    event_data = {
        "title": target["title"],
        "start": start or datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "end": end or (datetime.now() + __import__("datetime").timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        "description": target.get("description", ""),
        "importance": target.get("importance", ""),
        "urgency": target.get("urgency", ""),
        "groupID": target.get("groupID", ""),
    }

    from app.services.event_service import create_event
    new_event = await create_event(db, user_id, event_data)
    await delete_todo(db, user_id, todo_id)
    return new_event
