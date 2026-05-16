from fastapi import APIRouter
from app.api.auth import router as auth_router
from app.api.events import router as events_router
from app.api.todos import router as todos_router
from app.api.reminders import router as reminders_router
from app.api.event_groups import router as event_groups_router
from app.api.share_groups import router as share_groups_router
from app.api.calendar_feed import router as calendar_router
from app.api.oauth import router as oauth_router
from app.api.legacy import router as legacy_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(events_router)
api_router.include_router(todos_router)
api_router.include_router(reminders_router)
api_router.include_router(event_groups_router)
api_router.include_router(share_groups_router)
api_router.include_router(calendar_router)
api_router.include_router(oauth_router)
api_router.include_router(legacy_router)
