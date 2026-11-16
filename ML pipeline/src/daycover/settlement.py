"""Transactional mock settlement coordinator; real rails and external wallets disabled."""
from datetime import date
import hashlib
import json
import re
import uuid

from . import daily_evidence as daily, policy_lifecycle as life
from .contracts import canonical_json
from .ledger_repository import configured_repository, entity_id, cents
from .weather_ingestion import utcnow, iso
from .settlement_provider import MockSettlementProvider, PROVIDER

SCENARIOS={'success','partial','failed','timeout','pending','reversal'}
FIELDS={'provider','instruction_id','provider_ref','recipient_id','recipient_review_id','currency','event_id','sequence','status','gross_cents','reversed_cents'}


def _role(c,actor,roles):
    row=c.execute('SELECT role,active FROM auth_principals WHERE id=?',(actor,)).fetchone()
    if not row or not row['active'] or row['role'] not in roles:raise ValueError('Active authorized local role required.')


def _key(key):
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,96}',key):raise ValueError('Use a bounded opaque idempotency key.')


def record_outbox(c,p,payload,now):
    oid='SIM-OUTBOX-'+payload['decision_id']
    c.execute('INSERT INTO settlement_outbox VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',
              (oid,p['id'],p['term_id'],p['period_id'],payload['day'],payload['peril'],payload['decision_id'],canonical_json(payload),iso(now)))
    return oid


def _recipient(c,p,rid):
    row=c.execute('SELECT * FROM settlement_recipients WHERE id=? AND merchant_id=?',(rid,p['merchant_id'])).fetchone()
    if not row:raise LookupError('Unknown merchant-owned mock recipient.')
    review=c.execute('SELECT * FROM settlement_recipient_reviews WHERE recipient_id=? ORDER BY sequence DESC LIMIT 1',(rid,)).fetchone()
    return row,review


def register_recipient(stall,reference,actor,repository=None,*,now=None):
    if not isinstance(reference,str) or not re.fullmatch(r'MOCK-[A-Za-z0-9_-]{3,48}',reference):raise ValueError('Use a MOCK- reference only; bank/PayNow/identity numbers are not accepted.')
    now=now or utcnow()
    with (repository or configured_repository()).transaction() as c:
        p=life.root(c,stall);_role(c,actor,('customer','operator'))
        sha=hashlib.sha256(reference.encode()).hexdigest();rid=entity_id('MOCK-RECIPIENT',p['merchant_id']+'|'+sha)
        c.execute('INSERT INTO settlement_recipients VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',
                  (rid,p['merchant_id'],actor,sha,entity_id('LOCAL-MOCK-WALLET',rid),'local_mock_only',iso(now)))
        c.audit(p['id'],'mock_recipient_registered',{'recipient_id':rid,'actor_id':actor,'real_recipient_verified':False},iso(now))
        return {'recipient_id':rid,'review_required':True,'verification_scope':'local_mock_only','real_recipient_verified':False,'external_wallet_bridge':False}


def review_recipient(stall,rid,decision,actor,source_ref,repository=None,*,now=None):
    daily._reference(source_ref)
    if decision not in ('approved','revoked'):raise ValueError('Unsupported mock recipient review.')
    now=now or utcnow()
    with (repository or configured_repository()).transaction() as c:
        p=life.root(c,stall);_role(c,actor,('reviewer',));recipient,review=_recipient(c,p,rid)
        if recipient['owner_id']==actor:raise ValueError('Independent mock recipient reviewer required.')
        if review and review['decision']==decision:return {'recipient_id':rid,'review_id':review['id'],'duplicate':True,'real_recipient_verified':False}
        review_id='MOCK-RECIPIENT-REVIEW-'+uuid.uuid4().hex
        c.execute('INSERT INTO settlement_recipient_reviews (id,recipient_id,actor_id,decision,source_ref,recorded_at) VALUES (?,?,?,?,?,?)',
                  (review_id,rid,actor,decision,source_ref,iso(now)))
        c.audit(p['id'],'mock_recipient_'+decision,{'recipient_id':rid,'review_id':review_id,'actor_id':actor,'real_verification':False},iso(now))
        return {'recipient_id':rid,'review_id':review_id,'decision':decision,'verification_scope':'local_mock_only','real_recipient_verified':False}


def _latest(c,p,day,peril):
    return c.execute('SELECT * FROM engine_decisions WHERE term_id=? AND day=? AND peril=? ORDER BY sequence DESC LIMIT 1',(p['term_id'],str(day),peril)).fetchone()


def _net(c,p,day,peril):
    return sum(r['amount_cents'] for r in c.execute('SELECT amount_cents FROM engine_entitlement_entries WHERE period_id=? AND day=? AND peril=?',(p['period_id'],str(day),peril)).fetchall())


def _authority(c,p,day,peril,now,decision_id=None):
    mode=c.execute('SELECT mode FROM engine_period_modes WHERE period_id=?',(p['period_id'],)).fetchone()
    if not mode or mode['mode']!='reviewed_evidence':return None,'reviewed_evidence_period_required'
    latest=_latest(c,p,day,peril)
    if not latest or latest['effect']!='accepted':return None,'entitlement_awaits_evidence_review'
    payload=json.loads(latest['payload'])
    if decision_id and latest['id']!=decision_id:return None,'accepted_decision_superseded'
    if payload['status']!='TRIGGERED' or _net(c,p,day,peril)<=0:return None,'no_current_payable_entitlement'
    if cents(payload['target_entitlement_sgd'])!=_net(c,p,day,peril):return None,'entitlement_ledger_mismatch'
    selection=daily.select_in_unit(c,p['stall_id'],day,now=now,persist=False,policy_context=p)
    state=life.state(c,p,day)
    context=daily.digest({'term':p['term_id'],'period':p['period_id'],'contract':p['contract_sha256'],'selection':selection['fingerprint'],'lifecycle_state':state})
    if context!=payload['context_sha256'] or state!='ACTIVE_SIMULATION':return None,'current_evidence_or_lifecycle_changed'
    return payload,None


def _state(c,instruction):
    row=c.execute("SELECT payload FROM settlement_provider_events WHERE instruction_id=? AND disposition='applied' ORDER BY provider_sequence DESC LIMIT 1",(instruction['id'],)).fetchone()
    if row:
        payload=json.loads(row['payload']);return {'status':payload['status'],'terminal':payload['status']!='pending','snapshot':payload}
    event=c.execute('SELECT state FROM settlement_instruction_events WHERE instruction_id=? ORDER BY sequence DESC LIMIT 1',(instruction['id'],)).fetchone()
    state=event['state'] if event else 'queued'
    return {'status':state,'terminal':state=='canceled_unsent','snapshot':None}


def _instruction(c,p,iid):
    row=c.execute('SELECT * FROM settlement_instructions WHERE id=? AND policy_id=? AND term_id=?',(iid,p['id'],p['term_id'])).fetchone()
    if not row:raise LookupError('Unknown term-owned mock instruction.')
    return row


def _public(c,instruction):
    state=_state(c,instruction)
    return {'instruction_id':instruction['id'],'outbox_id':instruction['outbox_id'],'decision_id':instruction['decision_id'],
            'recipient_id':instruction['recipient_id'],'amount_cents':instruction['amount_cents'],'provider_ref':instruction['provider_ref'],
            'day':instruction['day'],'peril':instruction['peril'],'status':state['status'],'terminal':state['terminal'],
            'mode':'mock_settlement_only','real_paid_cents':0,'real_transfer':False}


def _event(c,iid,state,reason,now,key):
    c.execute('INSERT INTO settlement_instruction_events (id,instruction_id,state,reason,recorded_at) VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING',
              (entity_id('SETTLEMENT-STATE',iid+'|'+key),iid,state,reason,iso(now)))


def _eligibility(c,p,instruction,now):
    payload,error=_authority(c,p,date.fromisoformat(instruction['day']),instruction['peril'],now,instruction['decision_id'])
    if error:return error
    recipient,review=_recipient(c,p,instruction['recipient_id'])
    if not review or review['decision']!='approved' or review['id']!=instruction['recipient_review_id']:return 'mock_recipient_review_changed_or_missing'
    if json.loads(instruction['authority'])['decision']!=payload:return 'immutable_instruction_authority_mismatch'
    return None


def _cancel_stale_unsent(c,p,now):
    for instruction in c.execute('SELECT * FROM settlement_instructions WHERE term_id=?',(p['term_id'],)).fetchall():
        if _state(c,instruction)['status']=='queued' and not c.execute('SELECT id FROM settlement_dispatch_attempts WHERE instruction_id=?',(instruction['id'],)).fetchone():
            reason=_eligibility(c,p,instruction,now)
            if reason:_event(c,instruction['id'],'canceled_unsent',reason,now,'canceled_unsent')


def _money(c,p,day,peril):
    entries=c.execute('SELECT amount_cents FROM settlement_cash_entries WHERE period_id=? AND day=? AND peril=?',(p['period_id'],str(day),peril)).fetchall()
    settled=sum(r['amount_cents'] for r in entries)
    reserved=0
    for instruction in c.execute('SELECT * FROM settlement_instructions WHERE period_id=? AND day=? AND peril=?',(p['period_id'],str(day),peril)).fetchall():
        if not _state(c,instruction)['terminal']:reserved+=instruction['amount_cents']
    owed=_net(c,p,day,peril)
    return {'net_entitlement_cents':owed,'confirmed_mock_cents':settled,'reserved_cents':reserved,
            'unreserved_cents':max(0,owed-settled-reserved),'overpaid_mock_cents':max(0,settled-owed),
            'overcommitted_cents':max(0,settled+reserved-owed)}


def sync(stall,term_id,repository=None,*,now=None):
    now=now or utcnow()
    with (repository or configured_repository()).transaction() as c:
        p=life.term_context(c,stall,term_id=term_id)
        mode=c.execute('SELECT mode FROM engine_period_modes WHERE period_id=?',(p['period_id'],)).fetchone()
        if mode and mode['mode']=='synthetic_demo':raise ValueError('Legacy synthetic receipts cannot fund reviewed-evidence settlement.')
        records=c.execute('SELECT * FROM engine_decisions WHERE term_id=? ORDER BY sequence',(term_id,)).fetchall()
        latest={(r['day'],r['peril']):r for r in records}
        for row in latest.values():
            payload=json.loads(row['payload'])
            if row['effect'] in ('accepted','review_pending') and (_net(c,p,row['day'],row['peril'])>0 or payload['entitlement_delta_cents']):record_outbox(c,p,payload,now)
        _cancel_stale_unsent(c,p,now)
        return {'term_id':term_id,'outbox_ids':[r['id'] for r in c.execute('SELECT id FROM settlement_outbox WHERE term_id=? ORDER BY day,peril,id',(term_id,)).fetchall()],
                'real_transfer':False,'mode':'mock_settlement_only'}


def queue(stall,term_id,outbox_id,recipient_id,key,scenario,actor,repository=None,*,now=None):
    _key(key)
    if scenario not in SCENARIOS:raise ValueError('Unsupported local mock settlement scenario.')
    now=now or utcnow()
    with (repository or configured_repository()).transaction() as c:
        p=life.term_context(c,stall,term_id=term_id);_role(c,actor,('service',))
        old=c.execute('SELECT * FROM settlement_instructions WHERE policy_id=? AND idempotency_key=?',(p['id'],key)).fetchone()
        if old:
            if any(old[k]!=v for k,v in [('term_id',term_id),('outbox_id',outbox_id),('recipient_id',recipient_id),('scenario',scenario)]):raise ValueError('Settlement idempotency key conflicts with another instruction.')
            return {**_public(c,old),'duplicate':True}
        outbox=c.execute('SELECT * FROM settlement_outbox WHERE id=? AND term_id=? AND policy_id=?',(outbox_id,term_id,p['id'])).fetchone()
        if not outbox:raise LookupError('Unknown policy-owned outbox event.')
        payload,error=_authority(c,p,date.fromisoformat(outbox['day']),outbox['peril'],now,outbox['decision_id'])
        if error:raise ValueError('Settlement remains pending: '+error)
        if json.loads(outbox['snapshot'])!=payload:raise ValueError('Outbox does not match the immutable accepted decision.')
        recipient,review=_recipient(c,p,recipient_id)
        if not review or review['decision']!='approved':raise ValueError('Independent mock recipient approval required; no real recipient is verified.')
        _cancel_stale_unsent(c,p,now)
        for outstanding in c.execute('SELECT * FROM settlement_instructions WHERE period_id=? AND day=? AND peril=?',(p['period_id'],outbox['day'],outbox['peril'])).fetchall():
            if not _state(c,outstanding)['terminal'] and outstanding['recipient_id']!=recipient_id:raise ValueError('Reconcile an existing transfer before changing its recipient.')
        money=_money(c,p,outbox['day'],outbox['peril']);amount=money['unreserved_cents']
        if amount<=0:raise ValueError('No unreserved net entitlement remains; reconcile pending or confirmed transfers.')
        iid=entity_id('MOCK-SETTLEMENT',p['id']+'|'+key)
        entries=[r['id'] for r in c.execute('SELECT id FROM engine_entitlement_entries WHERE period_id=? AND day=? AND peril=? ORDER BY id',(p['period_id'],outbox['day'],outbox['peril'])).fetchall()]
        authority={'decision':payload,'contract_version':p['version_id'],'contract_sha256':p['contract_sha256'],'period_id':p['period_id'],
                   'entitlement_entry_ids':entries,'recipient_review_id':review['id'],'wallet_id':recipient['wallet_id']}
        c.execute('INSERT INTO settlement_instructions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (iid,p['id'],term_id,p['period_id'],outbox_id,payload['decision_id'],recipient_id,review['id'],outbox['day'],outbox['peril'],amount,'SGD','MOCK-SETTLEMENT-PROVIDER-'+iid,key,scenario,canonical_json(authority),actor,iso(now)))
        _event(c,iid,'queued','net_entitlement_reserved_mock_only',now,'queued')
        c.audit(p['id'],'mock_settlement_queued',{'instruction_id':iid,'actor_id':actor,'amount_cents':amount,'real_transfer':False},iso(now))
        return {**_public(c,_instruction(c,p,iid)),'duplicate':False}


def dispatch(stall,term_id,instruction_id,actor,repository=None,*,provider=None,now=None):
    repo=repository or configured_repository();provider=provider or MockSettlementProvider(repo);now=now or utcnow()
    if provider.name!=PROVIDER:raise ValueError('Only the local mock settlement provider is enabled.')
    with repo.transaction() as c:
        p=life.term_context(c,stall,term_id=term_id);_role(c,actor,('service',));instruction=_instruction(c,p,instruction_id)
        state=_state(c,instruction)
        if state['terminal']:return {**_public(c,instruction),'duplicate':True}
        attempts=c.execute('SELECT id FROM settlement_dispatch_attempts WHERE instruction_id=?',(instruction_id,)).fetchall()
        reason=_eligibility(c,p,instruction,now)
        if reason:
            if not attempts:_event(c,instruction_id,'canceled_unsent',reason,now,'canceled_unsent')
            return {**_public(c,instruction),'submission':'NO_PROVIDER_CALL','reason':reason,'reconciliation_required':bool(attempts)}
        if len(attempts)>=3:return {**_public(c,instruction),'submission':'RECONCILE_ONLY','reason':'bounded_manual_retry_limit','reconciliation_required':True}
        number=len(attempts)+1;attempt_id=entity_id('SETTLEMENT-DISPATCH',instruction_id+'|'+str(number))
        c.execute('INSERT INTO settlement_dispatch_attempts (id,instruction_id,attempt_number,actor_id,recorded_at) VALUES (?,?,?,?,?)',(attempt_id,instruction_id,number,actor,iso(now)))
        _event(c,instruction_id,'uncertain','durable_submission_intent_before_provider',now,'intent:'+attempt_id)
    try:ack=provider.submit(dict(instruction))
    except TimeoutError:ack=None
    with repo.transaction() as c:
        p=life.term_context(c,stall,term_id=term_id);instruction=_instruction(c,p,instruction_id)
        if ack and (ack.provider_ref!=instruction['provider_ref'] or ack.state not in ('submitted','uncertain')):raise ValueError('Mock provider acknowledgement binding mismatch.')
        _event(c,instruction_id,ack.state if ack else 'uncertain','submission_is_not_confirmation',now,'ack:'+attempt_id)
        c.audit(p['id'],'mock_settlement_dispatched',{'instruction_id':instruction_id,'actor_id':actor,'dispatch_attempt':number,'real_transfer':False},iso(now))
        return {**_public(c,instruction),'submission_only':True,'real_paid_cents':0}


def _receipt(c,instruction,payload,disposition,reason,now):
    encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=True,default=str);sha=hashlib.sha256(encoded.encode()).hexdigest()
    event_id=str(payload.get('event_id','invalid'))[:200] if isinstance(payload,dict) else 'invalid';seq=payload.get('sequence',0) if isinstance(payload,dict) else 0
    seq=seq if type(seq) is int and 0<=seq<2**31 else 0
    rid=entity_id('SETTLEMENT-RECEIPT',instruction['id']+'|'+event_id+'|'+sha+'|'+disposition+'|'+reason)
    c.execute('INSERT INTO settlement_provider_events VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',(rid,instruction['id'],event_id,seq,encoded,sha,disposition,reason,iso(now)))
    return rid,sha


def _validate(c,instruction,payload,signature):
    if not isinstance(payload,dict) or set(payload)!=FIELDS:return 'invalid_event_schema'
    for field in ('provider','instruction_id','provider_ref','recipient_id','recipient_review_id','currency','event_id','status'):
        if not isinstance(payload[field],str) or not 1<=len(payload[field])<=200:return 'invalid_event_identifier'
    if any(type(payload[k]) is not int or not 0<=payload[k]<2**31 for k in ('sequence','gross_cents','reversed_cents')) or payload['sequence']<1:return 'invalid_cumulative_amount'
    if not MockSettlementProvider.verify(c,payload,signature):return 'invalid_mock_signature'
    if (payload['provider'],payload['instruction_id'],payload['provider_ref'],payload['recipient_id'],payload['recipient_review_id'],payload['currency'])!=(PROVIDER,instruction['id'],instruction['provider_ref'],instruction['recipient_id'],instruction['recipient_review_id'],'SGD'):return 'instruction_or_recipient_reference_mismatch'
    if not c.execute('SELECT id FROM settlement_dispatch_attempts WHERE instruction_id=?',(instruction['id'],)).fetchone() or not c.execute('SELECT instruction_id FROM settlement_mock_jobs WHERE instruction_id=?',(instruction['id'],)).fetchone():return 'no_authorized_provider_submission'
    gross,returned,status=payload['gross_cents'],payload['reversed_cents'],payload['status']
    if gross>instruction['amount_cents'] or returned>gross:return 'amount_exceeds_immutable_instruction'
    if status not in ('pending','failed','confirmed','partially_confirmed','reversed'):return 'unsupported_provider_state'
    if status in ('pending','failed') and (gross or returned):return 'invalid_zero_outcome'
    if status=='confirmed' and (gross!=instruction['amount_cents'] or returned):return 'invalid_confirmation'
    if status=='partially_confirmed' and (not 0<gross<instruction['amount_cents'] or returned):return 'invalid_partial_outcome'
    if status=='reversed' and returned<=0:return 'invalid_reversal'
    return None


def _post_cash(c,p,instruction,receipt,kind,amount,now):
    eid=entity_id('MOCK-SETTLEMENT-CASH',receipt+'|'+kind)
    c.execute('INSERT INTO settlement_cash_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
              (eid,p['id'],p['term_id'],p['period_id'],instruction['id'],receipt,instruction['day'],instruction['peril'],kind,amount,'SGD',kind+':'+receipt,iso(now)))
    wallet=c.execute('SELECT wallet_id FROM settlement_recipients WHERE id=?',(instruction['recipient_id'],)).fetchone()['wallet_id']
    c.execute('INSERT INTO settlement_mock_wallet_entries VALUES (?,?,?,?,?,?)',(entity_id('MOCK-WALLET-ENTRY',eid),wallet,eid,amount,'SGD',iso(now)))


def ingest_event(stall,term_id,instruction_id,payload,signature,repository=None,*,now=None):
    now=now or utcnow()
    with (repository or configured_repository()).transaction() as c:
        p=life.term_context(c,stall,term_id=term_id);instruction=_instruction(c,p,instruction_id);error=_validate(c,instruction,payload,signature)
        if error:
            _receipt(c,instruction,payload,'quarantined',error,now)
            return {'accepted':False,'quarantined':True,'reason':error,'wallet_changed':False,'real_transfer':False}
        sha=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        existing=c.execute("SELECT * FROM settlement_provider_events WHERE event_id=? AND disposition IN ('applied','stale')",(payload['event_id'],)).fetchone()
        if existing:
            if existing['payload_sha256']==sha:return {'accepted':True,'duplicate':True,'wallet_changed':False,'real_transfer':False}
            _receipt(c,instruction,payload,'quarantined','event_id_payload_conflict',now)
            return {'accepted':False,'quarantined':True,'reason':'event_id_payload_conflict','real_transfer':False}
        old=_state(c,instruction)['snapshot']
        if old and payload['sequence']<=old['sequence']:
            stale=payload['sequence']<old['sequence'];_receipt(c,instruction,payload,'stale' if stale else 'quarantined','older_snapshot' if stale else 'sequence_conflict',now)
            return {'accepted':stale,'stale':stale,'quarantined':not stale,'wallet_changed':False,'real_transfer':False}
        old=old or {'gross_cents':0,'reversed_cents':0,'status':'pending'}
        if payload['gross_cents']<old['gross_cents'] or payload['reversed_cents']<old['reversed_cents'] or (old['status']!='pending' and payload['gross_cents']!=old['gross_cents']) or (old['status']!='pending' and payload['status']!=old['status'] and payload['status'] in ('pending','failed','partially_confirmed')):
            _receipt(c,instruction,payload,'quarantined','invalid_terminal_or_cumulative_transition',now)
            return {'accepted':False,'quarantined':True,'reason':'invalid_terminal_or_cumulative_transition','real_transfer':False}
        rid,_=_receipt(c,instruction,payload,'applied','validated_mock_provider_snapshot',now)
        gross=payload['gross_cents']-old['gross_cents'];returned=payload['reversed_cents']-old['reversed_cents']
        if gross:_post_cash(c,p,instruction,rid,'mock_confirmed',gross,now)
        if returned:_post_cash(c,p,instruction,rid,'mock_reversal',-returned,now)
        c.audit(p['id'],'mock_settlement_reconciled',{'instruction_id':instruction_id,'receipt_id':rid,'mock_credit_delta_cents':gross-returned,'real_transfer':False},iso(now))
        return {'accepted':True,'status':payload['status'],'wallet_changed':bool(gross or returned),'duplicate':False,'real_paid_cents':0,'real_transfer':False}


def reconcile(stall,term_id,instruction_id,repository=None,*,provider=None,now=None):
    repo=repository or configured_repository();provider=provider or MockSettlementProvider(repo)
    if provider.name!=PROVIDER:raise ValueError('Only local mock settlement reconciliation is enabled.')
    with repo.transaction() as c:_instruction(c,life.term_context(c,stall,term_id=term_id),instruction_id)
    envelope=provider.status(instruction_id)
    if envelope is None:return {'accepted':False,'status':'uncertain','reason':'No definitive provider snapshot; reservation retained.','real_transfer':False}
    return ingest_event(stall,term_id,instruction_id,envelope['payload'],envelope['signature'],repo,now=now)


def overview(stall,term_id,repository=None,*,now=None):
    now=now or utcnow()
    with (repository or configured_repository()).transaction() as c:
        p=life.term_context(c,stall,term_id=term_id)
        instructions=c.execute('SELECT * FROM settlement_instructions WHERE term_id=? ORDER BY created_at,id',(term_id,)).fetchall()
        decisions=c.execute('SELECT * FROM engine_decisions WHERE term_id=? ORDER BY sequence',(term_id,)).fetchall()
        latest={(r['day'],r['peril']):r for r in decisions}
        events=[]
        for (day,peril),row in sorted(latest.items()):
            _,reason=_authority(c,p,date.fromisoformat(day),peril,now)
            events.append({'day':day,'peril':peril,'decision_id':row['id'],'entitlement_status':json.loads(row['payload'])['status'],
                           **_money(c,p,day,peril),'current_qualification':reason or 'qualified_reviewed_simulation'})
        summary={k:sum(e[k] for e in events) for k in ('net_entitlement_cents','confirmed_mock_cents','reserved_cents','unreserved_cents','overpaid_mock_cents','overcommitted_cents')}
        issues=[]
        for instruction in instructions:
            snapshot=_state(c,instruction)['snapshot']
            expected=(snapshot['gross_cents']-snapshot['reversed_cents']) if snapshot else 0
            actual=sum(r['amount_cents'] for r in c.execute('SELECT amount_cents FROM settlement_cash_entries WHERE instruction_id=?',(instruction['id'],)).fetchall())
            if actual!=expected:issues.append({'instruction_id':instruction['id'],'reason':'confirmed_snapshot_cash_mismatch'})
        wallet=sum(r['amount_cents'] for r in c.execute('SELECT w.amount_cents FROM settlement_mock_wallet_entries w JOIN settlement_cash_entries e ON e.id=w.cash_entry_id WHERE e.period_id=?',(p['period_id'],)).fetchall())
        summary['mock_wallet_net_cents']=wallet
        if wallet!=summary['confirmed_mock_cents']:issues.append({'reason':'mock_wallet_cash_mismatch'})
        quarantine=c.execute("SELECT COUNT(*) AS n FROM settlement_provider_events e JOIN settlement_instructions i ON i.id=e.instruction_id WHERE i.term_id=? AND e.disposition='quarantined'",(term_id,)).fetchone()['n']
        outbox=[]
        for row in c.execute('SELECT * FROM settlement_outbox WHERE term_id=? ORDER BY day,peril,id',(term_id,)).fetchall():
            _,reason=_authority(c,p,date.fromisoformat(row['day']),row['peril'],now,row['decision_id'])
            linked=[_public(c,i) for i in instructions if i['outbox_id']==row['id']]
            outbox.append({'outbox_id':row['id'],'decision_id':row['decision_id'],'day':row['day'],'peril':row['peril'],
                           'status':'blocked' if reason else 'pending' if not linked else 'instructions_created','blocking_reason':reason,'instruction_ids':[i['instruction_id'] for i in linked]})
        recipients=[]
        for row in c.execute('SELECT * FROM settlement_recipients WHERE merchant_id=? ORDER BY id',(p['merchant_id'],)).fetchall():
            _,review=_recipient(c,p,row['id'])
            recipients.append({'recipient_id':row['id'],'status':'approved_mock_only' if review and review['decision']=='approved' else 'pending_or_revoked',
                               'review_id':review['id'] if review else None,'real_recipient_verified':False})
        return {'policy_id':p['id'],'term_id':term_id,'period_id':p['period_id'],'mode':'mock_settlement_only','summary':summary,'events':events,'outbox':outbox,
                'instructions':[_public(c,i) for i in instructions],'recipients':recipients,'quarantined_callbacks':quarantine,
                'reconciliation_issues':issues,'review_required':bool(issues or quarantine or summary['overpaid_mock_cents'] or summary['overcommitted_cents'] or any(e['current_qualification']!='qualified_reviewed_simulation' and (e['net_entitlement_cents'] or e['confirmed_mock_cents'] or e['reserved_cents']) for e in events)),
                'real_paid_cents':0,'external_wallet_bridge':False,'real_rail_enabled':False,'manual_submission_retry_limit':3,
                'explanation':'Submission/unknown outcomes are not confirmed. Only validated mock provider outcomes credit the local mock wallet; no real transfer occurred.'}


def policy_summary_in_unit(c,policy_id):
    cash=c.execute('SELECT kind,amount_cents FROM settlement_cash_entries WHERE policy_id=?',(policy_id,)).fetchall()
    instructions=c.execute('SELECT * FROM settlement_instructions WHERE policy_id=?',(policy_id,)).fetchall()
    reserved=sum(i['amount_cents'] for i in instructions if not _state(c,i)['terminal'])
    return {'payment_execution':'NOT_SUBMITTED' if not instructions else 'MOCK_PENDING' if reserved else 'MOCK_OUTCOMES_RECORDED',
            'confirmed_net_mock_cents':sum(r['amount_cents'] for r in cash),'reserved_mock_cents':reserved,
            'real_paid_cents':0,'external_wallet_bridge':False}
