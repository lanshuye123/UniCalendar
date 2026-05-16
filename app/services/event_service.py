import json
import uuid
import re
from datetime import datetime, timedelta
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import User, UserData, EventGroup
from app.core.rrule_engine import RRuleEngine
from app.core.reminder_manager import DictStorageBackend


def _get_rrule_engine(user_id: int) -> RRuleEngine:
    return RRuleEngine(DictStorageBackend(user_id))


async def _get_user_data(db: AsyncSession, user_id: int, key: str) -> tuple:
    result = await db.execute(
        select(UserData).where(UserData.user_id == user_id, UserData.key == key)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = UserData(user_id=user_id, key=key, value="[]")
        db.add(row)
        await db.flush()
    return row, row.get_value()


async def get_events(db: AsyncSession, user_id: int) -> list:
    _, events = await _get_user_data(db, user_id, "events")
    return events if isinstance(events, list) else []


async def create_event(db: AsyncSession, user_id: int, data: dict) -> dict:
    row, events = await _get_user_data(db, user_id, "events")
    if not isinstance(events, list):
        events = []

    rrule = data.get("rrule", "")
    main_event = None

    if rrule and "FREQ=" in rrule:
        rrule = rrule.strip().rstrip(";")
        engine = _get_rrule_engine(user_id)
        main_event = _create_recurring_event(engine, data, rrule)
        events.append(main_event)

        if "COUNT=" not in rrule and "UNTIL=" not in rrule:
            if "FREQ=MONTHLY" in rrule:
                additional = _generate_event_instances(engine, main_event, 365, 36)
            elif "FREQ=WEEKLY" in rrule:
                additional = _generate_event_instances(engine, main_event, 180, 26)
            else:
                additional = _generate_event_instances(engine, main_event, 90, 20)
            events.extend(additional)
        elif "COUNT=" in rrule:
            count_match = re.search(r"COUNT=(\d+)", rrule)
            if count_match:
                count = int(count_match.group(1))
                additional = _generate_event_instances(engine, main_event, 365, count)
                events.extend(additional)
        elif "UNTIL=" in rrule:
            additional = _generate_event_instances(engine, main_event, 365 * 2, 1000)
            events.extend(additional)
    else:
        data["id"] = str(uuid.uuid4())
        data["last_modified"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        events.append(data)
        main_event = data

    row.set_value(events)
    await db.flush()
    return main_event


def _create_recurring_event(engine: RRuleEngine, event_data: dict, rrule: str) -> dict:
    try:
        start_time = _parse_datetime(event_data["start"])
        end_time = _parse_datetime(event_data["end"])
    except Exception:
        start_time = datetime.now()
        end_time = start_time + timedelta(hours=1)

    duration = end_time - start_time
    needs_next = any(p in rrule for p in ["BYWEEKDAY", "BYMONTHDAY", "BYSETPOS", "BYYEARDAY", "BYWEEKNO", "BYDAY"])

    if needs_next:
        actual_start = _find_next_occurrence(rrule, start_time)
        if actual_start:
            actual_start = actual_start.replace(hour=start_time.hour, minute=start_time.minute,
                                                 second=start_time.second, microsecond=start_time.microsecond)
        else:
            actual_start = start_time
    else:
        actual_start = start_time

    actual_end = actual_start + duration
    series_id = engine.create_series(rrule, actual_start)

    main_event = event_data.copy()
    main_event.update({
        "id": str(uuid.uuid4()),
        "series_id": series_id,
        "rrule": rrule,
        "start": actual_start.strftime("%Y-%m-%dT%H:%M:%S"),
        "end": actual_end.strftime("%Y-%m-%dT%H:%M:%S"),
        "is_recurring": True,
        "is_main_event": True,
        "recurrence_id": "",
        "parent_event_id": "",
        "last_modified": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    return main_event


def _parse_datetime(time_str: str) -> datetime:
    if not time_str:
        return datetime.now()
    if "T" in time_str:
        if time_str.endswith("Z"):
            time_str = time_str[:-1]
        elif "+" in time_str or time_str.count("-") > 2:
            if "+" in time_str:
                time_str = time_str.split("+")[0]
            else:
                parts = time_str.split("-")
                if len(parts) > 3:
                    time_str = "-".join(parts[:3])
        if time_str.count(":") == 1:
            time_str += ":00"
    return datetime.fromisoformat(time_str)


def _find_next_occurrence(rrule_str: str, start_time: datetime) -> Optional[datetime]:
    try:
        from dateutil.rrule import rrulestr
        full_rrule = f"DTSTART:{start_time.strftime('%Y%m%dT%H%M%S')}\nRRULE:{rrule_str}"
        rule = rrulestr(full_rrule, dtstart=start_time)
        instances = list(rule[:5])
        if instances:
            first = instances[0]
            if (first.date() == start_time.date() and first.hour == start_time.hour and first.minute == start_time.minute):
                return start_time
            return first
        return None
    except Exception:
        return None


def _generate_event_instances(engine: RRuleEngine, main_event: dict, days_ahead: int, max_instances: int) -> list:
    instances = []
    rrule = main_event.get("rrule", "")
    series_id = main_event.get("series_id", "")
    if not rrule or not series_id or "FREQ=" not in rrule:
        return instances

    try:
        event_start = datetime.fromisoformat(main_event["start"])
        event_end = datetime.fromisoformat(main_event["end"])
    except Exception:
        return instances

    duration = event_end - event_start
    now = datetime.now()
    reference = max(event_start, now)
    end_time = reference + timedelta(days=days_ahead)
    total_days = (end_time - event_start).days
    estimated = max(max_instances, total_days + 10)

    instance_times = engine.generate_instances(series_id, event_start, end_time, estimated)
    for t in instance_times:
        if t == event_start:
            continue
        inst = main_event.copy()
        inst_end = (t + duration).strftime("%Y-%m-%dT%H:%M:%S")
        inst_ddl = ""
        if main_event.get("ddl"):
            try:
                ddl_time_part = main_event["ddl"].split("T")[1]
                inst_ddl = f"{inst_end.split('T')[0]}T{ddl_time_part}"
            except Exception:
                inst_ddl = main_event["ddl"]
        inst.update({
            "id": str(uuid.uuid4()),
            "start": t.strftime("%Y-%m-%dT%H:%M:%S"),
            "end": inst_end,
            "ddl": inst_ddl,
            "is_main_event": False,
            "recurrence_id": t.strftime("%Y%m%dT%H%M%S"),
            "last_modified": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        instances.append(inst)
    return instances


async def update_event(db: AsyncSession, user_id: int, event_id: str, data: dict) -> dict:
    row, events = await _get_user_data(db, user_id, "events")
    if not isinstance(events, list):
        events = []

    target = next((e for e in events if e.get("id") == event_id), None)
    if not target:
        raise ValueError("Event not found")

    for field in ["title", "start", "end", "description", "importance", "urgency", "groupID", "ddl", "shared_to_groups"]:
        if field in data and data[field] is not None:
            target[field] = data[field]

    if data.get("clear_rrule"):
        target["rrule"] = ""
        target["is_recurring"] = False
    elif "rrule" in data and data["rrule"] is not None:
        new_rrule = data["rrule"].strip().rstrip(";") if data["rrule"] else ""
        target["rrule"] = new_rrule
        target["is_recurring"] = bool(data["rrule"])
        if new_rrule:
            if not target.get("series_id"):
                target["series_id"] = target.get("id")
            series_id = target["series_id"]
            events = [e for e in events if e.get("series_id") != series_id or e.get("id") == event_id]
            engine = _get_rrule_engine(user_id)
            if "COUNT=" not in new_rrule and "UNTIL=" not in new_rrule:
                if "FREQ=MONTHLY" in new_rrule:
                    additional = _generate_event_instances(engine, target, 365, 36)
                elif "FREQ=WEEKLY" in new_rrule:
                    additional = _generate_event_instances(engine, target, 180, 26)
                else:
                    additional = _generate_event_instances(engine, target, 90, 20)
                events.extend(additional)

    target["last_modified"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row.set_value(events)
    await db.flush()
    return target


async def delete_event(db: AsyncSession, user_id: int, event_id: str, delete_scope: str = "single") -> bool:
    row, events = await _get_user_data(db, user_id, "events")
    if not isinstance(events, list):
        return False

    target = next((e for e in events if e.get("id") == event_id), None)
    if not target:
        raise ValueError("Event not found")

    original_count = len(events)
    is_recurring = target.get("is_recurring", False)
    series_id = target.get("series_id")

    if is_recurring and series_id:
        if delete_scope == "single":
            events = [e for e in events if e.get("id") != event_id]
            if len(events) < original_count and target.get("is_main_event"):
                series_events = sorted(
                    [e for e in events if e.get("series_id") == series_id],
                    key=lambda x: x["start"]
                )
                if series_events:
                    for i, e in enumerate(events):
                        if e.get("id") == series_events[0]["id"]:
                            events[i]["is_main_event"] = True
                            events[i]["last_modified"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            break
            engine = _get_rrule_engine(user_id)
            try:
                start_time = datetime.fromisoformat(target.get("start", ""))
                engine.delete_instance(series_id, start_time)
            except Exception:
                pass
        elif delete_scope == "all":
            events = [e for e in events if e.get("series_id") != series_id]
        elif delete_scope == "future":
            target_start = datetime.fromisoformat(target["start"])
            events = [e for e in events if not (
                e.get("series_id") == series_id and
                datetime.fromisoformat(e["start"]) >= target_start
            )]
            engine = _get_rrule_engine(user_id)
            engine.truncate_series_until(series_id, target_start)
    else:
        events = [e for e in events if e.get("id") != event_id]

    if len(events) < original_count:
        row.set_value(events)
        await db.flush()
        return True
    return False
