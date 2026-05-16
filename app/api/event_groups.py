from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import EventGroupCreate, EventGroupUpdate, MessageResponse
from app.services import group_service

router = APIRouter(prefix="/event-groups", tags=["Event Groups"])


@router.get("/")
async def list_event_groups(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all event groups."""
    groups = await group_service.get_event_groups(db, current_user.id)
    return {"groups": groups, "count": len(groups)}


@router.post("/")
async def create_event_group(
    data: EventGroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new event group."""
    group = await group_service.create_event_group(db, current_user.id, data.model_dump())
    return {"group": group, "message": "Event group created"}


@router.put("/{group_id}")
async def update_event_group(
    group_id: str,
    data: EventGroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an event group."""
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    try:
        group = await group_service.update_event_group(db, current_user.id, group_id, update_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"group": group, "message": "Event group updated"}


@router.delete("/{group_id}")
async def delete_event_group(
    group_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an event group."""
    count = await group_service.delete_event_groups(db, current_user.id, [group_id])
    if count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event group not found")
    return {"message": "Event group deleted"}


@router.post("/bulk-delete")
async def bulk_delete_event_groups(
    group_ids: list[str],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bulk delete event groups."""
    count = await group_service.delete_event_groups(db, current_user.id, group_ids)
    return {"message": f"Deleted {count} event group(s)"}
