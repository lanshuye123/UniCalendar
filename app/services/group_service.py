import uuid
import json
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import UserData, EventGroup


async def get_event_groups(db: AsyncSession, user_id: int) -> list:
    result = await db.execute(
        select(EventGroup).where(EventGroup.user_id == user_id)
    )
    groups = result.scalars().all()
    return [
        {
            "id": g.id,
            "name": g.name,
            "description": g.description,
            "color": g.color,
            "type": g.typ,
            "working_hours_start": g.working_hours_start,
            "working_hours_end": g.working_hours_end,
            "created_at": g.created_at.isoformat() if g.created_at else None,
        }
        for g in groups
    ]


async def create_event_group(db: AsyncSession, user_id: int, data: dict) -> dict:
    group = EventGroup(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=data["name"],
        description=data.get("description", ""),
        color=data.get("color", "#3b82f6"),
        typ=data.get("typ", "default"),
        working_hours_start=data.get("working_hours_start", "09:00"),
        working_hours_end=data.get("working_hours_end", "18:00"),
    )
    db.add(group)
    await db.flush()
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "color": group.color,
        "type": group.typ,
        "working_hours_start": group.working_hours_start,
        "working_hours_end": group.working_hours_end,
    }


async def update_event_group(db: AsyncSession, user_id: int, group_id: str, data: dict) -> dict:
    result = await db.execute(
        select(EventGroup).where(EventGroup.id == group_id, EventGroup.user_id == user_id)
    )
    group = result.scalar_one_or_none()
    if not group:
        raise ValueError("Event group not found")

    for field, col in [("name", "name"), ("description", "description"), ("color", "color"),
                        ("typ", "typ"), ("working_hours_start", "working_hours_start"),
                        ("working_hours_end", "working_hours_end")]:
        if field in data and data[field] is not None:
            setattr(group, col, data[field])

    group.updated_at = datetime.utcnow()
    await db.flush()
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "color": group.color,
        "type": group.typ,
        "working_hours_start": group.working_hours_start,
        "working_hours_end": group.working_hours_end,
    }


async def delete_event_groups(db: AsyncSession, user_id: int, group_ids: list[str]) -> int:
    result = await db.execute(
        select(EventGroup).where(EventGroup.id.in_(group_ids), EventGroup.user_id == user_id)
    )
    groups = result.scalars().all()
    for g in groups:
        await db.delete(g)
    await db.flush()
    return len(groups)
