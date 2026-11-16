"""Resumable official API ingestion. All observations remain provisional; no decisions.

Raw bytes are immutable and content-addressed. A page and its cursor commit together.
No correction wins automatically: downstream aggregation must inspect every revision.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import base64
import hashlib
import json
import math
import os
import re
import time
import uuid
from email.utils import parsedate_to_datetime

import httpx

from .contracts import canonical_json
from .ingestion import Reading, REGIONS, SGT
from .ledger_repository import configured_repository, entity_id

SOURCE = 'NEA_SINGAPORE_API_V2'
PARSER_VERSION = 'nea-weather-v1-2026.11'
ENDPOINTS = {kind:'https://api-open.data.gov.sg/v2/real-time/api/'+path for kind,path in [('rain','rainfall'),('psi','psi')]}
MAX_BODY = 4 * 1024 * 1024
STALE = {'rain':timedelta(minutes=30), 'psi':timedelta(minutes=120)}


def utcnow():
    return datetime.now(timezone.utc)


def iso(stamp):
    if not isinstance(stamp, datetime) or stamp.tzinfo is None:
        raise ValueError('timezone_required')
    return stamp.astimezone(timezone.utc).isoformat()


class InvalidPage(ValueError):
    """Stable codes only: never put raw server messages, tokens or secrets in logs."""


def invalid(code):
    raise InvalidPage(code)


def timestamp(value):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            invalid('timezone_required')
        return result.astimezone(timezone.utc)
    except (TypeError,ValueError) as exc:
        raise InvalidPage('invalid_timestamp') from exc


def numeric(value, lower, upper=None):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < lower or (upper is not None and value > upper):
        invalid('invalid_numeric_range')
    return float(value)


@dataclass(frozen=True)
class Page:
    readings: list
    metadata: dict
    updated: dict
    next_token: str | None
    expected_interval_seconds: int


def parse_page(raw, kind, fetched_at, query_day=None):
    """Strict page adapter, separate from legacy freshness-only snapshot parser.

    Historical mode validates requested SGT date rather than rejecting all old data.
    Rain ticks: 5 minutes; PSI publication ticks: 15 minutes (not a daily/hourly aggregate).
    """
    if kind not in ENDPOINTS:
        invalid('unknown_metric')
    iso(fetched_at)
    try:
        payload = json.loads(raw, parse_constant=lambda _:invalid('nonfinite_json'))
        if not isinstance(payload,dict) or type(payload.get('code')) is not int or payload['code'] != 0 or not isinstance(payload.get('data'),dict):
            invalid('source_schema_changed_or_error')
        data = payload['data']
        token = data.get('paginationToken')
        if token is not None and (not isinstance(token,str) or not token or len(token)>4096):
            invalid('invalid_pagination_token')
        metadata = {}
        stations = data['stations'] if kind=='rain' else data['regionMetadata']
        if not isinstance(stations,list) or not stations:
            invalid('missing_station_metadata')
        for s in stations:
            name = s['id'] if kind=='rain' else s['name']
            if not isinstance(name,str) or (not re.fullmatch(r'S[0-9]{2,4}',name) if kind=='rain' else name not in REGIONS):
                invalid('invalid_station_id')
            station = name if kind=='rain' else 'REGION_'+name.upper()
            if station in metadata:
                invalid('duplicate_station_metadata')
            location = s['location'] if kind=='rain' else s['labelLocation']
            normalized = {'latitude':numeric(location['latitude'],-90,90), 'longitude':numeric(location['longitude'],-180,180)}
            if kind=='rain':
                if not isinstance(s['name'],str) or not s['name'] or len(s['name'])>256 or s.get('deviceId',name)!=name:
                    invalid('invalid_station_metadata')
                normalized['name']=s['name']
                normalized['device_id']=s.get('deviceId',name)
            else:
                normalized['name']=name
                normalized['location_kind']='regional_label_not_station_or_official_boundary'
            metadata[station]=normalized
        if kind=='psi' and set(metadata) != {'REGION_'+r.upper() for r in REGIONS}:
            invalid('region_metadata_changed')
        if kind=='rain' and (data.get('readingType')!='TB1 Rainfall 5 Minute Total F' or data.get('readingUnit')!='mm'):
            invalid('unit_or_interval_changed')
        items = data['readings'] if kind=='rain' else data['items']
        if not isinstance(items,list) or not items:
            invalid('empty_page')
        out, seen, updated = [], {}, {}
        for item in items:
            ts = timestamp(item['timestamp'])
            sgt = ts.astimezone(SGT)
            interval = 5 if kind=='rain' else 15
            if ts.second or ts.microsecond or sgt.minute % interval:
                invalid('unexpected_interval')
            if ts>fetched_at+timedelta(minutes=5):
                invalid('future_observation')
            if query_day is not None:
                if sgt.date()!=query_day:
                    invalid('outside_requested_sgt_day')
            elif fetched_at-ts>STALE[kind]:
                invalid('stale_snapshot')
            source_updated = timestamp(item['updatedTimestamp']) if 'updatedTimestamp' in item else None
            if source_updated and (source_updated<ts or source_updated>fetched_at+timedelta(minutes=5)):
                invalid('invalid_source_update_time')
            if kind=='psi' and item.get('date',str(sgt.date())) != str(sgt.date()):
                invalid('source_date_mismatch')
            pairs = [(r['stationId'],r['value']) for r in item['data']] if kind=='rain' else list(item['readings']['psi_twenty_four_hourly'].items())
            if not pairs:
                invalid('missing_metric')
            for name,value in pairs:
                station = name if kind=='rain' else 'REGION_'+name.upper()
                if station not in metadata:
                    invalid('unknown_station')
                value = numeric(value,0,500 if kind=='psi' else None)
                key=(station,iso(ts))
                if key in seen:
                    if seen[key] != value:
                        invalid('conflicting_values_in_page')
                    continue
                seen[key]=value
                updated[key]=iso(source_updated) if source_updated else None
                out.append(Reading(station,'rainfall_5min_mm' if kind=='rain' else 'psi_24hr',ts,value,'mm' if kind=='rain' else 'PSI',SOURCE))
        return Page(out,metadata,updated,token,(300 if kind=='rain' else 900))
    except InvalidPage:
        raise
    except (KeyError,TypeError,AttributeError,ValueError,OverflowError) as exc:
        raise InvalidPage('malformed_or_changed_schema') from exc


@dataclass(frozen=True)
class Response:
    status: int | None
    body: bytes = b''
    retry_after: str | None = None
    complete: bool = True
    error: str | None = None


class OfficialClient:
    """Fixed allowlisted hosts, bounded body/time; no redirects or URL-supplied secrets."""
    def get(self, kind, query_day, token):
        params = {}
        if query_day:
            params['date']=query_day
        if token:
            params['paginationToken']=token
        headers={'User-Agent':'DayCoverPlus/local-research-prototype'}
        if os.getenv('DATAGOV_API_KEY'):
            headers['x-api-key']=os.environ['DATAGOV_API_KEY']
        started=time.monotonic()
        try:
            with httpx.Client(timeout=15,follow_redirects=False) as client:
                with client.stream('GET',ENDPOINTS[kind],params=params,headers=headers) as response:
                    body=bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic()-started>30:
                            return Response(response.status_code,bytes(body),complete=False,error='transport_deadline')
                        body.extend(chunk[:MAX_BODY+1-len(body)])
                        if len(body)>MAX_BODY:
                            return Response(response.status_code,bytes(body),complete=False,error='body_too_large')
                    return Response(response.status_code,bytes(body),response.headers.get('Retry-After'))
        except httpx.TransportError:
            return Response(None,error='transport_unavailable')


class Ingestor:
    def __init__(self, repository=None, client=None, *, clock=utcnow, sleep=time.sleep, max_attempts=3):
        if not 1<=max_attempts<=5:
            raise ValueError('max_attempts must be 1–5')
        self.repo=repository or configured_repository()
        self.client=client or OfficialClient()
        self.clock,self.sleep,self.max_attempts=clock,sleep,max_attempts

    def start(self, kind, query_day=None):
        if kind not in ENDPOINTS:
            raise ValueError('Unknown weather kind')
        if query_day is not None:
            if type(query_day) is not date or query_day>self.clock().astimezone(SGT).date():
                raise ValueError('Use a nonfuture Singapore calendar date')
        rid='WEATHER-RUN-'+uuid.uuid4().hex
        stamp=iso(self.clock())
        with self.repo.transaction() as c:
            c.execute('INSERT INTO weather_runs (id,kind,query_day,status,next_token,pages,created_at,updated_at,error_code) VALUES (?,?,?,\'running\',NULL,0,?,?,NULL)',(rid,kind,str(query_day) if query_day else None,stamp,stamp))
        return rid

    def status(self, rid):
        with self.repo.transaction() as c:
            row=c.execute('SELECT * FROM weather_runs WHERE id=?',(rid,)).fetchone()
            if not row:
                raise LookupError('Unknown weather run')
            # Cursor remains private to the resumable runner, not printed in logs/status.
            result={k:v for k,v in row.items() if k!='next_token'}
            result['alerts']=[dict(r) for r in c.execute('SELECT code,details,recorded_at FROM weather_alerts WHERE run_id=? ORDER BY recorded_at,id',(rid,)).fetchall()]
            result['settlement_ready']=False
            return result

    def _gate(self):
        # Persistent shared throttle across workers, runs and both weather sources.
        while True:
            with self.repo.transaction() as c:
                suffix=' FOR UPDATE' if c.backend=='postgres' else ''
                row=c.execute('SELECT next_allowed FROM weather_transport_gate WHERE id=?'+suffix,('datagov_realtime',)).fetchone()
                wait=row['next_allowed']-self.clock().timestamp()
                if wait<=0:
                    c.execute('UPDATE weather_transport_gate SET next_allowed=? WHERE id=?',(self.clock().timestamp()+2,'datagov_realtime'))
                    return True
                if wait>30:
                    return False
            self.sleep(wait)

    def _defer(self, seconds):
        with self.repo.transaction() as c:
            c.execute('UPDATE weather_transport_gate SET next_allowed=CASE WHEN next_allowed>? THEN next_allowed ELSE ? END WHERE id=?',
                      (self.clock().timestamp()+seconds,self.clock().timestamp()+seconds,'datagov_realtime'))

    def _alert(self,c,rid,fid,code,details):
        c.execute('INSERT INTO weather_alerts VALUES (?,?,?,?,?,?)',(str(uuid.uuid4()),rid,fid,code,canonical_json(details),iso(self.clock())))

    def _fetch_row(self,c,run,response,outcome,error,stamp):
        fid='WEATHER-FETCH-'+uuid.uuid4().hex
        c.execute('INSERT INTO weather_fetches VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                  (fid,run['id'],ENDPOINTS[run['kind']],run['next_token'],iso(stamp),response.status,
                   base64.b64encode(response.body).decode(),hashlib.sha256(response.body).hexdigest(),int(response.complete),outcome,error,PARSER_VERSION))
        return fid

    def _failure(self,run,response,error,*,quarantine=False,stamp=None):
        with self.repo.transaction() as c:
            suffix=' FOR UPDATE' if c.backend=='postgres' else ''
            current=c.execute('SELECT * FROM weather_runs WHERE id=?'+suffix,(run['id'],)).fetchone()
            fid=self._fetch_row(c,run,response,'quarantined' if quarantine else 'transport_error',error,stamp or self.clock())
            self._alert(c,run['id'],fid,error,{'kind':run['kind'],'checkpoint_advanced':False})
            if current['pages']!=run['pages'] or current['next_token']!=run['next_token'] or current['status']=='complete':
                return
            c.execute('UPDATE weather_runs SET status=?,error_code=?,updated_at=? WHERE id=?',('quarantined' if quarantine else 'failed',error,iso(self.clock()),run['id']))

    def _retry_delay(self,response,attempt):
        delay=min(2**attempt,8)
        if response.retry_after:
            try:
                delay=max(delay,float(response.retry_after))
            except ValueError:
                try:
                    delay=max(delay,(parsedate_to_datetime(response.retry_after)-self.clock()).total_seconds())
                except (ValueError,TypeError,OverflowError):
                    pass
        if not math.isfinite(delay):
            delay=86400
        return min(max(delay,0),86400)

    def run(self,rid,*,max_pages=50):
        if not 1<=max_pages<=500:
            raise ValueError('max_pages must be 1–500 per invocation')
        for _ in range(max_pages):
            with self.repo.transaction() as c:
                run=c.execute('SELECT * FROM weather_runs WHERE id=?',(rid,)).fetchone()
                if not run:
                    raise LookupError('Unknown weather run')
            if run['status']=='complete':
                return self.status(rid)
            response=None
            for attempt in range(self.max_attempts):
                if not self._gate():
                    self._failure(run,Response(None),'rate_limit_deferred')
                    return self.status(rid)
                response=self.client.get(run['kind'],run['query_day'],run['next_token'])
                stamp=self.clock()
                if response.status==200 and response.complete and not response.error:
                    break
                code=response.error or ('http_'+str(response.status))
                self._failure(run,response,code,quarantine=not response.complete,stamp=stamp)
                retryable=response.status in (429,500,502,503,504) or response.status is None
                if not retryable or not response.complete:
                    return self.status(rid)
                delay=self._retry_delay(response,attempt)
                self._defer(delay)
                if delay>30 or attempt+1==self.max_attempts:
                    return self.status(rid)
                self.sleep(delay)
            try:
                page=parse_page(response.body,run['kind'],stamp,date.fromisoformat(run['query_day']) if run['query_day'] else None)
                with self.repo.transaction() as c:
                    suffix=' FOR UPDATE' if c.backend=='postgres' else ''
                    current=c.execute('SELECT * FROM weather_runs WHERE id=?'+suffix,(rid,)).fetchone()
                    if current['pages']!=run['pages'] or current['next_token']!=run['next_token'] or current['status']=='complete':
                        # Retain fetched bytes even when another worker won the checkpoint.
                        self._fetch_row(c,run,response,'superseded','checkpoint_already_advanced',stamp)
                        continue
                    if page.next_token and (page.next_token==run['next_token'] or c.execute("SELECT id FROM weather_fetches WHERE run_id=? AND request_token=? AND outcome='accepted'",(rid,page.next_token)).fetchone()):
                        invalid('pagination_cycle')
                    if c.backend=='postgres':
                        c.execute('SELECT pg_advisory_xact_lock(hashtext(?))',('weather-observations:'+run['kind'],))
                    fid=self._fetch_row(c,run,response,'accepted',None,stamp)
                    self._persist_page(c,run,fid,page,stamp)
                    c.execute('UPDATE weather_runs SET status=?,next_token=?,pages=pages+1,updated_at=?,error_code=NULL WHERE id=?',
                              ('running' if page.next_token else 'complete',page.next_token,iso(stamp),rid))
            except InvalidPage as exc:
                self._failure(run,response,str(exc),quarantine=True,stamp=stamp)
                return self.status(rid)
            if not page.next_token:
                return self.status(rid)
        with self.repo.transaction() as c:
            c.execute("UPDATE weather_runs SET status='paused',updated_at=? WHERE id=? AND status='running'",(iso(self.clock()),rid))
        return self.status(rid)

    def _persist_page(self,c,run,fid,page,stamp):
        counts=Counter(r.station for r in page.readings)
        first=min(r.observed_at for r in page.readings)
        # Metadata may describe the current station even in a historical response.
        # First seen means fetch time, never a claimed historical relocation date.
        versions={}
        known={r['station'] for r in c.execute('SELECT DISTINCT station FROM weather_station_versions WHERE source=? AND station LIKE ?', (SOURCE,'S%' if run['kind']=='rain' else 'REGION_%')).fetchall()}
        absent=known-set(page.metadata)
        if absent:
            self._alert(c,run['id'],fid,'stations_absent_metadata',{'stations':sorted(absent),'not_proof_of_decommission':True})
        for station,metadata in page.metadata.items():
            encoded=canonical_json(metadata);digest=hashlib.sha256(encoded.encode()).hexdigest()
            version=entity_id('STATION',SOURCE+'|'+station+'|'+digest);versions[station]=version
            old=c.execute('SELECT id FROM weather_station_versions WHERE source=? AND station=?',(SOURCE,station)).fetchall()
            c.execute('INSERT INTO weather_station_versions VALUES (?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',(version,SOURCE,station,encoded,digest,iso(stamp),iso(stamp),fid))
            if old and any(r['id']!=version for r in old):
                self._alert(c,run['id'],fid,'station_metadata_changed',{'station':station,'review_required':True,'metadata_seen_at':iso(stamp),'page_observation_from':iso(first),'official_effective_date_known':False})
            c.execute('INSERT INTO weather_station_presence VALUES (?,?,?)',(fid,version,counts[station]))
        missing=[s for s in page.metadata if not counts[s]]
        if missing:
            self._alert(c,run['id'],fid,'stations_without_readings',{'stations':sorted(missing),'not_proof_of_decommission':True})
        for r in page.readings:
            observed=iso(r.observed_at)
            # Metadata is part of identity; relocation cannot silently reuse a reading.
            digest=hashlib.sha256(canonical_json({'value':r.value,'unit':r.unit,'station_version':versions[r.station]}).encode()).hexdigest()
            oid=entity_id('OBSERVATION','|'.join((SOURCE,r.station,r.metric,observed,digest)))
            old=c.execute('SELECT id FROM pilot_observations WHERE source=? AND station=? AND metric=? AND observed_at=?',(SOURCE,r.station,r.metric,observed)).fetchall()
            classification='equal_duplicate' if oid in {row['id'] for row in old} else 'conflicting_revision' if old else 'late' if stamp-r.observed_at>STALE[run['kind']] else 'new'
            quality='conflict_review' if classification=='conflicting_revision' else 'validated_provisional'
            c.execute('INSERT INTO pilot_observations VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',(oid,SOURCE,r.station,r.metric,r.unit,r.value,observed,quality,digest))
            c.execute('INSERT INTO weather_observation_provenance VALUES (?,?,?,?,?)',(fid,oid,versions[r.station],page.updated[(r.station,observed)],classification))
            if classification=='conflicting_revision':
                self._alert(c,run['id'],fid,'observation_conflict',{'station':r.station,'observed_at':observed,'automatic_selection':False})


def source_health(repository=None,now=None):
    """Fresh fetch + fresh measurement are both necessary. Backfill is never live health."""
    now=now or utcnow();repo=repository or configured_repository();results={}
    with repo.transaction() as c:
        for kind in ENDPOINTS:
            latest=c.execute('SELECT * FROM weather_runs WHERE kind=? AND query_day IS NULL ORDER BY updated_at DESC,sequence DESC LIMIT 1',(kind,)).fetchone()
            row=c.execute('''SELECT MAX(f.fetched_at) AS fetched,MAX(o.observed_at) AS observed FROM weather_fetches f
                             JOIN weather_runs r ON r.id=f.run_id JOIN weather_observation_provenance p ON p.fetch_id=f.id
                             JOIN pilot_observations o ON o.id=p.observation_id
                             WHERE r.kind=? AND r.query_day IS NULL AND f.outcome='accepted' ''',(kind,)).fetchone()
            fresh=bool(row['fetched'] and row['observed'] and now-timestamp(row['fetched'])<=STALE[kind] and now-timestamp(row['observed'])<=STALE[kind])
            reviews=c.execute("SELECT COUNT(*) AS n FROM weather_alerts a JOIN weather_runs r ON r.id=a.run_id WHERE r.kind=? AND a.code IN ('observation_conflict','station_metadata_changed')",(kind,)).fetchone()['n']
            degraded=bool(reviews) or bool(latest and (latest['status']!='complete' or c.execute('SELECT id FROM weather_alerts WHERE run_id=?',(latest['id'],)).fetchone()))
            results[kind]={'status':'missing' if not row['fetched'] else 'stale' if not fresh else 'degraded' if degraded else 'available_provisional',
                           'last_fetch_at':row['fetched'],'latest_observed_at':row['observed'],'latest_run_status':latest['status'] if latest else None,'unresolved_review_alerts':reviews,'settlement_ready':False}
    return results
