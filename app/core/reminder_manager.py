import json
import uuid
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from dateutil.rrule import rrulestr

from app.core.rrule_engine import RRuleEngine


class StorageBackend:
    """Abstract storage backend for RRule data — subclass and provide DB session."""

    def save_segments(self, uid: str, segments_data: List[Dict[str, Any]]):
        raise NotImplementedError

    def load_segments(self, uid: str) -> Optional[List[Dict[str, Any]]]:
        raise NotImplementedError

    def delete_segments(self, uid: str):
        raise NotImplementedError

    def cleanup_orphaned_series(self, active_series_ids: set) -> int:
        return 0


class DictStorageBackend(StorageBackend):
    """In-memory storage backend keyed by user_id — for use with SQLAlchemy session."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        # Each user gets their own in-memory dict keyed by series_uid
        self._storage: Dict[int, Dict[str, list]] = {}

    def _ensure_user(self):
        if self.user_id not in self._storage:
            self._storage[self.user_id] = {}

    def save_segments(self, uid: str, segments_data: List[Dict[str, Any]]):
        self._ensure_user()
        self._storage[self.user_id][uid] = segments_data

    def load_segments(self, uid: str) -> Optional[List[Dict[str, Any]]]:
        self._ensure_user()
        return self._storage[self.user_id].get(uid)

    def delete_segments(self, uid: str):
        self._ensure_user()
        self._storage[self.user_id].pop(uid, None)

    def cleanup_orphaned_series(self, active_series_ids: set) -> int:
        self._ensure_user()
        stored_ids = set(self._storage[self.user_id].keys())
        orphaned = stored_ids - active_series_ids
        for uid in orphaned:
            del self._storage[self.user_id][uid]
        return len(orphaned)


class IntegratedReminderManager:
    """Integrated reminder manager — adapted from original, Django dependencies removed."""

    def __init__(self, user_id: int):
        self.rrule_engine = RRuleEngine(DictStorageBackend(user_id))
        self.user_id = user_id
        self.default_future_days = 365
        self.min_future_instances = 10
        self.max_instances_per_generation = 50

    def process_reminder_data(self, user_reminders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        active_series_ids = set()
        for reminder in user_reminders:
            series_id = reminder.get('series_id')
            if series_id:
                active_series_ids.add(series_id)
        if active_series_ids and hasattr(self.rrule_engine.storage, 'cleanup_orphaned_series'):
            self.rrule_engine.storage.cleanup_orphaned_series(active_series_ids)

        series_info = self._analyze_recurring_series(user_reminders)
        updated_reminders = user_reminders.copy()
        for series_id, info in series_info.items():
            if self._needs_more_instances(info):
                new_instances = self._generate_instances_for_series(info)
                updated_reminders.extend(new_instances)
        return updated_reminders

    def create_recurring_reminder(self, reminder_data: Dict[str, Any], rrule_str: str) -> Dict[str, Any]:
        start_time_str = reminder_data.get('trigger_time', '')
        try:
            start_time = datetime.fromisoformat(start_time_str.replace('Z', ''))
        except Exception:
            start_time = datetime.now()

        needs_next = self._is_complex_rrule(rrule_str)
        if needs_next:
            actual_start = self._find_next_occurrence(rrule_str, start_time)
            if actual_start:
                actual_start = actual_start.replace(
                    hour=start_time.hour, minute=start_time.minute,
                    second=start_time.second, microsecond=start_time.microsecond)
            else:
                actual_start = start_time
        else:
            actual_start = start_time

        series_id = self.rrule_engine.create_series(rrule_str, actual_start)
        now = datetime.now()
        main_status = 'dismissed' if actual_start < now else reminder_data.get('status', 'active')

        reminder_data.update({
            'id': str(uuid.uuid4()),
            'series_id': series_id,
            'rrule': rrule_str,
            'trigger_time': actual_start.isoformat(),
            'status': main_status,
            'is_recurring': True,
            'is_main_reminder': True,
            'created_at': datetime.now().isoformat(),
            'last_modified': datetime.now().isoformat()
        })
        return reminder_data

    def _is_complex_rrule(self, rrule_str: str) -> bool:
        patterns = ['BYWEEKDAY', 'BYMONTHDAY', 'BYSETPOS', 'BYYEARDAY', 'BYWEEKNO', 'BYDAY']
        return any(p in rrule_str for p in patterns)

    def _find_next_occurrence(self, rrule_str: str, start_time: datetime) -> Optional[datetime]:
        try:
            full_rrule = f"DTSTART:{start_time.strftime('%Y%m%dT%H%M%S')}\nRRULE:{rrule_str}"
            rule = rrulestr(full_rrule, dtstart=start_time)
            instances = list(rule[:5])
            if instances:
                first = instances[0]
                if (first.date() == start_time.date() and
                    first.hour == start_time.hour and
                        first.minute == start_time.minute):
                    return start_time
                return first
            return None
        except Exception:
            return None

    def delete_reminder_instance(self, reminders: List[Dict[str, Any]],
                                 reminder_id: str, series_id: str) -> List[Dict[str, Any]]:
        updated = []
        deleted = None
        for r in reminders:
            if r.get('id') == reminder_id:
                deleted = r
                continue
            updated.append(r)
        if deleted and series_id:
            trigger_str = deleted.get('trigger_time', '')
            try:
                trigger_time = datetime.fromisoformat(trigger_str.replace('Z', ''))
                self.rrule_engine.delete_instance(series_id, trigger_time)
            except Exception:
                pass
        return updated

    def delete_reminder_this_and_after(self, reminders: List[Dict[str, Any]],
                                       reminder_id: str, series_id: str) -> List[Dict[str, Any]]:
        target = next((r for r in reminders if r.get('id') == reminder_id), None)
        if not target or not series_id:
            return reminders
        trigger_str = target.get('trigger_time', '')
        try:
            trigger_time = datetime.fromisoformat(trigger_str.replace('Z', ''))
        except Exception:
            return reminders
        self.rrule_engine.truncate_series_until(series_id, trigger_time)
        updated = []
        for r in reminders:
            if r.get('series_id') == series_id:
                r_time_str = r.get('trigger_time', '')
                try:
                    r_time = datetime.fromisoformat(r_time_str.replace('Z', ''))
                    if r_time < trigger_time:
                        current_rrule = r.get('rrule', '')
                        until_time = trigger_time - timedelta(seconds=1)
                        until_str = until_time.strftime('%Y%m%dT%H%M%S')
                        if 'UNTIL=' in current_rrule.upper():
                            new_rrule = re.sub(r'UNTIL=\d{8}T\d{6}', f'UNTIL={until_str}', current_rrule, flags=re.IGNORECASE)
                        else:
                            sep = ';' if ';' in current_rrule else ''
                            new_rrule = f"{current_rrule};UNTIL={until_str}" if current_rrule else f"UNTIL={until_str}"
                        r['rrule'] = new_rrule
                        updated.append(r)
                except Exception:
                    updated.append(r)
            else:
                updated.append(r)
        return updated

    def modify_recurring_rule(self, reminders: List[Dict[str, Any]],
                              series_id: str, from_date: datetime,
                              new_rrule: str, scope: str = 'from_this',
                              additional_updates: Optional[Dict] = None) -> List[Dict[str, Any]]:
        if additional_updates is None:
            additional_updates = {}
        main_reminder = next(
            (r for r in reminders if r.get('series_id') == series_id and r.get('is_main_reminder', False)),
            None
        )
        if not main_reminder:
            return reminders

        updated = []
        if scope == 'all':
            for r in reminders:
                if r.get('series_id') == series_id:
                    if r.get('is_main_reminder', False):
                        r['rrule'] = new_rrule
                        r['last_modified'] = datetime.now().isoformat()
                        updated.append(r)
                else:
                    updated.append(r)
            series_info = {
                'series_id': series_id,
                'main_reminder': main_reminder,
                'rrule': new_rrule,
                'instances': []
            }
            new_instances = self._generate_instances_for_series(series_info)
            updated.extend(new_instances)

        elif scope == 'from_this':
            self.rrule_engine.truncate_series_until(series_id, from_date)
            new_series_id = self.rrule_engine.create_series(new_rrule, from_date)
            for r in reminders:
                if r.get('series_id') == series_id:
                    r_time_str = r.get('trigger_time', '')
                    try:
                        r_time = datetime.fromisoformat(r_time_str.replace('Z', ''))
                    except Exception:
                        r_time = None
                    if r_time and r_time < from_date:
                        current_rrule = r.get('rrule', '')
                        until_time = from_date - timedelta(seconds=1)
                        until_str = until_time.strftime('%Y%m%dT%H%M%S')
                        if 'UNTIL=' in current_rrule.upper():
                            new_rr = re.sub(r'UNTIL=\d{8}T\d{6}', f'UNTIL={until_str}', current_rrule, flags=re.IGNORECASE)
                        else:
                            new_rr = f"{current_rrule};UNTIL={until_str}" if current_rrule else f"UNTIL={until_str}"
                        r['rrule'] = new_rr
                        r['last_modified'] = datetime.now().isoformat()
                        updated.append(r)
                    else:
                        if r_time == from_date:
                            r['series_id'] = new_series_id
                            r['rrule'] = new_rrule
                            r['is_main_reminder'] = True
                            r['last_modified'] = datetime.now().isoformat()
                            r.pop('original_reminder_id', None)
                            r.update({k: v for k, v in additional_updates.items() if k != 'trigger_time'})
                            updated.append(r)
                else:
                    updated.append(r)

            new_main = next((r for r in updated if r.get('series_id') == new_series_id and r.get('is_main_reminder')), None)
            if new_main:
                series_info = {
                    'series_id': new_series_id,
                    'main_reminder': new_main,
                    'rrule': new_rrule,
                    'instances': []
                }
                new_instances = self._generate_instances_for_series(series_info, start_from=from_date + timedelta(days=1))
                updated.extend(new_instances)

        return updated

    def _analyze_recurring_series(self, reminders: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        series_info = {}
        for r in reminders:
            series_id = r.get('series_id')
            if not series_id or not r.get('rrule'):
                continue
            if series_id not in series_info:
                series_info[series_id] = {
                    'series_id': series_id,
                    'main_reminder': None,
                    'instances': [],
                    'rrule': r.get('rrule', ''),
                    'latest_modified': r.get('last_modified', '1970-01-01T00:00:00')
                }
            else:
                current_latest = series_info[series_id]['latest_modified']
                reminder_modified = r.get('last_modified', '1970-01-01T00:00:00')
                if reminder_modified > current_latest:
                    series_info[series_id]['rrule'] = r.get('rrule', '')
                    series_info[series_id]['latest_modified'] = reminder_modified
            if r.get('is_main_reminder', False):
                series_info[series_id]['main_reminder'] = r
                series_info[series_id]['rrule'] = r.get('rrule', '')
            else:
                series_info[series_id]['instances'].append(r)
        return series_info

    def _needs_more_instances(self, series_info: Dict[str, Any]) -> bool:
        series_id = series_info['series_id']
        try:
            series = self.rrule_engine.get_series(series_id)
            if series:
                now = datetime.now()
                recent_exceptions = 0
                for segment in series.segments:
                    for exdate in segment.exdates:
                        if exdate > now:
                            recent_exceptions += 1
                if recent_exceptions >= 3:
                    return False
        except Exception:
            pass

        now = datetime.now()
        future_count = 0
        latest = None
        for instance in series_info['instances']:
            try:
                t = datetime.fromisoformat(instance.get('trigger_time', '').replace('Z', ''))
                if t > now:
                    future_count += 1
                    if latest is None or t > latest:
                        latest = t
            except Exception:
                continue
        main = series_info.get('main_reminder')
        if main:
            try:
                mt = datetime.fromisoformat(main.get('trigger_time', '').replace('Z', ''))
                if mt > now:
                    future_count += 1
                    if latest is None or mt > latest:
                        latest = mt
            except Exception:
                pass

        rrule_str = series_info.get('rrule', '')
        has_until = 'UNTIL=' in rrule_str.upper()
        if has_until:
            until_match = re.search(r'UNTIL=(\d{8}T\d{4,6})', rrule_str.upper())
            if until_match:
                until_str = until_match.group(1)
                try:
                    if len(until_str) == 13:
                        until_str += '00'
                    elif len(until_str) == 15:
                        until_str = until_str[:13] + '00'
                    until_time = datetime.strptime(until_str, '%Y%m%dT%H%M%S')
                    if until_time <= now:
                        return False
                    if latest:
                        time_to_until = (until_time - latest).total_seconds()
                        if abs(time_to_until) < 86400:
                            return False
                    days_until_end = (until_time - now).days
                    return future_count < self.min_future_instances and days_until_end > 0
                except ValueError:
                    return False
            return False
        return future_count < self.min_future_instances

    def _generate_instances_for_series(self, series_info: Dict[str, Any],
                                       start_from: Optional[datetime] = None) -> List[Dict[str, Any]]:
        main_reminder = series_info.get('main_reminder')
        if not main_reminder:
            return []
        series_id = series_info['series_id']
        rrule = series_info.get('rrule', '')
        if not rrule:
            return []
        try:
            main_start = datetime.fromisoformat(main_reminder.get('trigger_time', '').replace('Z', ''))
        except Exception:
            main_start = datetime.now()
        now = datetime.now()
        if start_from is None:
            start_from = main_start
        reference = max(start_from, now)
        end_date = reference + timedelta(days=self.default_future_days)
        total_days = (end_date - start_from).days
        estimated = max(self.max_instances_per_generation, total_days + 10)
        instance_times = self.rrule_engine.generate_instances(series_id, start_from, end_date, estimated)

        existing_times = set()
        for inst in series_info['instances']:
            try:
                existing_times.add(datetime.fromisoformat(inst.get('trigger_time', '').replace('Z', '')))
            except Exception:
                pass
        try:
            existing_times.add(main_start)
        except Exception:
            pass

        rrule_str = series_info.get('rrule', '')
        until_time = None
        if 'UNTIL=' in rrule_str.upper():
            until_match = re.search(r'UNTIL=(\d{8}T\d{4,6})', rrule_str.upper())
            if until_match:
                until_str = until_match.group(1)
                try:
                    if len(until_str) == 13:
                        until_str += '00'
                    elif len(until_str) == 15:
                        until_str = until_str[:13] + '00'
                    until_time = datetime.strptime(until_str, '%Y%m%dT%H%M%S')
                except Exception:
                    pass

        new_instances = []
        for instance_time in instance_times:
            if instance_time in existing_times:
                continue
            if until_time and instance_time > until_time:
                continue
            instance_status = 'dismissed' if instance_time < now else 'active'
            new_inst = main_reminder.copy()
            new_inst.update({
                'id': str(uuid.uuid4()),
                'trigger_time': instance_time.isoformat(),
                'status': instance_status,
                'is_main_reminder': False,
                'is_instance': True,
                'original_reminder_id': main_reminder['id'],
                'created_at': datetime.now().isoformat(),
                'last_modified': datetime.now().isoformat()
            })
            new_instances.append(new_inst)
        return new_instances
