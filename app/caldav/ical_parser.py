"""
CalDAV iCalendar 解析器 — ported from caldav_service/ical_parser.py
All Django dependencies removed.
"""

import datetime
from typing import Optional, List, Tuple
from icalendar import Calendar

_BEIJING_TZ = datetime.timezone(datetime.timedelta(hours=8))


def _to_beijing_str(dt) -> str:
    if isinstance(dt, datetime.datetime):
        if dt.tzinfo is not None:
            dt = dt.astimezone(_BEIJING_TZ)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(dt, datetime.date):
        return datetime.datetime.combine(dt, datetime.time(0, 0)).strftime("%Y-%m-%dT%H:%M:%S")
    return str(dt)


def _dt_to_rrule_str(dt) -> str:
    if isinstance(dt, datetime.datetime):
        if dt.tzinfo is not None:
            local_dt = dt.astimezone(_BEIJING_TZ)
            return local_dt.strftime("%Y%m%dT%H%M%S")
        else:
            return dt.strftime("%Y%m%dT%H%M%S")
    elif isinstance(dt, datetime.date):
        return dt.strftime("%Y%m%d")
    return str(dt)


def _rrule_vrecur_to_str(vrecur) -> str:
    parts = []
    for key, val in vrecur.items():
        key_upper = key.upper()
        if isinstance(val, list):
            str_vals = []
            for v in val:
                if isinstance(v, (datetime.datetime, datetime.date)):
                    str_vals.append(_dt_to_rrule_str(v))
                else:
                    str_vals.append(str(v))
            parts.append(f"{key_upper}={','.join(str_vals)}")
        elif isinstance(val, (datetime.datetime, datetime.date)):
            parts.append(f"{key_upper}={_dt_to_rrule_str(val)}")
        else:
            parts.append(f"{key_upper}={val}")
    return ";".join(parts)


def ical_to_event_dict(ical_text, existing_event: dict = None) -> dict:
    if isinstance(ical_text, bytes):
        ical_text_bytes = ical_text
    else:
        ical_text_bytes = ical_text.encode('utf-8')
    cal = Calendar.from_ical(ical_text_bytes)
    for component in cal.walk():
        if component.name == 'VEVENT':
            if component.get('RECURRENCE-ID') is None:
                return _vevent_to_dict(component, existing_event)
    for component in cal.walk():
        if component.name == 'VEVENT':
            return _vevent_to_dict(component, existing_event)
    raise ValueError("No VEVENT found in iCalendar data")


def ical_to_all_event_dicts(ical_text, existing_event: dict = None) -> Tuple[dict, List[dict]]:
    if isinstance(ical_text, bytes):
        ical_text_bytes = ical_text
    else:
        ical_text_bytes = ical_text.encode('utf-8')
    cal = Calendar.from_ical(ical_text_bytes)
    main_vevent = None
    exception_vevents = []
    for component in cal.walk():
        if component.name == 'VEVENT':
            if component.get('RECURRENCE-ID') is not None:
                exception_vevents.append(component)
            else:
                main_vevent = component
    if main_vevent is None:
        raise ValueError("No main VEVENT (without RECURRENCE-ID) found")
    main_dict = _vevent_to_dict(main_vevent, existing_event)
    exception_dicts = []
    for exc_vevent in exception_vevents:
        exc_dict = _vevent_to_dict(exc_vevent, None)
        rec_id = exc_vevent.get('RECURRENCE-ID')
        if rec_id:
            dt = rec_id.dt
            if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
                dt = datetime.datetime.combine(dt, datetime.time(0, 0))
            if isinstance(dt, datetime.datetime) and dt.tzinfo is not None:
                dt = dt.astimezone(_BEIJING_TZ)
            exc_dict['recurrence_id'] = dt.strftime("%Y%m%dT%H%M%S")
        exception_dicts.append(exc_dict)
    return main_dict, exception_dicts


def _vevent_to_dict(vevent, existing: Optional[dict]) -> dict:
    result = existing.copy() if existing else {}
    uid = vevent.get('UID')
    if uid is not None:
        result['caldav_uid'] = str(uid)
    summary = vevent.get('SUMMARY')
    if summary is not None:
        result['title'] = str(summary)
    dtstart = vevent.get('DTSTART')
    if dtstart:
        dt = dtstart.dt
        if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
            dt = datetime.datetime.combine(dt, datetime.time(0, 0))
        result['start'] = _to_beijing_str(dt)
    dtend = vevent.get('DTEND')
    if dtend:
        dt = dtend.dt
        if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
            dt = datetime.datetime.combine(dt, datetime.time(0, 0))
        result['end'] = _to_beijing_str(dt)
    desc = vevent.get('DESCRIPTION')
    if desc is not None:
        result['description'] = str(desc)
    loc = vevent.get('LOCATION')
    if loc is not None:
        result['location'] = str(loc)
    status = vevent.get('STATUS')
    if status:
        status_map = {
            'CONFIRMED': 'confirmed', 'TENTATIVE': 'tentative', 'CANCELLED': 'cancelled',
        }
        result['status'] = status_map.get(str(status).upper(), 'confirmed')
    rrule = vevent.get('RRULE')
    if rrule:
        result['rrule'] = _rrule_vrecur_to_str(rrule)
    result['last_modified'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return result


def extract_uid_from_ical(ical_text) -> Optional[str]:
    if isinstance(ical_text, str):
        ical_text = ical_text.encode('utf-8')
    cal = Calendar.from_ical(ical_text)
    for component in cal.walk():
        if component.name == 'VEVENT':
            uid = component.get('UID')
            if uid:
                return str(uid)
    return None
