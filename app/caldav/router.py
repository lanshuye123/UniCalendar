"""
CalDAV Router — ASGI application handling all CalDAV/WebDAV methods.
Ported from Django caldav_service views, adapted for SQLAlchemy async data access.
"""

import base64
import datetime
import json
import re
import uuid
import xml.etree.ElementTree as ET
from typing import Optional
from zoneinfo import ZoneInfo

from starlette.requests import Request
from starlette.responses import Response, PlainTextResponse, JSONResponse
from sqlalchemy import select

from app.database import async_session
from app.models import User, UserData, EventGroup
from app.core.security import verify_password
from app.dependencies import verify_jwt

from app.caldav.xml_utils import (
    dav, caldav, cs, ical,
    make_multistatus, add_response, add_propstat,
    get_prop, set_text_prop, set_href_prop,
    serialize_xml, parse_xml_body, get_local_name,
)
from app.caldav.etag import compute_event_etag, compute_calendar_ctag
from app.caldav.ical_builder import (
    build_single_event_ical, build_series_ical, get_event_uid,
    build_single_reminder_ical, get_reminder_uid, should_include_reminder,
    UID_DOMAIN,
)
from app.caldav.ical_parser import ical_to_all_event_dicts

MAX_PUT_BODY_SIZE = 512 * 1024
BEIJING_TZ = datetime.timezone(datetime.timedelta(hours=8))


class CalDAVApp:
    """ASGI application for CalDAV protocol."""

    def __init__(self):
        pass

    async def __call__(self, scope, receive, send):
        request = Request(scope, receive, send)
        method = request.method.upper()
        path = request.url.path

        if method == "OPTIONS":
            return await self._send_response(send, self._options_response(request))

        # Authenticate
        user = await self._authenticate(request)
        if user is None:
            resp = PlainTextResponse("Unauthorized", status_code=401)
            resp.headers["WWW-Authenticate"] = 'Basic realm="UniScheduler CalDAV"'
            resp.headers["DAV"] = "1, 2, 3, calendar-access"
            return await self._send_response(send, resp)

        # Route
        try:
            if path == "/caldav/" or path == "/caldav":
                resp = await self._service_root(request, user, method)
            elif path == "/.well-known/caldav":
                resp = await self._wellknown(request, user)
            elif path.startswith("/caldav/principals/"):
                parts = path.rstrip("/").split("/")
                username = parts[3] if len(parts) >= 4 else ""
                resp = await self._principal(request, user, username, method)
            elif path.startswith("/caldav/"):
                parts = path.rstrip("/").split("/")
                username = parts[2] if len(parts) >= 3 else ""
                calendar_id = parts[3] if len(parts) >= 4 else ""
                event_uid = parts[4] if len(parts) >= 5 else ""

                if not calendar_id and method in ("PROPFIND", "GET", "HEAD"):
                    # Calendar home: /caldav/<username>/
                    resp = await self._calendar_home(request, user, username, method)
                elif calendar_id and not event_uid:
                    # Calendar collection: /caldav/<username>/<cal>/
                    resp = await self._calendar_collection(request, user, username, calendar_id, method)
                elif calendar_id and event_uid:
                    # Event object: /caldav/<username>/<cal>/<uid>.ics
                    uid = event_uid.replace(".ics", "")
                    resp = await self._event_object(request, user, username, calendar_id, uid, method)
                else:
                    resp = PlainTextResponse("Not Found", status_code=404)
            else:
                resp = PlainTextResponse("Not Found", status_code=404)
        except Exception as e:
            resp = PlainTextResponse(f"Internal Error: {e}", status_code=500)

        resp.headers["DAV"] = "1, 2, 3, calendar-access"
        return await self._send_response(send, resp)

    async def _send_response(self, send, response: Response):
        await response(scope=None, receive=None, send=send)

    def _options_response(self, request):
        resp = PlainTextResponse("", status_code=200)
        resp.headers["Allow"] = "OPTIONS, GET, HEAD, PUT, DELETE, PROPFIND, REPORT, MKCALENDAR"
        return resp

    # ---- Auth ----

    async def _authenticate(self, request: Request) -> Optional[User]:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            return None

        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            except Exception:
                return None
            username, _, password = decoded.partition(":")
            if not username or not password:
                return None

            async with async_session() as db:
                # Try token as password
                result = await db.execute(select(User).where(User.username == username))
                user = result.scalar_one_or_none()
                if user:
                    # Try token auth
                    jwt_payload = verify_jwt(password)
                    if jwt_payload and int(jwt_payload.get("sub", 0)) == user.id:
                        return user
                    # Try password auth
                    if verify_password(password, user.hashed_password):
                        return user
            return None

        if auth_header.startswith("Bearer ") or auth_header.startswith("Token "):
            token_value = auth_header.split(" ", 1)[1].strip()
            payload = verify_jwt(token_value)
            if payload and "sub" in payload:
                async with async_session() as db:
                    result = await db.execute(select(User).where(User.id == int(payload["sub"]), User.is_active == True))
                    return result.scalar_one_or_none()
            return None

        return None

    # ---- .well-known ----

    async def _wellknown(self, request: Request, user: Optional[User]):
        if user is None:
            return PlainTextResponse("Unauthorized", status_code=401, headers={
                "WWW-Authenticate": 'Basic realm="UniScheduler CalDAV"',
                "DAV": "1, 2, 3, calendar-access",
            })

        multistatus = make_multistatus()
        resp_el = add_response(multistatus, '/.well-known/caldav')
        propstat = add_propstat(resp_el)
        prop = get_prop(propstat)
        rt = ET.SubElement(prop, dav("resourcetype"))
        ET.SubElement(rt, dav("collection"))
        set_href_prop(prop, dav("current-user-principal"), f'/caldav/principals/{user.username}/')

        body = serialize_xml(multistatus)
        return Response(content=body, media_type="application/xml; charset=utf-8", status_code=207)

    # ---- Service Root ----

    async def _service_root(self, request: Request, user: User, method: str):
        multistatus = make_multistatus()
        resp = add_response(multistatus, '/caldav/')
        propstat = add_propstat(resp)
        prop = get_prop(propstat)
        rt = ET.SubElement(prop, dav("resourcetype"))
        ET.SubElement(rt, dav("collection"))
        set_href_prop(prop, dav("current-user-principal"), f'/caldav/principals/{user.username}/')
        set_href_prop(prop, dav("principal-URL"), f'/caldav/principals/{user.username}/')
        body = serialize_xml(multistatus)
        return Response(content=body, media_type="application/xml; charset=utf-8", status_code=207)

    # ---- Principal ----

    async def _principal(self, request: Request, user: User, username: str, method: str):
        if user.username != username:
            return PlainTextResponse("Access denied", status_code=403)

        multistatus = make_multistatus()
        resp = add_response(multistatus, f'/caldav/principals/{username}/')
        propstat = add_propstat(resp)
        prop = get_prop(propstat)
        set_text_prop(prop, dav("displayname"), username)
        rt = ET.SubElement(prop, dav("resourcetype"))
        ET.SubElement(rt, dav("collection"))
        ET.SubElement(rt, dav("principal"))
        set_href_prop(prop, caldav("calendar-home-set"), f'/caldav/{username}/')
        set_href_prop(prop, dav("principal-URL"), f'/caldav/principals/{username}/')
        set_href_prop(prop, dav("current-user-principal"), f'/caldav/principals/{username}/')
        srs = ET.SubElement(prop, dav("supported-report-set"))
        for report_name in ["calendar-multiget", "calendar-query"]:
            sr = ET.SubElement(srs, dav("supported-report"))
            r = ET.SubElement(sr, dav("report"))
            ET.SubElement(r, caldav(report_name))
        body = serialize_xml(multistatus)
        return Response(content=body, media_type="application/xml; charset=utf-8", status_code=207)

    # ---- Calendar Home ----

    async def _calendar_home(self, request: Request, user: User, username: str, method: str):
        if user.username != username:
            return PlainTextResponse("Access denied", status_code=403)

        depth = request.headers.get("Depth", "1")
        all_events = await self._load_events(user.id)
        groups = await self._load_event_groups(user.id)
        reminders = await self._load_reminders(user.id)

        multistatus = make_multistatus()
        # Home itself
        resp_el = add_response(multistatus, f'/caldav/{username}/')
        ps = add_propstat(resp_el)
        p = get_prop(ps)
        rt = ET.SubElement(p, dav("resourcetype"))
        ET.SubElement(rt, dav("collection"))
        set_text_prop(p, dav("displayname"), "UniScheduler")
        cup = ET.SubElement(p, dav("current-user-principal"))
        href_el = ET.SubElement(cup, dav("href"))
        href_el.text = f'/caldav/principals/{username}/'

        if depth != "0":
            group_ids = {g.get('id') for g in groups if g.get('id')}
            ungrouped = [e for e in all_events if not e.get('groupID') or e.get('groupID') not in group_ids]
            self._add_calendar_response(multistatus, username, 'default', 'UniScheduler', '#4A90E2FF', ungrouped)

            for g in groups:
                gid = g.get('id', '')
                if not gid:
                    continue
                ge = [e for e in all_events if e.get('groupID') == gid]
                color_hex = g.get('color', '#888888')
                if len(color_hex) == 7:
                    color_hex += 'FF'
                self._add_calendar_response(multistatus, username, gid, g.get('name', gid), color_hex, ge)

            visible_reminders = [r for r in reminders if should_include_reminder(r)]
            self._add_calendar_response(multistatus, username, 'reminders', 'Reminders', '#FF6B6BFF', visible_reminders)

        body = serialize_xml(multistatus)
        return Response(content=body, media_type="application/xml; charset=utf-8", status_code=207)

    def _add_calendar_response(self, multistatus, username, calendar_id, display_name, color, events):
        resp = add_response(multistatus, f'/caldav/{username}/{calendar_id}/')
        ps = add_propstat(resp)
        p = get_prop(ps)
        rt = ET.SubElement(p, dav("resourcetype"))
        ET.SubElement(rt, dav("collection"))
        ET.SubElement(rt, caldav("calendar"))
        set_text_prop(p, dav("displayname"), display_name)
        set_text_prop(p, ical("calendar-color"), color)
        set_text_prop(p, cs("getctag"), compute_calendar_ctag(events))
        sccs = ET.SubElement(p, caldav("supported-calendar-component-set"))
        comp = ET.SubElement(sccs, caldav("comp"))
        comp.set("name", "VEVENT")

    # ---- Calendar Collection ----

    async def _calendar_collection(self, request: Request, user: User, username: str, calendar_id: str, method: str):
        if user.username != username:
            return PlainTextResponse("Access denied", status_code=403)

        if method == "MKCALENDAR":
            return PlainTextResponse("Calendar creation is managed by the server.", status_code=403)

        depth = request.headers.get("Depth", "1")
        events = await self._get_events_for_calendar(user.id, calendar_id)
        is_rem = (calendar_id == 'reminders')

        multistatus = make_multistatus()
        # Collection itself
        resp = add_response(multistatus, f'/caldav/{username}/{calendar_id}/')
        ps = add_propstat(resp)
        p = get_prop(ps)
        rt = ET.SubElement(p, dav("resourcetype"))
        ET.SubElement(rt, dav("collection"))
        ET.SubElement(rt, caldav("calendar"))
        display_name = await self._get_calendar_display_name(user.id, calendar_id)
        set_text_prop(p, dav("displayname"), display_name)
        color = await self._get_calendar_color(user.id, calendar_id)
        set_text_prop(p, ical("calendar-color"), color)
        set_text_prop(p, cs("getctag"), compute_calendar_ctag(events))
        sccs = ET.SubElement(p, caldav("supported-calendar-component-set"))
        comp = ET.SubElement(sccs, caldav("comp"))
        comp.set("name", "VEVENT")

        if depth != "0":
            seen_uids = set()
            for item in events:
                if is_rem:
                    self._add_item_stub(multistatus, username, calendar_id, item, is_reminder=True)
                else:
                    if not self._should_include_event(item):
                        continue
                    uid = get_event_uid(item)
                    if uid in seen_uids:
                        continue
                    seen_uids.add(uid)
                    self._add_item_stub(multistatus, username, calendar_id, item)

        if method == "REPORT":
            body = await request.body()
            if body:
                root = parse_xml_body(body)
                local_name = get_local_name(root.tag)
                if local_name == 'calendar-multiget':
                    return await self._handle_multiget(root, events, user, username, calendar_id, is_rem)
                elif local_name == 'calendar-query':
                    return await self._handle_calendar_query(root, events, user, username, calendar_id, is_rem)

        body = serialize_xml(multistatus)
        return Response(content=body, media_type="application/xml; charset=utf-8", status_code=207)

    def _add_item_stub(self, multistatus, username, calendar_id, item, is_reminder=False):
        uid = get_reminder_uid(item) if is_reminder else get_event_uid(item)
        href = f'/caldav/{username}/{calendar_id}/{uid}.ics'
        resp = add_response(multistatus, href)
        ps = add_propstat(resp)
        p = get_prop(ps)
        set_text_prop(p, dav("getetag"), compute_event_etag(item))
        set_text_prop(p, dav("getcontenttype"), "text/calendar; charset=utf-8")
        ET.SubElement(p, dav("resourcetype"))

    def _add_item_full(self, multistatus, href, item, user_id, calendar_id=None, is_reminder=False):
        resp = add_response(multistatus, href)
        ps = add_propstat(resp)
        p = get_prop(ps)
        set_text_prop(p, dav("getetag"), compute_event_etag(item))
        set_text_prop(p, dav("getcontenttype"), "text/calendar; charset=utf-8")
        if is_reminder:
            ical_bytes = build_single_reminder_ical(item)
        else:
            ical_bytes = build_single_event_ical(item)
        set_text_prop(p, caldav("calendar-data"), ical_bytes.decode('utf-8'))
        ET.SubElement(p, dav("resourcetype"))

    def _should_include_event(self, event: dict) -> bool:
        is_recurring = event.get("is_recurring", False)
        is_main = event.get("is_main_event", False)
        is_detached = event.get("is_detached", False)
        if is_detached:
            return True
        if is_recurring and not is_main:
            return False
        return True

    async def _handle_multiget(self, root, events, user, username, calendar_id, is_rem):
        item_by_uid = {}
        for item in events:
            if is_rem:
                uid = get_reminder_uid(item)
                item_by_uid[uid] = item
            else:
                if self._should_include_event(item):
                    uid = get_event_uid(item)
                    if uid not in item_by_uid or item.get('is_main_event'):
                        item_by_uid[uid] = item

        requested_hrefs = set()
        for href_el in root.iter(dav("href")):
            if href_el.text:
                requested_hrefs.add(href_el.text.strip())

        multistatus = make_multistatus()
        for href in requested_hrefs:
            uid = href.rstrip('/').rsplit('/', 1)[-1]
            if uid.endswith('.ics'):
                uid = uid[:-4]
            item = item_by_uid.get(uid)
            if item:
                self._add_item_full(multistatus, href, item, user.id, calendar_id, is_rem)
            else:
                resp = add_response(multistatus, href)
                add_propstat(resp, status="HTTP/1.1 404 Not Found")

        body = serialize_xml(multistatus)
        return Response(content=body, media_type="application/xml; charset=utf-8", status_code=207)

    async def _handle_calendar_query(self, root, events, user, username, calendar_id, is_rem):
        time_start, time_end = self._extract_time_range(root)
        multistatus = make_multistatus()
        seen_uids = set()
        for item in events:
            if is_rem:
                if time_start or time_end:
                    if not self._reminder_in_time_range(item, time_start, time_end):
                        continue
                uid = get_reminder_uid(item)
                href = f'/caldav/{username}/{calendar_id}/{uid}.ics'
                self._add_item_full(multistatus, href, item, user.id, calendar_id, True)
            else:
                if not self._should_include_event(item):
                    continue
                if time_start or time_end:
                    if not self._event_in_time_range(item, time_start, time_end):
                        continue
                uid = get_event_uid(item)
                if uid in seen_uids:
                    continue
                seen_uids.add(uid)
                href = f'/caldav/{username}/{calendar_id}/{uid}.ics'
                self._add_item_full(multistatus, href, item, user.id, calendar_id, False)

        body = serialize_xml(multistatus)
        return Response(content=body, media_type="application/xml; charset=utf-8", status_code=207)

    def _extract_time_range(self, root):
        time_start = None
        time_end = None
        for tr in root.iter(caldav("time-range")):
            start_str = tr.get("start", "")
            end_str = tr.get("end", "")
            if start_str:
                time_start = self._parse_caldav_datetime(start_str)
            if end_str:
                time_end = self._parse_caldav_datetime(end_str)
        return time_start, time_end

    def _parse_caldav_datetime(self, val: str) -> Optional[datetime.datetime]:
        val = val.strip()
        try:
            if val.endswith('Z'):
                return datetime.datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc)
            elif 'T' in val:
                return datetime.datetime.strptime(val, "%Y%m%dT%H%M%S")
            else:
                return datetime.datetime.strptime(val, "%Y%m%d")
        except (ValueError, TypeError):
            return None

    def _event_in_time_range(self, event: dict, time_start, time_end) -> bool:
        from app.caldav.ical_builder import _parse_dt
        evt_start = _parse_dt(event.get("start", ""))
        evt_end = _parse_dt(event.get("end", ""))
        if not evt_start:
            return False
        if evt_end is None:
            evt_end = evt_start
        if evt_start.tzinfo is None:
            evt_start = evt_start.replace(tzinfo=BEIJING_TZ)
        if evt_end.tzinfo is None:
            evt_end = evt_end.replace(tzinfo=BEIJING_TZ)
        if time_start and evt_end < time_start:
            return False
        if time_end and evt_start > time_end:
            return False
        return True

    def _reminder_in_time_range(self, reminder: dict, time_start, time_end) -> bool:
        from app.caldav.ical_builder import _parse_dt
        trigger = _parse_dt(reminder.get("trigger_time", ""))
        if not trigger:
            return False
        if trigger.tzinfo is None:
            trigger = trigger.replace(tzinfo=BEIJING_TZ)
        if time_start and trigger < time_start:
            return False
        if time_end and trigger > time_end:
            return False
        return True

    # ---- Event Object ----

    async def _event_object(self, request: Request, user: User, username: str, calendar_id: str, event_uid: str, method: str):
        if user.username != username:
            return PlainTextResponse("Access denied", status_code=403)

        if method == "GET":
            return await self._event_get(user, calendar_id, event_uid)
        elif method == "PUT":
            return await self._event_put(request, user, username, calendar_id, event_uid)
        elif method == "DELETE":
            return await self._event_delete(request, user, calendar_id, event_uid)
        return PlainTextResponse("Method Not Allowed", status_code=405)

    async def _event_get(self, user: User, calendar_id: str, event_uid: str):
        item = await self._find_item(user.id, calendar_id, event_uid)
        if item is None:
            return PlainTextResponse("Event not found", status_code=404)

        if calendar_id == 'reminders':
            ical_bytes = build_single_reminder_ical(item)
        else:
            ical_bytes = build_single_event_ical(item)

        etag = compute_event_etag(item)
        resp = Response(content=ical_bytes, media_type="text/calendar; charset=utf-8")
        resp.headers["ETag"] = etag
        return resp

    async def _event_put(self, request: Request, user: User, username: str, calendar_id: str, event_uid: str):
        if calendar_id == 'reminders':
            return PlainTextResponse("Reminders calendar is read-only via CalDAV.", status_code=403)

        body = await request.body()
        if len(body) > MAX_PUT_BODY_SIZE:
            return PlainTextResponse("Request body too large.", status_code=413)

        existing = await self._find_item(user.id, calendar_id, event_uid)

        if_match = request.headers.get("If-Match", "").strip()
        if existing and if_match:
            current_etag = compute_event_etag(existing)
            if if_match != '*' and if_match != current_etag:
                return Response(status_code=412)

        if_none_match = request.headers.get("If-None-Match", "").strip()
        if if_none_match == '*' and existing:
            return Response(status_code=412)

        try:
            main_data, exceptions = ical_to_all_event_dicts(body, existing_event=existing)
        except ValueError as e:
            return PlainTextResponse(f"Invalid iCalendar data: {e}", status_code=400)

        if calendar_id != 'default':
            main_data['groupID'] = calendar_id
        elif existing:
            main_data['groupID'] = existing.get('groupID', '')

        if existing:
            if exceptions:
                await self._handle_recurring_put(user, existing, main_data, exceptions, calendar_id)
            else:
                await self._handle_update(user, existing, main_data)
        else:
            await self._handle_create(user, main_data, calendar_id, username, event_uid)

        updated = await self._find_item(user.id, calendar_id, event_uid)
        etag = compute_event_etag(updated) if updated else ''
        resp = Response(status_code=204 if existing else 201)
        if existing:
            resp.headers["Location"] = f'/caldav/{username}/{calendar_id}/{event_uid}.ics'
        if etag:
            resp.headers["ETag"] = etag
        return resp

    async def _event_delete(self, request: Request, user: User, calendar_id: str, event_uid: str):
        if calendar_id == 'reminders':
            return PlainTextResponse("Reminders calendar is read-only via CalDAV.", status_code=403)

        existing = await self._find_item(user.id, calendar_id, event_uid)
        if existing is None:
            return PlainTextResponse("Event not found", status_code=404)

        if_match = request.headers.get("If-Match", "").strip()
        if if_match and if_match != '*':
            current_etag = compute_event_etag(existing)
            if if_match != current_etag:
                return Response(status_code=412)

        # Delete entire series if main event, else single
        if existing.get('is_main_event') and existing.get('series_id'):
            from app.services.event_service import delete_event as svc_delete
            try:
                await svc_delete(async_session(), user.id, existing['id'], 'all')
            except ValueError:
                return PlainTextResponse("Event not found", status_code=404)
        else:
            from app.services.event_service import delete_event as svc_delete
            async with async_session() as db:
                try:
                    await svc_delete(db, user.id, existing['id'], 'single')
                except ValueError:
                    return PlainTextResponse("Event not found", status_code=404)

        return Response(status_code=204)

    # ---- PUT handlers ----

    async def _handle_create(self, user: User, new_data: dict, calendar_id: str, username: str, event_uid: str):
        internal_id = event_uid
        if internal_id.startswith('evt-'):
            internal_id = internal_id[4:]
        new_data['id'] = internal_id
        new_data.setdefault('status', 'confirmed')
        new_data.setdefault('last_modified', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        new_data.setdefault('groupID', '')
        new_data.setdefault('description', '')
        new_data.setdefault('importance', '')
        new_data.setdefault('urgency', '')
        new_data.setdefault('ddl', '')
        new_data.setdefault('tags', [])
        new_data.setdefault('linked_reminders', [])
        new_data.setdefault('shared_to_groups', [])

        async with async_session() as db:
            row, events = await self._get_user_data_row(db, user.id, "events")
            if not isinstance(events, list):
                events = []
            events = [e for e in events if e.get('id') != internal_id]
            events.append(new_data)
            row.set_value(events)
            await db.commit()

    async def _handle_update(self, user: User, existing: dict, new_data: dict):
        event_id = existing['id']
        async with async_session() as db:
            row, events = await self._get_user_data_row(db, user.id, "events")
            if not isinstance(events, list):
                return
            for event in events:
                if event.get('id') == event_id:
                    for field in ('title', 'start', 'end', 'description', 'importance', 'urgency', 'groupID', 'location', 'status', 'rrule'):
                        if field in new_data:
                            event[field] = new_data[field]
                    if 'caldav_uid' in new_data:
                        uid = new_data['caldav_uid']
                        if not uid.endswith(f'@{UID_DOMAIN}'):
                            event['caldav_uid'] = uid
                    event['last_modified'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    break
            row.set_value(events)
            await db.commit()

    async def _handle_recurring_put(self, user: User, existing: dict, main_data: dict, exceptions: list, calendar_id: str):
        series_id = existing.get('series_id', '')
        if not series_id:
            await self._handle_update(user, existing, main_data)
            return

        async with async_session() as db:
            row, events = await self._get_user_data_row(db, user.id, "events")
            if not isinstance(events, list):
                return

            # Update main event
            for event in events:
                if event.get('id') == existing['id']:
                    for field in ('title', 'start', 'end', 'description', 'location', 'status', 'rrule'):
                        if field in main_data:
                            event[field] = main_data[field]
                    if 'caldav_uid' in main_data:
                        uid = main_data['caldav_uid']
                        if not uid.endswith(f'@{UID_DOMAIN}'):
                            event['caldav_uid'] = uid
                    event['last_modified'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    break

            existing_detached_rids = set()
            for e in events:
                if e.get('is_detached') and e.get('series_id') == series_id:
                    rid = e.get('recurrence_id', '')
                    if rid:
                        existing_detached_rids.add(rid)

            for exc in exceptions:
                rec_id = exc.get('recurrence_id', '')
                if not rec_id:
                    continue
                if rec_id in existing_detached_rids:
                    for e in events:
                        if e.get('is_detached') and e.get('recurrence_id') == rec_id and e.get('series_id') == series_id:
                            for field in ('title', 'start', 'end', 'description', 'location', 'status'):
                                if field in exc:
                                    e[field] = exc[field]
                            e['last_modified'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            break
                    continue

                target = None
                for e in events:
                    if e.get('series_id') == series_id and e.get('recurrence_id') == rec_id and not e.get('is_main_event') and not e.get('is_detached'):
                        target = e
                        break
                main_caldav_uid = existing.get('caldav_uid', '')
                if target:
                    target['is_detached'] = True
                    target['is_exception'] = True
                    if main_caldav_uid:
                        target['caldav_uid'] = main_caldav_uid
                    for field in ('title', 'start', 'end', 'description', 'location', 'status'):
                        if field in exc:
                            target[field] = exc[field]
                    target['last_modified'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                else:
                    new_instance = {
                        'id': str(uuid.uuid4()),
                        'series_id': series_id,
                        'is_recurring': True,
                        'is_main_event': False,
                        'is_detached': True,
                        'is_exception': True,
                        'recurrence_id': rec_id,
                        'groupID': existing.get('groupID', ''),
                        'status': 'confirmed',
                        'description': '', 'importance': '', 'urgency': '', 'ddl': '',
                        'tags': [], 'linked_reminders': [], 'shared_to_groups': [],
                        'last_modified': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    }
                    if main_caldav_uid:
                        new_instance['caldav_uid'] = main_caldav_uid
                    for field in ('title', 'start', 'end', 'description', 'location', 'status'):
                        if field in exc:
                            new_instance[field] = exc[field]
                    events.append(new_instance)

            row.set_value(events)
            await db.commit()

    # ---- Data access helpers ----

    async def _load_events(self, user_id: int) -> list:
        async with async_session() as db:
            row, data = await self._get_user_data_row(db, user_id, "events")
            return data if isinstance(data, list) else []

    async def _load_event_groups(self, user_id: int) -> list:
        async with async_session() as db:
            result = await db.execute(select(EventGroup).where(EventGroup.user_id == user_id))
            groups = result.scalars().all()
            return [{"id": g.id, "name": g.name, "description": g.description,
                     "color": g.color, "type": g.typ} for g in groups]

    async def _load_reminders(self, user_id: int) -> list:
        async with async_session() as db:
            row, data = await self._get_user_data_row(db, user_id, "reminders")
            return data if isinstance(data, list) else []

    async def _get_events_for_calendar(self, user_id: int, calendar_id: str) -> list:
        if calendar_id == 'reminders':
            reminders = await self._load_reminders(user_id)
            return [r for r in reminders if should_include_reminder(r)]
        events = await self._load_events(user_id)
        if calendar_id == 'default':
            groups = await self._load_event_groups(user_id)
            group_ids = {g.get('id') for g in groups if g.get('id')}
            return [e for e in events if not e.get('groupID') or e.get('groupID') not in group_ids]
        return [e for e in events if e.get('groupID') == calendar_id]

    async def _get_user_data_row(self, db, user_id: int, key: str):
        from app.models import UserData
        result = await db.execute(select(UserData).where(UserData.user_id == user_id, UserData.key == key))
        row = result.scalar_one_or_none()
        if row is None:
            row = UserData(user_id=user_id, key=key, value="[]")
            db.add(row)
            await db.flush()
        return row, row.get_value()

    async def _find_item(self, user_id: int, calendar_id: str, event_uid: str) -> Optional[dict]:
        items = await self._get_events_for_calendar(user_id, calendar_id)
        is_rem = (calendar_id == 'reminders')
        for item in items:
            uid = get_reminder_uid(item) if is_rem else get_event_uid(item)
            if uid == event_uid:
                return item
        for item in items:
            if item.get('caldav_uid') == event_uid or item.get('id') == event_uid:
                return item
        return None

    async def _get_calendar_display_name(self, user_id: int, calendar_id: str) -> str:
        if calendar_id == 'default':
            return 'UniScheduler'
        if calendar_id == 'reminders':
            return 'Reminders'
        groups = await self._load_event_groups(user_id)
        for g in groups:
            if g.get('id') == calendar_id:
                return g.get('name', calendar_id)
        return calendar_id

    async def _get_calendar_color(self, user_id: int, calendar_id: str) -> str:
        color = '#4A90E2'
        if calendar_id == 'reminders':
            color = '#FF6B6B'
        elif calendar_id != 'default':
            groups = await self._load_event_groups(user_id)
            for g in groups:
                if g.get('id') == calendar_id:
                    color = g.get('color', '#888888')
                    break
        if len(color) == 7:
            color += 'FF'
        return color


caldav_app = CalDAVApp()
