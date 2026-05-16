from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, get_optional_user
from app.models import User
from app.services import calendar_feed_service

router = APIRouter(prefix="/calendar", tags=["Calendar Feed"])


@router.get("/feed")
async def calendar_feed(
    token: str = Query(None, description="Bearer token for auth via query param (for calendar apps)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_user),
):
    """
    iCalendar feed (.ics) — subscribe in Apple Calendar, Google Calendar, etc.
    Supports auth via Authorization header or ?token= query parameter.
    """
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    ics_data = await calendar_feed_service.generate_icalendar_feed(db, current_user.id)
    return Response(
        content=ics_data,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": "inline; filename=unicalendar.ics",
            "Cache-Control": "no-cache",
        }
    )
