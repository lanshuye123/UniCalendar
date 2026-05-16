from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import TodoCreate, TodoUpdate, TodoConvert, MessageResponse
from app.services import todo_service

router = APIRouter(prefix="/todos", tags=["Todos"])


@router.get("/")
async def list_todos(
    status_filter: str = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all todos, optionally filtered by status."""
    todos = await todo_service.get_todos(db, current_user.id)
    if status_filter:
        todos = [t for t in todos if t.get("status") == status_filter]
    return {"todos": todos, "count": len(todos)}


@router.post("/")
async def create_todo(
    data: TodoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new todo."""
    todo = await todo_service.create_todo(db, current_user.id, data.model_dump())
    return {"todo": todo, "message": "Todo created"}


@router.get("/{todo_id}")
async def get_todo(
    todo_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single todo."""
    todos = await todo_service.get_todos(db, current_user.id)
    todo = next((t for t in todos if t["id"] == todo_id), None)
    if not todo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    return {"todo": todo}


@router.put("/{todo_id}")
async def update_todo(
    todo_id: str,
    data: TodoUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a todo."""
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    try:
        todo = await todo_service.update_todo(db, current_user.id, todo_id, update_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"todo": todo, "message": "Todo updated"}


@router.delete("/{todo_id}")
async def delete_todo(
    todo_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a todo."""
    success = await todo_service.delete_todo(db, current_user.id, todo_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    return {"message": "Todo deleted"}


@router.post("/convert")
async def convert_todo(
    data: TodoConvert,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Convert a todo into an event, then delete the todo."""
    try:
        event = await todo_service.convert_todo_to_event(
            db, current_user.id, data.todo_id, data.start, data.end
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"event": event, "message": "Todo converted to event"}
