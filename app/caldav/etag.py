"""
ETag / CTag 计算工具 — ported from caldav_service/etag.py
"""

import hashlib


def compute_event_etag(event: dict) -> str:
    raw = f"{event.get('id', '')}:{event.get('last_modified', '')}"
    return f'"{hashlib.sha256(raw.encode()).hexdigest()[:32]}"'


def compute_calendar_ctag(events: list) -> str:
    if not events:
        return '"empty-0"'
    latest = max((e.get('last_modified', '') for e in events), default='')
    raw = f"{latest}:{len(events)}"
    return f'"{hashlib.sha256(raw.encode()).hexdigest()[:32]}"'
