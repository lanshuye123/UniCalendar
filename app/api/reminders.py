from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import ReminderCreate, ReminderUpdate, ReminderBulkEdit, ReminderStatusUpdate, MessageResponse
from app.services import reminder_service

router = APIRouter(prefix="/reminders", tags=["Reminders"])


@router.get("/")
async def list_reminders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all reminders."""
    reminders = await reminder_service.get_reminders(db, current_user.id)
    return {"reminders": reminders, "count": len(reminders)}


@router.post("/")
async def create_reminder(
    data: ReminderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new reminder (with optional recurring rules)."""
    reminder = await reminder_service.create_reminder(db, current_user.id, data.model_dump())
    return {"reminder": reminder, "message": "Reminder created"}


@router.get("/{reminder_id}")
async def get_reminder(
    reminder_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single reminder."""
    reminders = await reminder_service.get_reminders(db, current_user.id)
    reminder = next((r for r in reminders if r["id"] == reminder_id), None)
    if not reminder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found")
    return {"reminder": reminder}


@router.put("/{reminder_id}")
async def update_reminder(
    reminder_id: str,
    data: ReminderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a reminder."""
    update_data = {k: v for k, v in data.model_dump().items() if v is not None or k in ("clear_rrule",)}
    try:
        reminder = await reminder_service.update_reminder(db, current_user.id, reminder_id, update_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"reminder": reminder, "message": "Reminder updated"}


@router.delete("/{reminder_id}")
async def delete_reminder(
    reminder_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a reminder."""
    success = await reminder_service.delete_reminder(db, current_user.id, reminder_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found")
    return {"message": "Reminder deleted"}


@router.post("/update-status")
async def update_reminder_status(
    data: ReminderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a reminder's status (snooze, dismiss, complete)."""
    try:
        reminder = await reminder_service.update_reminder_status(
            db, current_user.id, data.reminder_id,
            data.status, data.snooze_until or ""
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"reminder": reminder, "message": f"Reminder {data.status}"}


@router.post("/bulk-edit")
async def bulk_edit_reminders(
    data: ReminderBulkEdit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bulk edit/delete reminders with scope support."""
    try:
        result = await reminder_service.bulk_edit_reminders(db, current_user.id, data.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return result
