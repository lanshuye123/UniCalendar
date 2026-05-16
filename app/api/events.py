from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import EventCreate, EventUpdate, BulkEditRequest, EventDelete, MessageResponse
from app.services import event_service

router = APIRouter(prefix="/events", tags=["Events"])


@router.get("/")
async def list_events(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all events for authenticated user."""
    events = await event_service.get_events(db, current_user.id)
    return {"events": events, "count": len(events)}


@router.post("/")
async def create_event(
    data: EventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new event (with optional recurring rules)."""
    event = await event_service.create_event(db, current_user.id, data.model_dump())
    return {"event": event, "message": "Event created"}


@router.get("/{event_id}")
async def get_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single event by ID."""
    events = await event_service.get_events(db, current_user.id)
    event = next((e for e in events if e.get("id") == event_id), None)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return {"event": event}


@router.put("/{event_id}")
async def update_event(
    event_id: str,
    data: EventUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing event."""
    update_data = {k: v for k, v in data.model_dump().items() if v is not None or k in ("clear_rrule",)}
    try:
        event = await event_service.update_event(db, current_user.id, event_id, update_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"event": event, "message": "Event updated"}


@router.delete("/{event_id}")
async def delete_event(
    event_id: str,
    delete_scope: str = Query("single", description="single, all, future"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an event."""
    try:
        success = await event_service.delete_event(db, current_user.id, event_id, delete_scope)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return {"message": "Event deleted"}


@router.post("/bulk-edit")
async def bulk_edit_events(
    data: BulkEditRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bulk edit/delete events with scope support (single, all, future)."""
    from app.services.event_service import update_event, delete_event

    if data.operation == "delete":
        try:
            success = await delete_event(db, current_user.id, data.event_id, data.edit_scope)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        return {"message": "Events deleted", "deleted": success}

    # edit
    events = await event_service.get_events(db, current_user.id)
    target = next((e for e in events if e.get("id") == data.event_id), None)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    series_id = data.series_id or target.get("series_id")
    is_recurring = bool(target.get("is_recurring") or target.get("series_id"))

    if not is_recurring or data.edit_scope == "single":
        update_data = {k: v for k, v in data.model_dump().items() if v is not None and k not in (
            "event_id", "operation", "edit_scope", "from_time", "series_id"
        )}
        try:
            updated = await update_event(db, current_user.id, data.event_id, update_data)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        return {"event": updated, "message": "Event updated"}

    # Recurring bulk edit — create new series for changed portion
    if data.edit_scope in ("future", "from_time"):
        from_time_str = data.from_time or data.start or target.get("start", "")
        try:
            from_date = __import__("datetime").datetime.fromisoformat(from_time_str.replace("Z", ""))
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid from_time format")

        # Truncate the original series
        if series_id:
            from app.core.rrule_engine import RRuleEngine
            from app.core.reminder_manager import DictStorageBackend
            engine = RRuleEngine(DictStorageBackend(current_user.id))
            engine.truncate_series_until(series_id, from_date)

        # Create new event with remaining changes as a new series
        new_rrule = data.rrule or target.get("rrule", "")
        if data.title:
            target["title"] = data.title
        event_data = target.copy()
        event_data["start"] = from_time_str
        event_data["rrule"] = new_rrule

        new_event = await event_service.create_event(db, current_user.id, event_data)
        return {"event": new_event, "message": f"Event modified from {from_time_str}"}

    if data.edit_scope == "all":
        update_data = {"rrule": data.rrule} if data.rrule else {}
        try:
            updated = await update_event(db, current_user.id, data.event_id, update_data)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        return {"event": updated, "message": "All events in series updated"}

    return {"message": "No changes made"}
