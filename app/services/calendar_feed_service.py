from io import BytesIO
from datetime import datetime, timedelta
from icalendar import Calendar, Event as CalEvent, Alarm
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.event_service import get_events
from app.services.todo_service import get_todos
from app.services.reminder_service import get_reminders


async def generate_icalendar_feed(db: AsyncSession, user_id: int) -> bytes:
    """Generate an iCalendar (.ics) feed from user's events, todos, and reminders."""
    cal = Calendar()
    cal.add("prodid", "-//UniCalendar//API//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "UniCalendar Feed")
    cal.add("x-wr-timezone", "Asia/Shanghai")

    events = await get_events(db, user_id)
    for evt in events:
        try:
            ce = CalEvent()
            ce.add("uid", evt.get("id", ""))
            ce.add("summary", evt.get("title", "Untitled"))
            ce.add("description", evt.get("description", ""))

            start_str = evt.get("start", "")
            end_str = evt.get("end", "")

            if "T" in start_str:
                dt_start = datetime.fromisoformat(start_str.replace("Z", ""))
                dt_end = datetime.fromisoformat(end_str.replace("Z", "")) if end_str else dt_start + timedelta(hours=1)
                ce.add("dtstart", dt_start)
                ce.add("dtend", dt_end)
            else:
                ce.add("dtstart", datetime.fromisoformat(start_str + "T00:00:00").date())
                ce.add("dtend", datetime.fromisoformat(start_str + "T00:00:00").date() + timedelta(days=1))

            if evt.get("rrule"):
                try:
                    from dateutil.rrule import rrulestr
                    rule = rrulestr(evt["rrule"])
                    ce.add("rrule", rule)
                except Exception:
                    pass

            if evt.get("importance") == "high":
                alarm = Alarm()
                alarm.add("action", "DISPLAY")
                alarm.add("description", f"High importance: {evt.get('title', '')}")
                alarm.add("trigger", timedelta(minutes=-30))
                ce.add_component(alarm)

            cal.add_component(ce)
        except Exception:
            continue

    todos = await get_todos(db, user_id)
    for todo in todos:
        if todo.get("due_date") and todo["status"] != "completed":
            try:
                ce = CalEvent()
                ce.add("uid", todo.get("id", "") + "-todo")
                ce.add("summary", f"[TODO] {todo.get('title', 'Untitled')}")
                ce.add("description", todo.get("description", ""))
                due = datetime.fromisoformat(todo["due_date"].replace("Z", ""))
                ce.add("dtstart", due)
                ce.add("dtend", due + timedelta(hours=1))
                cal.add_component(ce)
            except Exception:
                continue

    reminders = await get_reminders(db, user_id)
    for rem in reminders:
        try:
            ce = CalEvent()
            ce.add("uid", rem.get("id", "") + "-rem")
            ce.add("summary", f"[Reminder] {rem.get('title', 'Untitled')}")
            ce.add("description", rem.get("content", ""))
            trigger = datetime.fromisoformat(rem.get("trigger_time", "").replace("Z", ""))
            ce.add("dtstart", trigger)
            ce.add("dtend", trigger + timedelta(minutes=15))

            alarm = Alarm()
            alarm.add("action", "DISPLAY")
            alarm.add("description", rem.get("title", ""))
            alarm.add("trigger", timedelta(minutes=-5))
            ce.add_component(alarm)

            cal.add_component(ce)
        except Exception:
            continue

    buf = BytesIO()
    buf.write(cal.to_ical())
    return buf.getvalue()
