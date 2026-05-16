"""
CalDAV iCalendar 构建器 — ported from caldav_service/ical_builder.py
Uses our own calendar_feed_service helper functions.
"""

import datetime
from typing import Optional
from icalendar import Calendar, Event, Alarm

CALENDAR_PRODID = "-//UniScheduler//UniScheduler//ZH"
TIMEZONE_ID = "Asia/Shanghai"
UID_DOMAIN = "unischeduler"
REMINDER_DURATION_MINUTES = 5


def _build_vtimezone():
    from icalendar import Timezone, TimezoneStandard
    tz = Timezone()
    tz.add("TZID", TIMEZONE_ID)
    std = TimezoneStandard()
    std.add("DTSTART", datetime.datetime(1970, 1, 1, 0, 0, 0))
    std.add("TZOFFSETFROM", datetime.timedelta(hours=8))
    std.add("TZOFFSETTO", datetime.timedelta(hours=8))
    std.add("TZNAME", "CST")
    tz.add_component(std)
    return tz


def _parse_dt(value: str) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _dt_to_utc(dt: datetime.datetime) -> datetime.datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(datetime.timezone.utc)
    return dt.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8))).astimezone(datetime.timezone.utc)


def _map_event_status(status: str) -> str:
    mapping = {"confirmed": "CONFIRMED", "tentative": "TENTATIVE", "cancelled": "CANCELLED"}
    return mapping.get(status, "CONFIRMED")


def _parse_rrule_to_dict(rrule_str: str) -> dict:
    """将 RRULE 字符串解析为 icalendar 可用的 dict。"""
    from dateutil.rrule import rrulestr
    return rrulestr(rrule_str) if rrule_str else {}


def _parse_rrule_datetime(val: str) -> Optional[datetime.datetime]:
    """解析 recurrence_id 字符串为 datetime。"""
    if not val:
        return None
    try:
        return datetime.datetime.strptime(val, "%Y%m%dT%H%M%S")
    except (ValueError, TypeError):
        return None


def _build_valarm(description: str) -> Alarm:
    alarm = Alarm()
    alarm.add("action", "DISPLAY")
    alarm.add("description", description)
    alarm.add("trigger", datetime.timedelta(minutes=-5))
    return alarm


def _should_include_reminder(reminder: dict) -> bool:
    status = reminder.get("status", "active")
    return status in ("active", "snoozed")


def build_single_event_ical(event: dict) -> bytes:
    cal = Calendar()
    cal.add("PRODID", CALENDAR_PRODID)
    cal.add("VERSION", "2.0")
    cal.add("CALSCALE", "GREGORIAN")
    cal.add_component(_build_vtimezone())
    ve = _build_caldav_vevent(event)
    if ve:
        cal.add_component(ve)
    return cal.to_ical()


def build_series_ical(main_event: dict, detached_instances: list = None) -> bytes:
    cal = Calendar()
    cal.add("PRODID", CALENDAR_PRODID)
    cal.add("VERSION", "2.0")
    cal.add("CALSCALE", "GREGORIAN")
    cal.add_component(_build_vtimezone())
    ve = _build_caldav_vevent(main_event)
    if ve:
        cal.add_component(ve)
    if detached_instances:
        for instance in detached_instances:
            ve = _build_caldav_vevent(instance)
            if ve:
                cal.add_component(ve)
    return cal.to_ical()


def _build_caldav_vevent(event: dict) -> Optional[Event]:
    start = _parse_dt(event.get("start", ""))
    end = _parse_dt(event.get("end", ""))
    if not start:
        return None
    is_detached = event.get("is_detached", False)
    series_id = event.get("series_id", "")
    ve = Event()
    caldav_uid = event.get('caldav_uid')
    if is_detached and series_id:
        ve.add("UID", caldav_uid or f"evt-series-{series_id}@{UID_DOMAIN}")
        recurrence_id = event.get("recurrence_id", "")
        if recurrence_id:
            rec_dt = _parse_rrule_datetime(recurrence_id)
            if rec_dt:
                ve.add("RECURRENCE-ID", rec_dt, parameters={"TZID": TIMEZONE_ID})
    elif event.get("is_main_event", False) and series_id:
        ve.add("UID", caldav_uid or f"evt-series-{series_id}@{UID_DOMAIN}")
    elif caldav_uid:
        ve.add("UID", caldav_uid)
    else:
        ve.add("UID", f"{event['id']}@{UID_DOMAIN}")
    ve.add("SUMMARY", event.get("title", ""))
    dtstamp = _parse_dt(event.get("last_modified", ""))
    ve.add("DTSTAMP", _dt_to_utc(dtstamp) if dtstamp else _dt_to_utc(datetime.datetime.now()))
    ve.add("DTSTART", start, parameters={"TZID": TIMEZONE_ID})
    if end:
        ve.add("DTEND", end, parameters={"TZID": TIMEZONE_ID})
    if dtstamp:
        ve.add("LAST-MODIFIED", _dt_to_utc(dtstamp))
    desc = event.get("description", "")
    if desc:
        ve.add("DESCRIPTION", desc)
    location = event.get("location", "")
    if location:
        ve.add("LOCATION", location)
    status = event.get("status", "confirmed")
    ve.add("STATUS", _map_event_status(status))
    if not is_detached:
        rrule_str = event.get("rrule", "")
        if rrule_str:
            ve.add("RRULE", _parse_rrule_to_dict(rrule_str))
    return ve


def get_event_uid(event: dict) -> str:
    caldav_uid = event.get('caldav_uid', '')
    if caldav_uid:
        return caldav_uid
    is_detached = event.get("is_detached", False)
    series_id = event.get("series_id", "")
    if is_detached and series_id:
        return f"evt-series-{series_id}"
    elif event.get("is_main_event", False) and series_id:
        return f"evt-series-{series_id}"
    else:
        return event['id']


def build_single_reminder_ical(reminder: dict) -> bytes:
    cal = Calendar()
    cal.add("PRODID", CALENDAR_PRODID)
    cal.add("VERSION", "2.0")
    cal.add("CALSCALE", "GREGORIAN")
    cal.add_component(_build_vtimezone())
    ve = _build_caldav_vevent_from_reminder(reminder)
    if ve:
        cal.add_component(ve)
    return cal.to_ical()


def _build_caldav_vevent_from_reminder(reminder: dict) -> Optional[Event]:
    trigger_time = _parse_dt(reminder.get("trigger_time", ""))
    if not trigger_time:
        return None
    is_detached = reminder.get("is_detached", False)
    is_main = reminder.get("is_main_reminder", False)
    series_id = reminder.get("series_id", "")
    ve = Event()
    if is_detached and series_id:
        ve.add("UID", f"rem-series-{series_id}@{UID_DOMAIN}")
    elif is_main and series_id:
        ve.add("UID", f"rem-series-{series_id}@{UID_DOMAIN}")
    else:
        ve.add("UID", f"rem-{reminder['id']}@{UID_DOMAIN}")
    ve.add("SUMMARY", f"[Reminder] {reminder.get('title', '')}")
    dtstamp = _parse_dt(reminder.get("last_modified", "")) or _parse_dt(reminder.get("created_at", ""))
    ve.add("DTSTAMP", _dt_to_utc(dtstamp) if dtstamp else _dt_to_utc(datetime.datetime.now()))
    ve.add("DTSTART", trigger_time, parameters={"TZID": TIMEZONE_ID})
    ve.add("DTEND", trigger_time + datetime.timedelta(minutes=REMINDER_DURATION_MINUTES), parameters={"TZID": TIMEZONE_ID})
    if dtstamp:
        ve.add("LAST-MODIFIED", _dt_to_utc(dtstamp))
    content = reminder.get("content", "")
    if content:
        ve.add("DESCRIPTION", content)
    if not is_detached:
        rrule_str = reminder.get("rrule", "")
        if rrule_str:
            ve.add("RRULE", _parse_rrule_to_dict(rrule_str))
    ve.add_component(_build_valarm(f"Reminder: {reminder.get('title', '')}"))
    return ve


def get_reminder_uid(reminder: dict) -> str:
    is_detached = reminder.get("is_detached", False)
    series_id = reminder.get("series_id", "")
    if is_detached and series_id:
        return f"rem-series-{series_id}"
    elif reminder.get("is_main_reminder", False) and series_id:
        return f"rem-series-{series_id}"
    else:
        return f"rem-{reminder['id']}"


def should_include_reminder(reminder: dict) -> bool:
    return _should_include_reminder(reminder)
