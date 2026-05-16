from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import ShareGroupCreate, ShareGroupJoin, ShareGroupMemberUpdate, MessageResponse
from app.services import share_group_service

router = APIRouter(prefix="/share-groups", tags=["Share Groups"])


@router.post("/")
async def create_share_group(
    data: ShareGroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new share group."""
    group = await share_group_service.create_share_group(
        db, current_user.id, data.name, data.description
    )
    return {"group": group, "message": "Share group created"}


@router.get("/")
async def list_my_groups(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all share groups the user belongs to."""
    groups = await share_group_service.get_my_groups(db, current_user.id)
    return {"groups": groups, "count": len(groups)}


@router.post("/join")
async def join_group(
    data: ShareGroupJoin,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Join a share group by invite code."""
    try:
        group = await share_group_service.join_share_group(db, current_user.id, data.join_code)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"group": group, "message": "Joined group successfully"}


@router.post("/{group_id}/leave")
async def leave_group(
    group_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Leave a share group (owners cannot leave)."""
    try:
        await share_group_service.leave_share_group(db, current_user.id, group_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"message": "Left group"}


@router.get("/{group_id}/members")
async def list_group_members(
    group_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List members of a share group."""
    try:
        members = await share_group_service.get_group_members(db, group_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    return {"members": members}


@router.put("/{group_id}/members")
async def update_member_role(
    group_id: str,
    data: ShareGroupMemberUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a member's role/color (requires owner or admin)."""
    try:
        result = await share_group_service.update_member_role(
            db, group_id, current_user.id, data.user_id, data.role, data.color
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"member": result, "message": "Member updated"}


@router.get("/{group_id}/events")
async def get_group_events(
    group_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get shared events from a group."""
    try:
        events = await share_group_service.get_group_events(db, group_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    return {"events": events, "count": len(events)}
