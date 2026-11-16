"""Versioned Singapore-day evidence. Local finality is reviewed, never a payout.

Rain end labelling is a candidate convention: official verification is still absent.
No operator/environment option can silently lift that source-method gate.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import uuid

from .contracts import canonical_json, simulation_contract, validate_snapshot
from . import data
from .ingestion import SGT, REGIONS
from .ledger_repository import configured_repository, entity_id
from .weather_ingestion import SOURCE, iso, timestamp, utcnow

METHOD_VERSION='sgt-daily-v1-2026.11'
RAIN_TIMING_VERIFIED=False
PSI_REFERENCE='https://www.nea.gov.sg/our-services/pollution-control/air-and-coastal-water-quality-monitoring'


def digest(value):return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _day(value):
    if type(value) is not date or value in (date.min,date.max):raise ValueError('Use a Singapore calendar date.')
    return value


def _kind(kind,station):
    if kind not in ('rain','psi') or not isinstance(station,str):raise ValueError('Unknown metric/station.')
    if kind=='rain' and not re.fullmatch(r'S\d{2,4}',station):raise ValueError('Invalid gauge ID.')
    if kind=='psi' and station not in {'REGION_'+r.upper() for r in REGIONS}:raise ValueError('Invalid PSI region.')
    return 'rainfall_5min_mm' if kind=='rain' else 'psi_24hr'


def _lock(c,key):
    if c.backend=='postgres':c.execute('SELECT pg_advisory_xact_lock(hashtext(?))',(key,))


def _reviewer(c,actor):
    p=c.execute('SELECT role,active FROM auth_principals WHERE id=?',(actor,)).fetchone()
    if not p or p['role']!='reviewer' or not p['active']:raise ValueError('Active locally provisioned reviewer required.')


def _reference(value):
    if not isinstance(value,str) or not 3<=len(value.strip())<=512 or '\n' in value:raise ValueError('A bounded source/evidence reference is required.')


def _mapping(c,station,day):
    return c.execute('''SELECT r.*,v.metadata FROM weather_mapping_reviews r JOIN weather_station_versions v ON v.id=r.station_version_id
                        WHERE v.source=? AND v.station=? AND r.valid_from<=? AND r.valid_until>=? ORDER BY r.sequence DESC LIMIT 1''',
                     (SOURCE,station,str(day),str(day))).fetchone()


def review_mapping(station_version_id,start,end,decision,actor,source_ref,repository=None):
    _day(start);_day(end);_reference(source_ref)
    if end<start or decision not in ('approved','revoked'):raise ValueError('Invalid mapping review.')
    with (repository or configured_repository()).transaction() as c:
        _reviewer(c,actor)
        version=c.execute('SELECT * FROM weather_station_versions WHERE id=?',(station_version_id,)).fetchone()
        if not version:raise LookupError('Unknown station version.')
        _lock(c,'weather-observations:'+('rain' if version['station'].startswith('S') else 'psi'))
        rid='MAPPING-REVIEW-'+uuid.uuid4().hex
        c.execute('''INSERT INTO weather_mapping_reviews (id,station_version_id,valid_from,valid_until,decision,reviewer_id,source_ref,recorded_at)
                     VALUES (?,?,?,?,?,?,?,?)''',(rid,station_version_id,str(start),str(end),decision,actor,source_ref,iso(utcnow())))
        return {'review_id':rid,'station':version['station'],'valid_from':str(start),'valid_until':str(end),'decision':decision,'authority':'local_evidence_review'}


def review_revision(observation_id,actor,source_ref,repository=None,*,reject=False):
    _reference(source_ref)
    with (repository or configured_repository()).transaction() as c:
        _reviewer(c,actor)
        row=c.execute('SELECT * FROM pilot_observations WHERE id=?',(observation_id,)).fetchone()
        if not row or row['source']!=SOURCE:raise LookupError('Unknown canonical weather observation.')
        _lock(c,'weather-observations:'+('rain' if row['metric']=='rainfall_5min_mm' else 'psi'))
        ids=sorted(r['id'] for r in c.execute('SELECT id FROM pilot_observations WHERE source=? AND station=? AND metric=? AND observed_at=?',
                      (SOURCE,row['station'],row['metric'],row['observed_at'])).fetchall())
        rid='REVISION-REVIEW-'+uuid.uuid4().hex
        c.execute('''INSERT INTO weather_revision_reviews (id,source,station,metric,observed_at,revision_set_sha256,selected_observation_id,reviewer_id,source_ref,recorded_at)
                     VALUES (?,?,?,?,?,?,?,?,?,?)''',(rid,SOURCE,row['station'],row['metric'],iso(timestamp(row['observed_at'])),digest(ids),None if reject else observation_id,actor,source_ref,iso(utcnow())))
        return {'review_id':rid,'revision_set_sha256':digest(ids),'selected_observation_id':None if reject else observation_id}


def expected_times(day,kind):
    _day(day)
    start=datetime.combine(day,datetime.min.time(),SGT)
    return [iso(start+timedelta(minutes=5*i)) for i in range(1,289)] if kind=='rain' else [iso(start+timedelta(hours=i)) for i in range(24)]


def _candidate(c,kind,station,day,now):
    metric=_kind(kind,station);expected=expected_times(day,kind)
    _lock(c,'weather-observations:'+kind)
    raw=c.execute('''SELECT * FROM pilot_observations WHERE source=? AND station=? AND metric=? AND observed_at>=? AND observed_at<=?''',
                  (SOURCE,station,metric,expected[0],expected[-1])).fetchall()
    buckets=defaultdict(list)
    for r in raw:
        key=iso(timestamp(r['observed_at']))
        if key in expected:buckets[key].append(r)
    mapping=_mapping(c,station,day)
    reasons=[];selected=[];all_ids=[];proofs=[];resolutions=[];missing=[];conflicts=[]
    if not mapping or mapping['decision']!='approved':reasons.append('station_mapping_not_reviewed')
    for at in expected:
        variants=sorted(buckets.get(at,[]),key=lambda r:r['id'])
        all_ids.extend(r['id'] for r in variants)
        if not variants:
            missing.append(at);continue
        chosen=variants[0]
        review=c.execute('''SELECT * FROM weather_revision_reviews WHERE source=? AND station=? AND metric=? AND observed_at=? ORDER BY sequence DESC LIMIT 1''',
                         (SOURCE,station,metric,at)).fetchone()
        if review:
            if review['revision_set_sha256']!=digest([r['id'] for r in variants]):
                conflicts.append(at);continue
            resolutions.append(review['id'])
            if review['selected_observation_id'] is None:
                reasons.append('rejected_observation');continue
            chosen=next(r for r in variants if r['id']==review['selected_observation_id'])
        elif len(variants)>1:
            conflicts.append(at);continue
        evidence=c.execute('''SELECT p.*,f.fetched_at,r.status AS run_status FROM weather_observation_provenance p
                           JOIN weather_fetches f ON f.id=p.fetch_id JOIN weather_runs r ON r.id=f.run_id
                           WHERE p.observation_id=? AND f.outcome='accepted' AND f.body_complete=1 ORDER BY f.fetched_at,p.fetch_id''',(chosen['id'],)).fetchall()
        # Prefer a completed acquisition; equal late duplicates cannot invalidate a final day.
        proof=next((p for p in evidence if p['run_status']=='complete'),None)
        if proof is None:
            reasons.append('acquisition_not_complete')
            proof=evidence[0] if evidence else None
        if proof is None:
            reasons.append('raw_provenance_missing')
        else:
            proofs.append({'observation_id':chosen['id'],'fetch_id':proof['fetch_id'],'station_version_id':proof['station_version_id'],'run_status':proof['run_status']})
            if not mapping or proof['station_version_id']!=mapping['station_version_id']:reasons.append('station_mapping_mismatch')
        if chosen['unit']!=('mm' if kind=='rain' else 'PSI'):
            reasons.append('unit_mismatch');continue
        if chosen['quality'] not in ('validated_provisional','conflict_review'):
            reasons.append('unaccepted_quality');continue
        try:value=Decimal(str(chosen['value']))
        except InvalidOperation:
            reasons.append('invalid_value');continue
        if not value.is_finite() or value<0 or (kind=='psi' and value>500):
            reasons.append('invalid_value');continue
        selected.append({'id':chosen['id'],'value':str(value),'observed_at':at})
    if missing:reasons.append('missing_bins')
    if conflicts:reasons.append('unresolved_revisions')
    end=datetime.combine(day+timedelta(days=1),datetime.min.time(),SGT)
    if now<end:reasons.append('day_not_finished')
    if kind=='rain' and not RAIN_TIMING_VERIFIED:reasons.append('rain_interval_label_unverified')
    complete=len(selected)==len(expected) and not missing and not conflicts and 'rejected_observation' not in reasons
    value=float(sum((Decimal(r['value']) for r in selected),Decimal(0))) if kind=='rain' and complete else float(max(Decimal(r['value']) for r in selected)) if complete else None
    payload={'kind':kind,'station':station,'day':str(day),'timezone':'Asia/Singapore','method_version':METHOD_VERSION,
             'window':'(00:00,next_00:00]' if kind=='rain' else '[00:00,23:00]_top_of_hour_only',
             'source_timing_verified':RAIN_TIMING_VERIFIED if kind=='rain' else True,
             'source_reference':None if kind=='rain' else PSI_REFERENCE,
             'expected_bins':len(expected),'observed_bins':len(buckets),'usable_bins':len(selected),'missing_bins':missing,'conflicting_bins':conflicts,
             'completeness':'complete' if complete else 'incomplete','candidate_value':value,'unit':'mm/day' if kind=='rain' else 'PSI',
             'blocking_reasons':sorted(set(reasons)),'input_observation_ids':sorted(all_ids),'selected_observation_ids':[r['id'] for r in selected],
             'raw_proofs':proofs,'revision_review_ids':sorted(resolutions),'mapping_review_id':mapping['id'] if mapping else None,
             'station_version_id':mapping['station_version_id'] if mapping and mapping['decision']=='approved' else None,
             'settlement_ready':False}
    fingerprint=digest(payload)
    return payload,fingerprint


def _save(c,payload,fingerprint,status,aggregate_id,now):
    c.execute('''INSERT INTO pilot_daily_aggregates (id,source,station,metric,unit,day,timezone,value,observed_bins,expected_bins,status,version)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING''',
              (aggregate_id,SOURCE,payload['station'],'rain_daily_mm' if payload['kind']=='rain' else 'psi_daily_max_hourly_24hr',payload['unit'],payload['day'],'Asia/Singapore',
               payload['candidate_value'],payload['observed_bins'],payload['expected_bins'],status,METHOD_VERSION+':'+fingerprint))
    for oid in payload['input_observation_ids']:
        c.execute('INSERT INTO pilot_aggregate_inputs VALUES (?,?) ON CONFLICT DO NOTHING',(aggregate_id,oid))


def build_daily(kind,station,day,repository=None,*,now=None):
    now=now or utcnow();iso(now)
    with (repository or configured_repository()).transaction() as c:
        payload,fingerprint=_candidate(c,kind,station,day,now)
        existing=c.execute('SELECT aggregate_id FROM weather_daily_details WHERE kind=? AND station=? AND day=? AND fingerprint=?',(kind,station,str(day),fingerprint)).fetchone()
        if existing:return _current(c,kind,station,day,now)
        previous=c.execute('SELECT aggregate_id FROM weather_daily_details WHERE kind=? AND station=? AND day=? ORDER BY sequence DESC LIMIT 1',(kind,station,str(day))).fetchone()
        aid=entity_id('DAILY',kind+'|'+station+'|'+str(day)+'|'+fingerprint)
        payload['aggregate_id']=aid;payload['fingerprint']=fingerprint;payload['supersedes_id']=previous['aggregate_id'] if previous else None
        payload['status']='pending' if payload['blocking_reasons'] else 'corrected' if previous else 'complete'
        _save(c,payload,fingerprint,'corrected' if previous and not payload['blocking_reasons'] else 'pending',aid,now)
        c.execute('INSERT INTO weather_daily_details (aggregate_id,kind,station,day,fingerprint,payload,recorded_at) VALUES (?,?,?,?,?,?,?)',(aid,kind,station,str(day),fingerprint,canonical_json(payload),iso(now)))
        return _current(c,kind,station,day,now)


def _current(c,kind,station,day,now):
    payload,fingerprint=_candidate(c,kind,station,day,now)
    stored=c.execute('SELECT * FROM weather_daily_details WHERE kind=? AND station=? AND day=? AND fingerprint=?',(kind,station,str(day),fingerprint)).fetchone()
    if not stored:
        return {**payload,'status':'pending','aggregate_id':None,'fingerprint':fingerprint,'blocking_reasons':sorted(set(payload['blocking_reasons']+['current_inputs_not_built'])),
                'usable_value':None,'eligible_for_phase6':False}
    payload=json.loads(stored['payload'])
    review=c.execute('SELECT * FROM weather_daily_reviews WHERE aggregate_id=? ORDER BY sequence DESC LIMIT 1',(stored['aggregate_id'],)).fetchone()
    if review:
        payload['status']=review['decision'];payload['candidate_aggregate_id']=payload['aggregate_id'];payload['aggregate_id']=review['result_aggregate_id'];payload['final_review_id']=review['id']
    payload['usable_value']=payload['candidate_value'] if payload['status']=='final' else None
    payload['eligible_for_phase6']=payload['status']=='final'
    return payload


def current_daily(kind,station,day,repository=None,*,now=None):
    with (repository or configured_repository()).transaction() as c:return _current(c,kind,station,day,now or utcnow())


def review_daily(aggregate_id,decision,actor,source_ref,repository=None,*,now=None):
    now=now or utcnow();_reference(source_ref)
    if decision not in ('final','rejected'):raise ValueError('Invalid aggregate review.')
    with (repository or configured_repository()).transaction() as c:
        _reviewer(c,actor)
        stored=c.execute('SELECT * FROM weather_daily_details WHERE aggregate_id=?',(aggregate_id,)).fetchone()
        if not stored:raise LookupError('Unknown daily candidate.')
        payload,fingerprint=_candidate(c,stored['kind'],stored['station'],date.fromisoformat(stored['day']),now)
        if fingerprint!=stored['fingerprint']:raise ValueError('Evidence changed; rebuild and review the current candidate.')
        if decision=='final' and payload['blocking_reasons']:raise ValueError('Finality gates remain: '+','.join(payload['blocking_reasons']))
        rid='DAILY-REVIEW-'+uuid.uuid4().hex
        result_id=entity_id('DAILY-REVIEW',aggregate_id+'|'+rid)
        _save(c,payload,fingerprint+':'+rid,decision,result_id,now)
        c.execute('''INSERT INTO weather_daily_reviews (id,aggregate_id,result_aggregate_id,decision,reviewer_id,source_ref,recorded_at) VALUES (?,?,?,?,?,?,?)''',
                  (rid,aggregate_id,result_id,decision,actor,source_ref,iso(now)))
        return _current(c,stored['kind'],stored['station'],date.fromisoformat(stored['day']),now)


def propose_closure(centre,day,closed,reason,source_ref,source_document_sha256,repository=None):
    _day(day);_reference(source_ref)
    if type(closed) is not bool or reason not in ('cleaning','works','explicit_open') or (not closed and reason!='explicit_open') or (closed and reason=='explicit_open'):
        raise ValueError('Closure fact/reason mismatch.')
    if not isinstance(source_document_sha256,str) or not re.fullmatch(r'[a-f0-9]{64}',source_document_sha256):raise ValueError('Source document checksum required.')
    with (repository or configured_repository()).transaction() as c:
        if not c.execute('SELECT id FROM pilot_centres WHERE id=?',(centre,)).fetchone():raise LookupError('Unknown canonical centre.')
        _lock(c,'closure:'+centre+'|'+str(day))
        facts={'centre_id':centre,'day':str(day),'closed':closed,'reason':reason,'source_ref':source_ref,'source_document_sha256':source_document_sha256}
        old=c.execute('SELECT * FROM weather_closure_versions WHERE centre_id=? AND day=? ORDER BY sequence DESC LIMIT 1',(centre,str(day))).fetchone()
        if old and json.loads(old['payload'])==facts:return {'closure_id':old['id'],'duplicate':True}
        sha=digest({'facts':facts,'supersedes_id':old['id'] if old else None});cid=entity_id('CLOSURE',sha)
        c.execute('''INSERT INTO weather_closure_versions (id,centre_id,day,payload,closed,source_ref,source_sha256,supersedes_id,recorded_at)
                     VALUES (?,?,?,?,?,?,?,?,?)''',(cid,centre,str(day),canonical_json(facts),int(closed),source_ref,sha,old['id'] if old else None,iso(utcnow())))
        return {'closure_id':cid,'duplicate':False,'review_required':True}


def review_closure(closure_id,decision,actor,source_ref,repository=None):
    _reference(source_ref)
    if decision not in ('approved','rejected'):raise ValueError('Invalid closure review.')
    with (repository or configured_repository()).transaction() as c:
        _reviewer(c,actor)
        row=c.execute('SELECT * FROM weather_closure_versions WHERE id=?',(closure_id,)).fetchone()
        if not row:raise LookupError('Unknown closure version.')
        _lock(c,'closure:'+row['centre_id']+'|'+row['day'])
        latest=c.execute('SELECT id FROM weather_closure_versions WHERE centre_id=? AND day=? ORDER BY sequence DESC LIMIT 1',(row['centre_id'],row['day'])).fetchone()
        if latest['id']!=closure_id:raise ValueError('Review the latest closure correction.')
        rid='CLOSURE-REVIEW-'+uuid.uuid4().hex
        c.execute('''INSERT INTO weather_closure_reviews (id,closure_id,decision,reviewer_id,source_ref,recorded_at) VALUES (?,?,?,?,?,?)''',(rid,closure_id,decision,actor,source_ref,iso(utcnow())))
        return {'closure_id':closure_id,'review_id':rid,'decision':decision,'financial_effect':False}


def _closure(c,centre,day):
    _lock(c,'closure:'+centre+'|'+str(day))
    row=c.execute('SELECT * FROM weather_closure_versions WHERE centre_id=? AND day=? ORDER BY sequence DESC LIMIT 1',(centre,str(day))).fetchone()
    review=c.execute('SELECT * FROM weather_closure_reviews WHERE closure_id=? ORDER BY sequence DESC LIMIT 1',(row['id'],)).fetchone() if row else None
    approved=bool(review and review['decision']=='approved')
    return {'status':'approved' if approved else 'pending','closed':bool(row['closed']) if approved else None,
            'closure_id':row['id'] if row else None,'review_id':review['id'] if review else None,
            'source_ref':row['source_ref'] if row else None,'supersedes_id':row['supersedes_id'] if row else None}


def select_evidence(stall,day,repository=None,*,now=None,persist=True):
    with (repository or configured_repository()).transaction() as c:
        context=None
        if c.execute('SELECT version FROM pilot_schema_migrations WHERE version=5').fetchone():
            from .policy_lifecycle import term_context
            context=term_context(c,stall,day)
        return select_in_unit(c,stall,day,now=now,persist=persist,policy_context=context)


def select_in_unit(c,stall,day,*,now=None,persist=True,policy_context=None):
    _day(day);now=now or utcnow();iso(now)
    p=policy_context or c.lock_policy(stall);contract=json.loads(p['contract']);entry=validate_snapshot(contract)
    if entry.version!=p['version_id'] or entry.sha256!=p['contract_sha256']:raise ValueError('Accepted contract metadata differs.')
    if not p['start']<=str(day)<=p['end']:raise ValueError('Evidence date is outside the accepted term.')
    # Hold ingestion locks consistently while deriving a single reproducible read snapshot.
    _lock(c,'weather-observations:rain');_lock(c,'weather-observations:psi')
    closure=_closure(c,p['centre_id'],day)
    location=c.execute('SELECT latitude,longitude FROM auth_onboarding WHERE stall_id=?',(stall,)).fetchone()
    if location:coordinates=(location['latitude'],location['longitude'])
    else:
        reference=c.execute('SELECT external_ref FROM pilot_centres WHERE id=?',(p['centre_id'],)).fetchone()['external_ref']
        centre=next((s for s in data.load_stalls() if s.id==reference),None)
        coordinates=(centre.lat,centre.lon) if centre else None
    assigned=contract['assigned_gauge'];primary=_current(c,'rain',assigned,day,now)
    selected=primary if primary['eligible_for_phase6'] else None;distance=None;considered=[]
    if selected:
        mapping=_mapping(c,assigned,day)
        if mapping and coordinates:
            meta=json.loads(mapping['metadata']);distance=data.km(coordinates,(meta['latitude'],meta['longitude']))
    if not selected and coordinates:
        stations=sorted({r['station'] for r in c.execute("SELECT DISTINCT station FROM weather_station_versions WHERE source=? AND station LIKE ?",(SOURCE,'S%')).fetchall()}-{assigned})
        candidates=[]
        for station in stations:
            mapping=_mapping(c,station,day)
            if not mapping or mapping['decision']!='approved':continue
            meta=json.loads(mapping['metadata']);km=data.km(coordinates,(meta['latitude'],meta['longitude']))
            if km<=contract['rules']['gauge_fallback_km']:
                aggregate=_current(c,'rain',station,day,now)
                considered.append({'station':station,'distance_km':km,'aggregate_id':aggregate['aggregate_id'],'status':aggregate['status']})
                if aggregate['eligible_for_phase6']:candidates.append((km,station,aggregate))
        if candidates:
            distance,_,selected=min(candidates,key=lambda item:(item[0],item[1]))
    region='REGION_'+contract['psi_region'].upper()
    psi=_current(c,'psi',region,day,now);yesterday=_current(c,'psi',region,day-timedelta(days=1),now)
    reason='assigned_gauge' if selected and selected['station']==assigned else 'approved_nearest_valid_within_5km' if selected else 'no_approved_valid_gauge_within_5km'
    report={'policy_id':p['id'],'stall_id':stall,'day':str(day),'contract_version':p['version_id'],'contract_sha256':p['contract_sha256'],
            'assigned_gauge':assigned,'selected_gauge':selected['station'] if selected else None,'distance_km':distance,'selection_reason':reason,
            'tie_break':'exact_distance_km_then_station_id','primary_status':primary['status'],'primary_blocking_reasons':primary['blocking_reasons'],
            'fallback_candidates':sorted(considered,key=lambda r:(r['distance_km'],r['station'])),
            'rain':selected or primary,'psi_today':psi,'psi_yesterday':yesterday,'closure':closure,
            'rain_input_ready':bool(selected and closure['status']=='approved'),
            'haze_today_ready':bool(psi['eligible_for_phase6'] and closure['status']=='approved'),
            'haze_consecutive_ready':bool(psi['eligible_for_phase6'] and yesterday['eligible_for_phase6'] and closure['status']=='approved'),
            'settlement_ready':False,'financial_effect':False}
    fingerprint=digest(report);sid=entity_id('EVIDENCE-SELECTION',p['id']+'|'+str(day)+'|'+fingerprint)
    if persist:c.execute('INSERT INTO weather_evidence_selections VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING',(sid,p['id'],str(day),fingerprint,canonical_json(report),iso(now)))
    return {**report,'selection_id':sid,'fingerprint':fingerprint,'persisted':persist}
