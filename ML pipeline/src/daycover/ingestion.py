"""Validated v2 NEA snapshots. Interval rain is never a daily total."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from zoneinfo import ZoneInfo

SGT = ZoneInfo('Asia/Singapore')
REGIONS = {'north', 'south', 'east', 'west', 'central'}

@dataclass(frozen=True)
class Reading:
    station: str
    metric: str
    observed_at: datetime
    value: float
    unit: str
    source: str = 'NEA_SINGAPORE_API_V2'

    def __post_init__(self):
        if self.observed_at.tzinfo is None or not math.isfinite(self.value) or self.value < 0:
            raise ValueError('Invalid canonical reading')
        allowed = {'rainfall_5min_mm': 'mm', 'psi_24hr': 'PSI'}
        if allowed.get(self.metric) != self.unit or (self.metric == 'psi_24hr' and self.value > 500):
            raise ValueError('Invalid canonical metric/unit/value')


def parse_snapshot(payload, kind, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(payload, dict) or payload.get('code') != 0 or not isinstance(payload.get('data'), dict):
        raise ValueError('Missing/failed NEA payload; no fabricated fallback')
    data = payload['data']
    if kind == 'rain':
        if data.get('readingUnit') != 'mm' or data.get('readingType') != 'TB1 Rainfall 5 Minute Total F':
            raise ValueError('Unexpected rain unit or interval')
        stations = {s['id'] for s in data.get('stations', [])}
        items = data.get('readings', [])
    elif kind == 'psi':
        stations = REGIONS
        items = data.get('items', [])
    else:
        raise ValueError('Unknown metric')
    if not items:
        raise ValueError('Missing readings')
    out, seen = [], set()
    for item in items:
        ts = datetime.fromisoformat(item['timestamp'])
        if ts.tzinfo is None or now.tzinfo is None:
            raise ValueError('Timezone required')
        if not -timedelta(minutes=5) <= now-ts <= timedelta(minutes=30 if kind == 'rain' else 120):
            raise ValueError('Stale/future snapshot')
        pairs = [(r['stationId'], r['value']) for r in item.get('data', [])] if kind == 'rain' else list(item.get('readings', {}).get('psi_twenty_four_hourly', {}).items())
        if not pairs:
            raise ValueError('Missing metric')
        for station, val in pairs:
            if station not in stations or isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or val < 0 or (kind == 'psi' and val > 500):
                raise ValueError('Unknown station or invalid value')
            key = (station, ts)
            if key in seen:
                raise ValueError('Duplicate station/time in snapshot')
            seen.add(key)
            out.append(Reading(station if kind == 'rain' else 'REGION_'+station.upper(),
                               'rainfall_5min_mm' if kind == 'rain' else 'psi_24hr', ts, float(val), 'mm' if kind == 'rain' else 'PSI'))
    return out


def daily_summary(readings, day, station, kind):
    """Strict complete-day aggregation; missing bins remain pending, never zero.

    Research assumption only: end-labelled (00:00, next midnight] rain.
    Official API interval labelling is unverified; persisted evidence uses a gate.
    PSI uses hourly timestamps [00:00, 23:00]. Equal duplicates are idempotent;
    conflicting revisions require review rather than silent replacement.
    """
    if kind not in ('rain', 'psi'):
        raise ValueError('Unknown summary metric')
    metric = 'rainfall_5min_mm' if kind == 'rain' else 'psi_24hr'
    step, count = (5, 288) if kind == 'rain' else (60, 24)
    start = datetime.combine(day, datetime.min.time(), SGT)
    expected = {start + timedelta(minutes=step*i) for i in (range(1, count+1) if kind == 'rain' else range(count))}
    values = {}
    for r in readings:
        ts = r.observed_at.astimezone(SGT)
        if r.station != station or r.metric != metric or ts not in expected:
            continue
        if ts in values and values[ts] != r.value:
            raise ValueError('Conflicting duplicate observation')
        values[ts] = r.value
    return {'status': 'complete' if len(values) == count else 'pending',
            'value': (sum(values.values()) if kind == 'rain' else max(values.values())) if len(values) == count else None,
            'observed_bins': len(values), 'expected_bins': count, 'date_sgt': str(day), 'station': station,
            'unit': 'mm/day' if kind == 'rain' else 'PSI', 'source': 'official_singapore'}
