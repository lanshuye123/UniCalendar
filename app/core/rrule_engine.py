"""
RRule Engine - 通用重复规则引擎
支持复杂的重复规则管理，包括规则变更、例外处理、实例生成等
Adapted from original rrule_engine.py — all Django dependencies removed.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import uuid
import json
import re

try:
    from dateutil.rrule import rrulestr, rruleset
    DATEUTIL_AVAILABLE = True
except ImportError:
    DATEUTIL_AVAILABLE = False


class RRuleSegment:
    """RRule规则段 - 表示某个时间段内的重复规则"""

    def __init__(self, uid: str, sequence: int, rrule_str: str,
                 dtstart: datetime, until: Optional[datetime] = None,
                 exdates: Optional[List[datetime]] = None,
                 created_at: Optional[datetime] = None):
        self.uid = uid
        self.sequence = sequence
        self.rrule_str = rrule_str
        self.dtstart = dtstart
        self.until = until
        self.exdates = exdates or []
        self.created_at = created_at or datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            'uid': self.uid,
            'sequence': self.sequence,
            'rrule_str': self.rrule_str,
            'dtstart': self.dtstart.isoformat(),
            'until': self.until.isoformat() if self.until else None,
            'exdates': [d.isoformat() for d in self.exdates],
            'created_at': self.created_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RRuleSegment':
        return cls(
            uid=data['uid'],
            sequence=data['sequence'],
            rrule_str=data['rrule_str'],
            dtstart=datetime.fromisoformat(data['dtstart']),
            until=datetime.fromisoformat(data['until']) if data.get('until') else None,
            exdates=[datetime.fromisoformat(d) for d in data.get('exdates', [])],
            created_at=datetime.fromisoformat(data['created_at'])
        )


class RRuleSeries:
    """RRule系列 - 管理一个完整的重复任务生命周期"""

    def __init__(self, uid: Optional[str] = None):
        self.uid = uid or str(uuid.uuid4())
        self.segments: List[RRuleSegment] = []

    def add_segment(self, rrule_str: str, dtstart: datetime,
                    until: Optional[datetime] = None) -> RRuleSegment:
        sequence = max([s.sequence for s in self.segments], default=0) + 1
        segment = RRuleSegment(
            uid=self.uid,
            sequence=sequence,
            rrule_str=rrule_str,
            dtstart=dtstart,
            until=until
        )
        self.segments.append(segment)
        return segment

    def add_exception(self, exception_date: datetime, segment_sequence: Optional[int] = None):
        if segment_sequence is None:
            target_segment = None
            for segment in sorted(self.segments, key=lambda s: s.sequence):
                if segment.dtstart <= exception_date:
                    if segment.until is None or exception_date <= segment.until:
                        target_segment = segment
                        break
            if target_segment:
                target_segment.exdates.append(exception_date)
        else:
            for segment in self.segments:
                if segment.sequence == segment_sequence:
                    segment.exdates.append(exception_date)
                    break

    def modify_rule_from_date(self, from_date: datetime, new_rrule_str: str) -> RRuleSegment:
        for segment in self.segments:
            if segment.dtstart <= from_date:
                if segment.until is None or segment.until > from_date:
                    segment.until = from_date - timedelta(days=1)
        new_segment = self.add_segment(new_rrule_str, from_date)
        return new_segment

    def truncate_until(self, until_date: datetime):
        actual_until = until_date - timedelta(seconds=1)
        for segment in self.segments:
            if segment.dtstart < until_date:
                if segment.until is None or segment.until > actual_until:
                    segment.until = actual_until
        self.segments = [s for s in self.segments if s.dtstart < until_date]

    def generate_instances(self, start_date: Optional[datetime] = None,
                           end_date: Optional[datetime] = None,
                           max_count: int = 100) -> List[datetime]:
        if start_date is None:
            start_date = datetime.now()
        if end_date is None:
            end_date = start_date + timedelta(days=365)

        if not DATEUTIL_AVAILABLE:
            return []

        rrset = rruleset()
        for segment in sorted(self.segments, key=lambda s: s.sequence):
            try:
                dtstart = segment.dtstart
                if dtstart.tzinfo is not None:
                    dtstart = dtstart.replace(tzinfo=None)

                processed_rrule = segment.rrule_str
                if 'UNTIL=' in segment.rrule_str:
                    until_match = re.search(r'UNTIL=([^;]+)', segment.rrule_str)
                    if until_match:
                        until_str = until_match.group(1)
                        if until_str.endswith('Z'):
                            try:
                                utc_dt = datetime.strptime(until_str[:-1], '%Y%m%dT%H%M%S')
                                local_dt = utc_dt - timedelta(hours=-8)  # Asia/Shanghai offset
                                until_naive = local_dt.strftime('%Y%m%dT%H%M%S')
                            except Exception:
                                until_naive = until_str[:-1]
                            processed_rrule = segment.rrule_str.replace(f'UNTIL={until_str}', f'UNTIL={until_naive}')

                full_rrule = f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%S')}\nRRULE:{processed_rrule}"

                if segment.until and 'UNTIL=' not in processed_rrule:
                    until_str = segment.until.strftime('%Y%m%dT%H%M%S')
                    full_rrule = f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%S')}\nRRULE:{processed_rrule};UNTIL={until_str}"

                rule_obj = rrulestr(full_rrule, dtstart=dtstart)
                rrset.rrule(rule_obj)

                for exdate in segment.exdates:
                    rrset.exdate(exdate)

            except Exception:
                continue

        instances = []
        try:
            for dt in rrset:
                if dt > end_date:
                    break
                if dt >= start_date:
                    instances.append(dt)
                if len(instances) >= max_count:
                    break
        except Exception:
            pass

        return instances

    def get_segments_data(self) -> List[Dict[str, Any]]:
        return [segment.to_dict() for segment in self.segments]

    @classmethod
    def from_segments_data(cls, segments_data: List[Dict[str, Any]]) -> 'RRuleSeries':
        if not segments_data:
            return cls()
        uid = segments_data[0]['uid']
        series = cls(uid)
        for data in segments_data:
            segment = RRuleSegment.from_dict(data)
            series.segments.append(segment)
        return series


class RRuleEngine:
    """RRule引擎 - 管理所有重复规则系列"""

    def __init__(self, storage_backend=None):
        self.storage = storage_backend
        self._cache: Dict[str, RRuleSeries] = {}

    def create_series(self, initial_rrule: str, dtstart: datetime,
                      until: Optional[datetime] = None) -> str:
        series = RRuleSeries()
        series.add_segment(initial_rrule, dtstart, until)
        if self.storage:
            self.storage.save_segments(series.uid, series.get_segments_data())
        self._cache[series.uid] = series
        return series.uid

    def get_series(self, uid: str) -> Optional[RRuleSeries]:
        if uid in self._cache:
            return self._cache[uid]
        if self.storage:
            segments_data = self.storage.load_segments(uid)
            if segments_data:
                series = RRuleSeries.from_segments_data(segments_data)
                self._cache[uid] = series
                return series
        return None

    def delete_instance(self, uid: str, instance_date: datetime):
        series = self.get_series(uid)
        if series:
            series.add_exception(instance_date)
            if self.storage:
                self.storage.save_segments(uid, series.get_segments_data())

    def modify_rule_from_date(self, uid: str, from_date: datetime, new_rrule: str):
        series = self.get_series(uid)
        if series:
            series.modify_rule_from_date(from_date, new_rrule)
            if self.storage:
                self.storage.save_segments(uid, series.get_segments_data())

    def generate_instances(self, uid: str, start_date: Optional[datetime] = None,
                           end_date: Optional[datetime] = None, max_count: int = 100) -> List[datetime]:
        series = self.get_series(uid)
        if series:
            return series.generate_instances(start_date, end_date, max_count)
        return []

    def delete_series(self, uid: str):
        if self.storage:
            self.storage.delete_segments(uid)
        if uid in self._cache:
            del self._cache[uid]

    def truncate_series_until(self, uid: str, until_date: datetime):
        series = self.get_series(uid)
        if series:
            series.truncate_until(until_date)
            if self.storage:
                self.storage.save_segments(uid, series.get_segments_data())
