import uuid
import json
from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import ShareGroup, GroupMembership, GroupCalendarData
from app.services.event_service import get_events


def _generate_join_code() -> str:
    import secrets
    return secrets.token_hex(4).upper()


async def create_share_group(db: AsyncSession, user_id: int, name: str, description: str = "") -> dict:
    group = ShareGroup(
        id=str(uuid.uuid4()),
        owner_id=user_id,
        name=name,
        description=description,
        join_code=_generate_join_code(),
    )
    db.add(group)
    await db.flush()

    membership = GroupMembership(
        share_group_id=group.id,
        user_id=user_id,
        role="owner",
    )
    db.add(membership)

    cal_data = GroupCalendarData(
        share_group_id=group.id,
        events_data="[]",
        last_synced_by=user_id,
    )
    db.add(cal_data)
    await db.flush()

    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "join_code": group.join_code,
        "is_active": group.is_active,
        "owner_id": group.owner_id,
        "created_at": group.created_at.isoformat() if group.created_at else None,
    }


async def get_my_groups(db: AsyncSession, user_id: int) -> list:
    result = await db.execute(
        select(GroupMembership).where(GroupMembership.user_id == user_id)
    )
    memberships = result.scalars().all()
    groups = []
    for m in memberships:
        g_result = await db.execute(select(ShareGroup).where(ShareGroup.id == m.share_group_id))
        g = g_result.scalar_one_or_none()
        if g:
            groups.append({
                "id": g.id,
                "name": g.name,
                "description": g.description,
                "join_code": g.join_code,
                "is_active": g.is_active,
                "owner_id": g.owner_id,
                "role": m.role,
                "created_at": g.created_at.isoformat() if g.created_at else None,
            })
    return groups


async def join_share_group(db: AsyncSession, user_id: int, join_code: str) -> dict:
    result = await db.execute(
        select(ShareGroup).where(ShareGroup.join_code == join_code, ShareGroup.is_active == True)
    )
    group = result.scalar_one_or_none()
    if not group:
        raise ValueError("Share group not found or inactive")

    existing = await db.execute(
        select(GroupMembership).where(
            GroupMembership.share_group_id == group.id,
            GroupMembership.user_id == user_id
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Already a member of this group")

    membership = GroupMembership(
        share_group_id=group.id,
        user_id=user_id,
        role="member",
    )
    db.add(membership)
    await db.flush()

    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "join_code": group.join_code,
        "role": "member",
    }


async def leave_share_group(db: AsyncSession, user_id: int, group_id: str) -> bool:
    result = await db.execute(
        select(GroupMembership).where(
            GroupMembership.share_group_id == group_id,
            GroupMembership.user_id == user_id,
            GroupMembership.role != "owner",
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise ValueError("Cannot leave group (owner or not a member)")

    await db.delete(membership)
    await db.flush()
    return True


async def get_group_members(db: AsyncSession, group_id: str, user_id: int) -> list:
    # Verify membership
    check = await db.execute(
        select(GroupMembership).where(
            GroupMembership.share_group_id == group_id,
            GroupMembership.user_id == user_id,
        )
    )
    if not check.scalar_one_or_none():
        raise ValueError("Not a member of this group")

    result = await db.execute(
        select(GroupMembership).where(GroupMembership.share_group_id == group_id)
    )
    memberships = result.scalars().all()
    return [
        {"user_id": m.user_id, "role": m.role, "color": m.color, "joined_at": m.joined_at.isoformat() if m.joined_at else None}
        for m in memberships
    ]


async def update_member_role(db: AsyncSession, group_id: str, requester_id: int, target_user_id: int, role: str, color: str = "") -> dict:
    # Check requester is owner or admin
    req = await db.execute(
        select(GroupMembership).where(
            GroupMembership.share_group_id == group_id,
            GroupMembership.user_id == requester_id,
            GroupMembership.role.in_(["owner", "admin"]),
        )
    )
    if not req.scalar_one_or_none():
        raise ValueError("Insufficient permissions")

    target = await db.execute(
        select(GroupMembership).where(
            GroupMembership.share_group_id == group_id,
            GroupMembership.user_id == target_user_id,
        )
    )
    mem = target.scalar_one_or_none()
    if not mem:
        raise ValueError("Member not found")

    if role:
        mem.role = role
    if color:
        mem.color = color
    await db.flush()
    return {"user_id": mem.user_id, "role": mem.role, "color": mem.color}


async def get_group_events(db: AsyncSession, group_id: str, user_id: int) -> list:
    check = await db.execute(
        select(GroupMembership).where(
            GroupMembership.share_group_id == group_id,
            GroupMembership.user_id == user_id,
        )
    )
    if not check.scalar_one_or_none():
        raise ValueError("Not a member of this group")

    result = await db.execute(
        select(GroupCalendarData).where(GroupCalendarData.share_group_id == group_id)
    )
    cal = result.scalar_one_or_none()
    if cal:
        return cal.events
    return []


async def sync_group_calendar_data(db: AsyncSession, group_ids: list[str], user_id: int):
    """Sync shared events to group calendar data."""
    # Get all events from the user that are shared to these groups
    user_events = await get_events(db, user_id)
    for group_id in group_ids:
        shared_events = [e for e in user_events if group_id in e.get("shared_to_groups", [])]
        result = await db.execute(
            select(GroupCalendarData).where(GroupCalendarData.share_group_id == group_id)
        )
        cal = result.scalar_one_or_none()
        if cal:
            cal.events = shared_events
            cal.last_synced_by = user_id
            cal.updated_at = datetime.utcnow()
    await db.flush()
