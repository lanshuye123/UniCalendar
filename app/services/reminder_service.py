import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import UserData
from app.core.reminder_manager import IntegratedReminderManager


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


async def get_reminders(db: AsyncSession, user_id: int) -> list:
    _, reminders = await _get_user_data(db, user_id, "reminders")
    return reminders if isinstance(reminders, list) else []


async def create_reminder(db: AsyncSession, user_id: int, data: dict) -> dict:
    row, reminders = await _get_user_data(db, user_id, "reminders")
    if not isinstance(reminders, list):
        reminders = []

    reminder_data = {
        "title": data["title"],
        "content": data.get("content", ""),
        "trigger_time": data["trigger_time"],
        "priority": data.get("priority", "normal"),
        "status": "active",
        "snooze_until": "",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_modified": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    rrule = data.get("rrule", "")
    if rrule and "FREQ=" in rrule:
        mgr = IntegratedReminderManager(user_id)
        recurring = mgr.create_recurring_reminder(reminder_data, rrule)
        reminders.append(recurring)
        updated = mgr.process_reminder_data(reminders)
        row.set_value(updated)
        await db.flush()
        return recurring
    else:
        reminder_data.update({
            "id": str(uuid.uuid4()),
            "series_id": None,
            "rrule": "",
            "is_recurring": False,
            "is_main_reminder": False,
            "is_detached": False
        })
        reminders.append(reminder_data)
        row.set_value(reminders)
        await db.flush()
        return reminder_data


async def update_reminder(db: AsyncSession, user_id: int, reminder_id: str, data: dict) -> dict:
    row, reminders = await _get_user_data(db, user_id, "reminders")
    if not isinstance(reminders, list):
        reminders = []

    target = next((r for r in reminders if r["id"] == reminder_id), None)
    if not target:
        raise ValueError("Reminder not found")

    for field in ["title", "content", "trigger_time", "priority", "status"]:
        if field in data and data[field] is not None:
            target[field] = data[field]

    if data.get("clear_rrule"):
        target["rrule"] = ""
        target["is_recurring"] = False

    target["last_modified"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row.set_value(reminders)
    await db.flush()
    return target


async def delete_reminder(db: AsyncSession, user_id: int, reminder_id: str) -> bool:
    row, reminders = await _get_user_data(db, user_id, "reminders")
    if not isinstance(reminders, list):
        return False

    new_reminders = [r for r in reminders if r["id"] != reminder_id]
    if len(new_reminders) < len(reminders):
        row.set_value(new_reminders)
        await db.flush()
        return True
    return False


async def update_reminder_status(db: AsyncSession, user_id: int, reminder_id: str, status: str, snooze_until: str = "") -> dict:
    return await update_reminder(db, user_id, reminder_id, {
        "status": status,
        "snooze_until": snooze_until
    })


async def bulk_edit_reminders(db: AsyncSession, user_id: int, data: dict) -> dict:
    row, reminders = await _get_user_data(db, user_id, "reminders")
    if not isinstance(reminders, list):
        raise ValueError("No reminders found")

    reminder_id = data["reminder_id"]
    operation = data.get("operation", "edit")
    edit_scope = data.get("edit_scope", "single")
    series_id = data.get("series_id")

    target = next((r for r in reminders if r["id"] == reminder_id), None)
    if not target:
        raise ValueError(f"Reminder not found: {reminder_id}")

    if not series_id:
        series_id = target.get("series_id")

    mgr = IntegratedReminderManager(user_id)

    if operation == "delete":
        if edit_scope == "single":
            reminders = mgr.delete_reminder_instance(reminders, reminder_id, series_id)
        elif edit_scope in ("from_this", "future"):
            reminders = mgr.delete_reminder_this_and_after(reminders, reminder_id, series_id)
        elif edit_scope == "all":
            reminders = [r for r in reminders if r.get("series_id") != series_id]
        row.set_value(reminders)
        await db.flush()
        return {"message": "Reminder deleted", "deleted_count": 1}

    if edit_scope == "single":
        for field in ["title", "content", "trigger_time", "priority", "status"]:
            if field in data and data[field] is not None:
                target[field] = data[field]
        target["last_modified"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row.set_value(reminders)
        await db.flush()
        return target

    if edit_scope in ("from_this", "from_time", "all", "future"):
        new_rrule = data.get("rrule", target.get("rrule", ""))
        from_time_str = data.get("from_time", data.get("trigger_time", ""))
        try:
            from_date = datetime.fromisoformat(from_time_str.replace("Z", ""))
        except Exception:
            from_date = datetime.now()

        additional_updates = {k: v for k, v in data.items()
                              if k in ["title", "content", "priority", "status"] and v is not None}

        if edit_scope == "all":
            scope = "all"
        else:
            scope = "from_this"

        reminders = mgr.modify_recurring_rule(reminders, series_id, from_date, new_rrule, scope, additional_updates)
        row.set_value(reminders)
        await db.flush()
        return {"message": f"Bulk edit completed", "scope": edit_scope}

    return target
