"""Deterministic reviewed-evidence entitlements. No payment instructions/execution.

Cap reservations are monotonic. Reviewed downward corrections change net entitlement,
never release spent cap or recall money. The separate settlement coordinator owns any mock execution/reconciliation.
"""
from datetime import date, timedelta
import json

from . import daily_evidence, policy_lifecycle as life
from .contracts import canonical_json, simulation_contract
from .ledger_repository import configured_repository, cents, sgd, entity_id
from .pilot import decide
from .ingestion import SGT
from .weather_ingestion import utcnow, iso

ZERO={'rain':0,'haze_days':0,'haze_sgd':0,'total':0}


def _dates(start,end,limit=366):
    if type(start) is not date or type(end) is not date or end<start or (end-start).days>=limit:raise ValueError('Invalid bounded date range.')
    return [start+timedelta(days=i) for i in range((end-start).days+1)]


def _event_total(c,table,p,day,peril):
    return sum(r['amount_cents'] for r in c.execute('SELECT amount_cents FROM '+table+' WHERE period_id=? AND day=? AND peril=?',(p['period_id'],str(day),peril)).fetchall())


def _latest(c,p,day,peril,effect=None):
    query='SELECT * FROM engine_decisions WHERE term_id=? AND day=? AND peril=?'
    params=(p['term_id'],str(day),peril)
    if effect:query+=' AND effect=?';params+=(effect,)
    return c.execute(query+' ORDER BY sequence DESC LIMIT 1',params).fetchone()


def _context(c,p,day,now):
    selection=daily_evidence.select_in_unit(c,p['stall_id'],day,now=now,persist=True,policy_context=p)
    state=life.state(c,p,day)
    key=daily_evidence.digest({'term':p['term_id'],'period':p['period_id'],'contract':p['contract_sha256'],'selection':selection['fingerprint'],'lifecycle_state':state})
    evidence={'source':'reviewed_nea_daily_simulation','selection_id':selection['selection_id'],'selection_sha256':selection['fingerprint'],
              'rain_mm':selection['rain']['usable_value'],'psi_today':selection['psi_today']['usable_value'],'psi_yesterday':selection['psi_yesterday']['usable_value'],
              'rain_aggregate_id':selection['rain']['aggregate_id'],'psi_aggregate_id':selection['psi_today']['aggregate_id'],'previous_psi_aggregate_id':selection['psi_yesterday']['aggregate_id'],
              'assigned_gauge':selection['assigned_gauge'],'selected_gauge':selection['selected_gauge'],'distance_km':selection['distance_km'],'selection_reason':selection['selection_reason'],
              'closure':selection['closure'],'rain_input_ready':selection['rain_input_ready'],'haze_today_ready':selection['haze_today_ready'],
              'haze_consecutive_ready':selection['haze_consecutive_ready'],'rain_blocking_reasons':selection['rain']['blocking_reasons']}
    return key,state,evidence


def _assessment(p,peril,state,evidence,used):
    if state!='ACTIVE_SIMULATION':return 'INACTIVE',0,'Simulation term is not active for the covered event date: '+state
    if evidence['closure']['status']!='approved':return 'PENDING',0,'Reviewed closure/open-day evidence is missing; no denial or invented open day.'
    if evidence['closure']['closed']:return decide(peril,None,None,None,True,used,version=p['version_id'])
    rain=evidence['rain_mm'] if evidence['rain_input_ready'] else None
    psi=evidence['psi_today'] if evidence['haze_today_ready'] else None
    yesterday=evidence['psi_yesterday'] if evidence['haze_consecutive_ready'] else None
    return decide(peril,rain,psi,yesterday,False,used,version=p['version_id'])


def _record(c,p,day,peril,key,effect,status,target,reason,evidence,now,*,commit=False,review_key=None):
    record_key=key+'|replay|'+review_key if review_key else key
    previous=c.execute('SELECT payload FROM engine_decisions WHERE term_id=? AND day=? AND peril=? AND context_sha256=? AND effect=?',
                       (p['term_id'],str(day),peril,record_key,effect)).fetchone()
    if previous:return {**json.loads(previous['payload']),'duplicate':True}
    current=_event_total(c,'engine_entitlement_entries',p,day,peril)
    consumed=_event_total(c,'engine_cap_entries',p,day,peril)
    reserve=0;delta=0
    if commit and status!='PENDING':
        desired=cents(target)
        used=c.used(p['period_id']);rules=simulation_contract(p['version_id']).terms
        reserve=max(0,desired-consumed)
        room=max(0,cents(rules['combined_cap_sgd'])-cents(used['total']))
        if peril=='rain':
            if not consumed and used['rain']>=rules['rules']['rain_cap_days_per_year']:room=0
        else:
            room=min(room,max(0,cents(rules['rules']['haze_cap_amount_per_year'])-cents(used['haze_sgd'])))
            if not consumed and used['haze_days']>=rules['rules']['haze_cap_days_per_year']:room=0
        reserve=min(reserve,room)
        allowed=min(desired,consumed+reserve)
        if desired>allowed:reason+=' Previously consumed cap is never restored or reassigned; reviewed target limited to remaining capacity.'
        target=sgd(allowed);delta=allowed-current
        if desired>0 and allowed==0:status='CAPPED'
    elif commit:
        target=sgd(current);effect='review_pending' if current else effect
        reason+=' Prior entitlement retained while corrected evidence is pending.'
    did=entity_id('ENGINE-DECISION','|'.join((p['term_id'],str(day),peril,record_key,effect)))
    payload={'decision_id':did,'policy_id':p['id'],'term_id':p['term_id'],'period_id':p['period_id'],'day':str(day),'peril':peril,
             'context_sha256':key,'contract_version':p['version_id'],'contract_sha256':p['contract_sha256'],'status':status,'effect':effect,
             'target_entitlement_sgd':target,'entitlement_delta_cents':delta,'cap_reserved_delta_cents':reserve,'reason':reason,'evidence':evidence,
             'mode':'reviewed_evidence_simulation','real_policy_issued':False,'disbursed':False,'settlement_ready':False,'payment_instruction_created':False,
             'timestamp':iso(now),'duplicate':False}
    c.execute('''INSERT INTO engine_decisions (id,policy_id,term_id,period_id,day,peril,context_sha256,effect,payload,recorded_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?)''',(did,p['id'],p['term_id'],p['period_id'],str(day),peril,record_key,effect,canonical_json(payload),iso(now)))
    if reserve:
        c.execute('INSERT INTO engine_cap_entries VALUES (?,?,?,?,?,?,?,?,?,?)',(entity_id('CAP',did),p['id'],p['period_id'],did,str(day),peril,reserve,'SGD','cap:'+did,iso(now)))
    if delta:
        c.execute('INSERT INTO engine_entitlement_entries VALUES (?,?,?,?,?,?,?,?,?,?)',(entity_id('ENTITLEMENT',did),p['id'],p['period_id'],did,str(day),peril,delta,'SGD','entitlement:'+did,iso(now)))
    if commit and (target>0 or delta) and c.execute('SELECT version FROM pilot_schema_migrations WHERE version=7').fetchone():
        from .settlement import record_outbox
        record_outbox(c,p,payload,now)
    c.audit(p['id'],'reviewed_evidence_'+effect,{'decision_id':did,'term_id':p['term_id'],'entitlement_delta_cents':delta,'cap_delta_cents':reserve},iso(now))
    return payload


def evaluate(stall,start,end,repository=None,*,now=None):
    now=now or utcnow();days=_dates(start,end,31)
    if end>now.astimezone(SGT).date():raise ValueError('Future covered weather dates cannot be evaluated.')
    repo=repository or configured_repository()
    with repo.transaction() as c:
        p=life.term_context(c,stall,start)
        if str(end)>p['end']:raise ValueError('A processing slice cannot cross an unaccepted or different term.')
        life.ensure_mode(c,p,'reviewed_evidence')
        results=[]
        for day in days:
            key,state,evidence=_context(c,p,day,now)
            for peril in ('rain','haze'):
                latest=_latest(c,p,day,peril)
                if latest and json.loads(latest['payload'])['context_sha256']==key:
                    results.append({**json.loads(latest['payload']),'duplicate':True});continue
                accepted=_latest(c,p,day,peril,'accepted')
                later=c.execute("SELECT id FROM engine_decisions WHERE period_id=? AND day>? AND effect='accepted'",(p['period_id'],str(day))).fetchone()
                requires_review=bool(later or (accepted and json.loads(accepted['payload'])['status']!='PENDING'))
                status,amount,reason=_assessment(p,peril,state,evidence,ZERO if requires_review else c.used(p['period_id']))
                if requires_review:
                    results.append(_record(c,p,day,peril,key,'review_required',status,amount,'Ordered replay/review required. '+reason,evidence,now))
                else:
                    results.append(_record(c,p,day,peril,key,'accepted',status,amount,reason,evidence,now,commit=True))
        return {'policy_id':p['id'],'term_id':p['term_id'],'decisions':results,'used':c.used(p['period_id']),
                'net_entitlement_cents':sum(r['amount_cents'] for r in c.execute('SELECT amount_cents FROM engine_entitlement_entries WHERE period_id=?',(p['period_id'],)).fetchall()),
                'payment_execution':'NOT_SUBMITTED','real_settlement_supported':False}


def _ledger_basis(c,p):
    return {table:[dict(r) for r in c.execute('SELECT id,amount_cents FROM '+table+' WHERE period_id=? ORDER BY id',(p['period_id'],)).fetchall()]
            for table in ('engine_cap_entries','engine_entitlement_entries')} | {
            'decisions':[r['id'] for r in c.execute('SELECT id FROM engine_decisions WHERE period_id=? ORDER BY sequence',(p['period_id'],)).fetchall()],
            'lifecycle':[r['id'] for r in c.execute('SELECT id FROM engine_lifecycle_events WHERE policy_id=? ORDER BY sequence',(p['id'],)).fetchall()]}


def _plan(c,p,through,now):
    days=_dates(date.fromisoformat(p['start']),through)
    if str(through)>p['end'] or through>now.astimezone(SGT).date():raise ValueError('Replay must remain within a known, nonfuture accepted term.')
    used=dict(ZERO);items=[]
    for day in days:
        key,state,evidence=_context(c,p,day,now)
        for peril in ('rain','haze'):
            status,target,reason=_assessment(p,peril,state,evidence,used)
            if target:
                used['total']+=target
                if peril=='rain':used['rain']+=1
                else:used['haze_days']+=1;used['haze_sgd']+=target
            actual=_event_total(c,'engine_entitlement_entries',p,day,peril)
            items.append({'day':str(day),'peril':peril,'context_sha256':key,'status':status,'target_sgd':target,'actual_entitlement_cents':actual,
                          'reason':reason,'evidence':evidence,'pending_preserves_prior_entitlement':status=='PENDING'})
    payload={'policy_id':p['id'],'term_id':p['term_id'],'through_day':str(through),'items':items,'ledger_basis':_ledger_basis(c,p),
             'theoretical_ordered_usage':used,'cap_policy':'positive_reservations_never_released; targets_can_be_limited_by_consumed_cap',
             'mode':'review_only_simulation','payment_execution':'NOT_SUBMITTED'}
    return payload,daily_evidence.digest(payload)


def plan_replay(stall,term_id,through,repository=None,*,now=None):
    now=now or utcnow()
    with (repository or configured_repository()).transaction() as c:
        p=life.term_context(c,stall,term_id=term_id);life.ensure_mode(c,p,'reviewed_evidence')
        payload,fingerprint=_plan(c,p,through,now)
        pid=entity_id('REPLAY-PLAN',p['term_id']+'|'+fingerprint)
        c.execute('INSERT INTO engine_replay_plans VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',(pid,p['id'],p['term_id'],str(through),fingerprint,canonical_json(payload),iso(now)))
        return {'plan_id':pid,'fingerprint':fingerprint,**payload,'approval_required':True}


def approve_replay(stall,plan_id,actor,source_ref,repository=None,*,now=None):
    now=now or utcnow();daily_evidence._reference(source_ref)
    with (repository or configured_repository()).transaction() as c:
        root=life.root(c,stall)
        plan=c.execute('SELECT * FROM engine_replay_plans WHERE id=? AND policy_id=?',(plan_id,root['id'])).fetchone()
        if not plan:raise LookupError('Unknown policy-owned replay plan.')
        daily_evidence._reviewer(c,actor)
        previous=c.execute('SELECT payload FROM engine_replay_reviews WHERE plan_id=?',(plan_id,)).fetchone()
        if previous:return {**json.loads(previous['payload']),'duplicate':True}
        p=life.term_context(c,stall,term_id=plan['term_id']);life.ensure_mode(c,p,'reviewed_evidence')
        payload,fingerprint=_plan(c,p,date.fromisoformat(plan['through_day']),now)
        if fingerprint!=plan['fingerprint']:raise ValueError('Replay inputs or ledger changed; create and review a fresh plan.')
        decisions=[]
        for item in payload['items']:
            decisions.append(_record(c,p,date.fromisoformat(item['day']),item['peril'],item['context_sha256'],
                              'review_pending' if item['status']=='PENDING' and item['actual_entitlement_cents'] else 'accepted',
                              item['status'],item['target_sgd'],item['reason'],item['evidence'],now,commit=True,review_key=plan_id))
        result={'plan_id':plan_id,'decisions':decisions,'used':c.used(p['period_id']),'payment_execution':'NOT_SUBMITTED','duplicate':False,'real_policy_issued':False}
        rid=entity_id('REPLAY-REVIEW',plan_id)
        c.execute('INSERT INTO engine_replay_reviews VALUES (?,?,?,?,?,?)',(rid,plan_id,actor,source_ref,canonical_json(result),iso(now)))
        c.audit(p['id'],'ordered_replay_approved',{'plan_id':plan_id,'actor_id':actor,'cap_restored':False,'payment_execution':False},iso(now))
        return result


def history(stall,repository=None):
    with (repository or configured_repository()).transaction() as c:
        p=life.root(c,stall)
        decisions=[json.loads(r['payload']) for r in c.execute('SELECT payload FROM engine_decisions WHERE policy_id=? ORDER BY day,peril,sequence',(p['id'],)).fetchall()]
        entitlements=[dict(r) for r in c.execute('SELECT * FROM engine_entitlement_entries WHERE policy_id=? ORDER BY recorded_at,id',(p['id'],)).fetchall()]
        caps=[dict(r) for r in c.execute('SELECT * FROM engine_cap_entries WHERE policy_id=? ORDER BY recorded_at,id',(p['id'],)).fetchall()]
        mock_summary={'payment_execution':'NOT_SUBMITTED','real_paid_cents':0}
        if c.execute('SELECT version FROM pilot_schema_migrations WHERE version=7').fetchone():
            from .settlement import policy_summary_in_unit
            mock_summary=policy_summary_in_unit(c,p['id'])
        return {'stall_id':stall,'policy_id':p['id'],'decisions':decisions,'entitlement_entries':entitlements,'cap_entries':caps,
                'net_entitlement_cents':sum(r['amount_cents'] for r in entitlements),'consumed_cap_cents':sum(r['amount_cents'] for r in caps),
                'payment_execution':mock_summary['payment_execution'],'mock_settlement':mock_summary,'disbursed_sgd':0,'mode':'reviewed_evidence_simulation'}
