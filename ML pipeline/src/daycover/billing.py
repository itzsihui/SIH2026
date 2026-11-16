"""Exact simulation billing and confirmed mock collection reconciliation.

No real mandate/debit adapter, subsidy funding, automatic retry/grace/lapse or refund
eligibility policy is established. Coverage/entitlement ledgers are independent.
"""
import calendar
from datetime import date
from decimal import Decimal
import hashlib
import json
import re
import uuid

from . import policy_lifecycle as life
from .contracts import canonical_json
from .ingestion import SGT
from .ledger_repository import configured_repository, entity_id, cents
from .weather_ingestion import utcnow, iso
from .billing_provider import MockCollectionProvider, PROVIDER

CONVENTION='monthly-term-start-clamp-v1-simulation'
SCENARIOS={'success','partial','failed','timeout','pending','reversal'}
EVENT_FIELDS={'provider','attempt_id','bill_id','provider_ref','event_id','sequence','currency','status','gross_cents','refunded_cents','reversed_cents','refund_request_id'}


def _key(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,96}',value):raise ValueError('Use a bounded opaque idempotency key.')


def projection(p):
    contract=json.loads(p['contract']);amounts=contract['instalments_cents'];annual=cents(contract['annual_premium_sgd'])
    if amounts!=[867]*8+[866]*4 or annual!=10400 or contract['billing_choice']!='monthly_giro_proposed_not_connected' or contract['subsidy_sgd']!=0:
        raise ValueError('Unsupported billing terms; no silent substitute or subsidy.')
    anchor=date.fromisoformat(p['start']);sid=entity_id('BILLING-SCHEDULE',p['term_id']+'|'+CONVENTION+'|'+p['contract_sha256'])
    bills=[]
    for index,amount in enumerate(amounts):
        year,month=divmod(anchor.year*12+anchor.month-1+index,12);month+=1
        due=date(year,month,min(anchor.day,calendar.monthrange(year,month)[1]))
        bills.append({'id':entity_id('BILL',sid+'|'+str(index+1)),'instalment':index+1,'due_on':str(due),'amount_cents':amount,'currency':'SGD'})
    return sid,bills


def _auth(c,p,as_of):
    row=c.execute('SELECT * FROM billing_authorizations WHERE term_id=? ORDER BY sequence DESC LIMIT 1',(p['term_id'],)).fetchone()
    valid=bool(row and row['action']=='grant' and str(as_of)<=p['end'] and life.state(c,p,as_of)!='CANCELED_SIMULATION')
    return {'status':'active_mock_only' if valid else 'revoked' if row and row['action']=='revoke' else 'expired_or_canceled' if row else 'missing',
            'authorization_id':row['id'] if row else None,'active':valid,'real_mandate_status':'NOT_CONNECTED','purpose':'mock_collections_only'}


def _event_state(c,attempt):
    row=c.execute("SELECT payload FROM billing_provider_events WHERE attempt_id=? AND disposition='applied' ORDER BY provider_sequence DESC LIMIT 1",(attempt['id'],)).fetchone()
    if row:
        payload=json.loads(row['payload']);return {'status':payload['status'],'terminal':payload['status']!='pending','snapshot':payload}
    dispatch=c.execute('SELECT state FROM billing_dispatches WHERE attempt_id=? ORDER BY sequence DESC LIMIT 1',(attempt['id'],)).fetchone()
    status=dispatch['state'] if dispatch else 'authorized'
    return {'status':status,'terminal':status=='canceled_unsubmitted','snapshot':None}


def _bill_entries(c,bill):
    return c.execute('''SELECT e.* FROM pilot_billing_entries e JOIN billing_entry_links l ON l.entry_id=e.id WHERE l.bill_id=?''',(bill['id'],)).fetchall()


def _bill_state(c,bill,stored=True):
    entries=_bill_entries(c,bill) if stored else []
    for entry in entries:
        if entry['kind'] not in ('obligation','collection','refund','compensation') or entry['currency']!='SGD':
            raise ValueError('Unsupported funded credit or billing entry; explicit source review required.')
        if (entry['kind']=='collection' and entry['amount_cents']>=0) or (entry['kind']!='collection' and entry['amount_cents']<=0):
            raise ValueError('Billing entry sign does not reconcile with its kind.')
    if stored and sum(r['amount_cents'] for r in entries if r['kind']=='obligation')!=bill['amount_cents']:raise ValueError('Bill obligations do not reconcile; review required.')
    gross=-sum(r['amount_cents'] for r in entries if r['kind']=='collection')
    refunded=sum(r['amount_cents'] for r in entries if r['kind']=='refund')
    reversed_=sum(r['amount_cents'] for r in entries if r['kind']=='compensation')
    retained=gross-refunded-reversed_
    if not 0<=retained<=bill['amount_cents']:raise ValueError('Confirmed mock balance is outside the bill; review required.')
    attempts=[];pending=0;failed=0;partial_uncollected=0
    for attempt in c.execute('SELECT * FROM billing_attempts WHERE bill_id=? ORDER BY created_at,id',(bill['id'],)).fetchall() if stored else []:
        state=_event_state(c,attempt)
        if not state['terminal']:pending+=attempt['amount_cents']
        if state['status']=='failed':failed+=attempt['amount_cents']
        if state['status']=='partially_collected':partial_uncollected+=attempt['amount_cents']-state['snapshot']['gross_cents']
        attempts.append({'attempt_id':attempt['id'],'provider_ref':attempt['provider_ref'],'authorized_cents':attempt['amount_cents'],'status':state['status'],'scenario':attempt['scenario']})
    outstanding=bill['amount_cents']-retained
    if pending>outstanding:raise ValueError('Pending reservations exceed bill outstanding; reconciliation required.')
    return {**bill,'gross_collected_cents':gross,'refunded_cents':refunded,'reversed_cents':reversed_,'collected_cents':retained,
            'outstanding_cents':outstanding,'pending_cents':pending,'available_to_attempt_cents':outstanding-pending,
            'failed_attempt_cents':failed,'partial_uncollected_cents':partial_uncollected,'sponsor_funded_cents':0,'attempts':attempts}


def _statement(c,p,as_of):
    sid,bills=projection(p)
    schedule=c.execute('SELECT * FROM billing_schedules WHERE term_id=?',(p['term_id'],)).fetchone()
    if schedule and (schedule['id']!=sid or schedule['contract_sha256']!=p['contract_sha256']):raise ValueError('Billing schedule differs from accepted terms.')
    if schedule:
        actual=[dict(r) for r in c.execute('SELECT * FROM billing_bills WHERE schedule_id=? ORDER BY instalment',(sid,)).fetchall()]
        if len(actual)!=12 or any(any(row[k]!=bill[k] for k in bill) for row,bill in zip(actual,bills)):raise ValueError('Stored schedule differs from the frozen projection.')
    states=[_bill_state(c,bill,bool(schedule)) for bill in bills]
    summary={field:sum(b[field] for b in states) for field in ('amount_cents','gross_collected_cents','refunded_cents','reversed_cents','collected_cents','outstanding_cents','pending_cents','failed_attempt_cents','partial_uncollected_cents','sponsor_funded_cents')}
    summary['annual_obligation_cents']=summary.pop('amount_cents')
    summary['due_outstanding_cents']=sum(b['outstanding_cents'] for b in states if b['due_on']<=str(as_of))
    summary['future_outstanding_cents']=summary['outstanding_cents']-summary['due_outstanding_cents']
    quarantine=c.execute("SELECT COUNT(*) AS n FROM billing_provider_events e JOIN billing_attempts a ON a.id=e.attempt_id WHERE a.term_id=? AND e.disposition='quarantined'",(p['term_id'],)).fetchone()['n']
    return {'policy_id':p['id'],'term_id':p['term_id'],'period_id':p['period_id'],'schedule_id':sid,'prepared':bool(schedule),'as_of':str(as_of),
            'convention':CONVENTION,'due_dates':'simulation_projections_not_confirmed_debit_dates','currency':'SGD','mode':'mock_billing_only',
            'summary':summary,'bills':states,'authorization':_auth(c,p,as_of),'quarantined_callbacks':quarantine,'review_required':bool(quarantine),
            'real_collected_cents':0,'real_refunded_cents':0,'real_mandate_connected':False,'provider':PROVIDER,
            'commercial_rules':{k:'not_specified_not_invented' for k in ('first_payment','actual_mandate','automatic_retry','grace','lapse','refund_eligibility','cancellation_proration')},
            'sponsor_credit_enabled':False,'explanation':'All balances are simulated. Submission alone is not collection; only validated cumulative mock outcomes affect balances. No debit occurred.'}


def statement(stall,term_id,repository=None,*,as_of=None):
    with (repository or configured_repository()).transaction() as c:return _statement(c,life.term_context(c,stall,term_id=term_id),as_of or utcnow().astimezone(SGT).date())


def _post(c,p,bill,kind,amount,key,now,attempt=None,receipt=None):
    eid=entity_id('BILLING-ENTRY',key)
    reversal=None
    if kind in ('refund','compensation') and attempt:
        prior=c.execute("SELECT e.id FROM pilot_billing_entries e JOIN billing_entry_links l ON l.entry_id=e.id WHERE l.attempt_id=? AND e.kind='collection' ORDER BY e.recorded_at,e.id LIMIT 1",(attempt['id'],)).fetchone()
        reversal=prior['id'] if prior else None
    c.execute('INSERT INTO pilot_billing_entries VALUES (?,?,?,?,?,?,?,?,?,?)',
              (eid,p['id'],p['period_id'],kind,amount,'SGD',bill['due_on'],reversal,key,iso(now)))
    c.execute('INSERT INTO billing_entry_links VALUES (?,?,?,?)',(eid,bill['id'],attempt['id'] if attempt else None,receipt))


def prepare(stall,term_id,repository=None,*,now=None):
    now=now or utcnow()
    with (repository or configured_repository()).transaction() as c:
        p=life.term_context(c,stall,term_id=term_id);sid,bills=projection(p)
        exists=c.execute('SELECT id FROM billing_schedules WHERE term_id=?',(term_id,)).fetchone()
        if not exists:
            if c.execute('SELECT id FROM pilot_billing_entries WHERE period_id=?',(p['period_id'],)).fetchone():raise ValueError('Unlinked existing billing entries require explicit import review.')
            c.execute('INSERT INTO billing_schedules VALUES (?,?,?,?,?,?,?,?,?)',(sid,p['id'],term_id,p['period_id'],p['contract_sha256'],CONVENTION,10400,'SGD',iso(now)))
            for bill in bills:
                c.execute('INSERT INTO billing_bills VALUES (?,?,?,?,?,?)',(bill['id'],sid,bill['instalment'],bill['due_on'],bill['amount_cents'],'SGD'))
                _post(c,p,bill,'obligation',bill['amount_cents'],'obligation:'+bill['id'],now)
            c.audit(p['id'],'mock_billing_schedule_prepared',{'term_id':term_id,'annual_cents':10400,'real_collection':False},iso(now))
        return _statement(c,p,now.astimezone(SGT).date())


def _dispatch(c,attempt_id,state,now):
    c.execute('INSERT INTO billing_dispatches (id,attempt_id,state,recorded_at) VALUES (?,?,?,?) ON CONFLICT DO NOTHING',(entity_id('MOCK-DISPATCH',attempt_id+'|'+state),attempt_id,state,iso(now)))


def authorize(stall,term_id,actor,action,repository=None,*,now=None):
    if action not in ('grant','revoke'):raise ValueError('Invalid mock authorization action.')
    now=now or utcnow()
    with (repository or configured_repository()).transaction() as c:
        p=life.term_context(c,stall,term_id=term_id)
        who=c.execute('SELECT role,active FROM auth_principals WHERE id=?',(actor,)).fetchone()
        if not who or not who['active'] or who['role'] not in ('customer','operator'):raise ValueError('Customer/operator mock authorization required.')
        if action=='grant' and (str(now.astimezone(SGT).date())>p['end'] or life.state(c,p,now.astimezone(SGT).date())=='CANCELED_SIMULATION'):raise ValueError('Expired/canceled simulation cannot grant new collection permission.')
        latest=c.execute('SELECT * FROM billing_authorizations WHERE term_id=? ORDER BY sequence DESC LIMIT 1',(term_id,)).fetchone()
        duplicate=bool(latest and latest['action']==action)
        if not duplicate:
            aid='MOCK-AUTH-'+uuid.uuid4().hex
            c.execute('INSERT INTO billing_authorizations (id,term_id,actor_id,action,purpose,recorded_at) VALUES (?,?,?,?,?,?)',(aid,term_id,actor,action,'mock_collections_only',iso(now)))
            if action=='revoke':
                for attempt in c.execute('SELECT * FROM billing_attempts WHERE term_id=?',(term_id,)).fetchall():
                    if _event_state(c,attempt)['status']=='authorized':_dispatch(c,attempt['id'],'canceled_unsubmitted',now)
            c.audit(p['id'],'mock_collection_authorization_'+action,{'term_id':term_id,'actor_id':actor,'real_mandate':False},iso(now))
        return {**_auth(c,p,now.astimezone(SGT).date()),'duplicate':duplicate,'real_debit':False}


def _attempt(c,p,attempt_id):
    row=c.execute('SELECT * FROM billing_attempts WHERE id=? AND policy_id=? AND term_id=?',(attempt_id,p['id'],p['term_id'])).fetchone()
    if not row:raise LookupError('Unknown term-owned mock attempt.')
    return row


def _public_attempt(c,a):
    state=_event_state(c,a)
    return {'attempt_id':a['id'],'bill_id':a['bill_id'],'authorized_cents':a['amount_cents'],'provider_ref':a['provider_ref'],
            'status':state['status'],'terminal':state['terminal'],'mode':'mock_billing_only','real_debit':False}


def create_attempt(stall,term_id,bill_id,key,scenario,actor,repository=None,*,now=None):
    _key(key)
    if scenario not in SCENARIOS:raise ValueError('Unsupported deterministic mock scenario.')
    now=now or utcnow();today=now.astimezone(SGT).date()
    with (repository or configured_repository()).transaction() as c:
        p=life.term_context(c,stall,term_id=term_id)
        who=c.execute('SELECT role,active FROM auth_principals WHERE id=?',(actor,)).fetchone()
        if not who or who['role']!='service' or not who['active']:raise ValueError('Controlled service credential required.')
        old=c.execute('SELECT * FROM billing_attempts WHERE policy_id=? AND idempotency_key=?',(p['id'],key)).fetchone()
        if old:
            if old['term_id']!=term_id or old['bill_id']!=bill_id or old['scenario']!=scenario:raise ValueError('Idempotency key conflicts with a different collection request.')
            return {**_public_attempt(c,old),'duplicate':True}
        authorization=_auth(c,p,today)
        if not authorization['active']:raise ValueError('Current explicit mock collection authorization required; no GIRO mandate is connected.')
        bill=c.execute('SELECT b.* FROM billing_bills b JOIN billing_schedules s ON s.id=b.schedule_id WHERE b.id=? AND s.term_id=?',(bill_id,term_id)).fetchone()
        if not bill:raise LookupError('Prepare a policy-owned billing schedule first.')
        if bill['due_on']>str(today):raise ValueError('Future projected instalments cannot be attempted in this mock.')
        state=_bill_state(c,bill);amount=state['available_to_attempt_cents']
        if amount<=0:raise ValueError('Bill is collected or reserved by an unresolved attempt; reconcile before retry.')
        aid=entity_id('MOCK-COLLECTION',p['id']+'|'+key);ref='MOCK-PROVIDER-'+aid
        c.execute('INSERT INTO billing_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                  (aid,p['id'],term_id,bill_id,authorization['authorization_id'],actor,amount,'SGD',scenario,ref,key,iso(now)))
        c.audit(p['id'],'mock_collection_authorized',{'attempt_id':aid,'bill_id':bill_id,'amount_cents':amount,'actor_id':actor},iso(now))
        return {**_public_attempt(c,_attempt(c,p,aid)),'duplicate':False}


def submit(stall,term_id,attempt_id,repository=None,*,provider=None,now=None):
    repo=repository or configured_repository();provider=provider or MockCollectionProvider(repo);now=now or utcnow()
    if provider.name!=PROVIDER:raise ValueError('Only the local deterministic mock is enabled.')
    with repo.transaction() as c:
        p=life.term_context(c,stall,term_id=term_id);a=_attempt(c,p,attempt_id)
        state=_event_state(c,a)
        if state['terminal']:return {**_public_attempt(c,a),'duplicate':True}
        permission=_auth(c,p,now.astimezone(SGT).date())
        if not permission['active'] or permission['authorization_id']!=a['authorization_id']:
            if state['status']=='authorized':_dispatch(c,a['id'],'canceled_unsubmitted',now)
            return {**_public_attempt(c,a),'submission':'NO_NEW_PROVIDER_CALL','reconciliation_required':state['status']!='authorized'}
        _dispatch(c,a['id'],'submitting',now)
    # No database transaction is held across the provider boundary.
    try:ack=provider.submit(dict(a))
    except TimeoutError:ack=None
    with repo.transaction() as c:
        p=life.term_context(c,stall,term_id=term_id);a=_attempt(c,p,attempt_id)
        if ack and (ack.provider_ref!=a['provider_ref'] or ack.state not in ('submitted','uncertain')):raise ValueError('Provider acknowledgement binding mismatch.')
        _dispatch(c,a['id'],ack.state if ack else 'uncertain',now)
        confirmed=_event_state(c,a)['snapshot']
        return {**_public_attempt(c,a),'submission_only':True,'collection_confirmed':bool(confirmed and confirmed['gross_cents']>0)}


def _receipt(c,a,payload,disposition,reason,now):
    encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=True,default=str)
    sha=hashlib.sha256(encoded.encode()).hexdigest();event_id=str(payload.get('event_id','invalid'))[:200] if isinstance(payload,dict) else 'invalid'
    seq=payload.get('sequence',0) if isinstance(payload,dict) else 0
    seq=seq if type(seq) is int and 0<=seq<2**31 else 0
    rid=entity_id('BILLING-RECEIPT',a['id']+'|'+event_id+'|'+sha+'|'+disposition+'|'+reason)
    c.execute('INSERT INTO billing_provider_events VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',(rid,a['id'],event_id,seq,encoded,sha,disposition,reason,iso(now)))
    return rid,sha


def _validate_event(c,a,payload,signature):
    if not isinstance(payload,dict) or set(payload)!=EVENT_FIELDS:return 'invalid_event_schema'
    if any(not isinstance(payload[k],str) or not 1<=len(payload[k])<=200 for k in ('provider','attempt_id','bill_id','provider_ref','event_id','currency','status')):return 'invalid_event_identifiers'
    if any(type(payload[k]) is not int or not 0<=payload[k]<2**31 for k in ('sequence','gross_cents','refunded_cents','reversed_cents')) or payload['sequence']<1:return 'invalid_event_amounts'
    if payload['refund_request_id'] is not None and (not isinstance(payload['refund_request_id'],str) or len(payload['refund_request_id'])>200):return 'invalid_refund_reference'
    if not MockCollectionProvider.verify(c,payload,signature):return 'invalid_mock_signature'
    if (payload['provider'],payload['attempt_id'],payload['bill_id'],payload['provider_ref'],payload['currency'])!=(PROVIDER,a['id'],a['bill_id'],a['provider_ref'],'SGD'):return 'provider_reference_mismatch'
    if not c.execute("SELECT id FROM billing_dispatches WHERE attempt_id=? AND state='submitting'",(a['id'],)).fetchone() or not c.execute('SELECT attempt_id FROM billing_mock_jobs WHERE attempt_id=?',(a['id'],)).fetchone():return 'no_authorized_submission'
    gross,refund,reversal=payload['gross_cents'],payload['refunded_cents'],payload['reversed_cents'];status=payload['status']
    if gross>a['amount_cents'] or refund+reversal>gross:return 'provider_amount_exceeds_authorization'
    if status not in ('pending','failed','partially_collected','confirmed','refunded','reversed'):return 'unsupported_provider_status'
    if status in ('pending','failed') and (gross or refund or reversal):return 'invalid_zero_outcome'
    if status=='confirmed' and (gross!=a['amount_cents'] or refund or reversal):return 'invalid_confirmation'
    if status=='partially_collected' and (not 0<gross<a['amount_cents'] or refund or reversal):return 'invalid_partial_outcome'
    if status=='refunded':
        request=c.execute('SELECT * FROM billing_refund_requests WHERE id=? AND attempt_id=?',(payload['refund_request_id'],a['id'])).fetchone()
        if not request or not 0<refund<=request['amount_cents']:return 'refund_not_explicitly_authorized'
    if status=='reversed' and reversal<=0:return 'invalid_reversal'
    return None


def ingest_event(stall,term_id,attempt_id,payload,signature,repository=None,*,now=None):
    now=now or utcnow()
    with (repository or configured_repository()).transaction() as c:
        p=life.term_context(c,stall,term_id=term_id);a=_attempt(c,p,attempt_id)
        error=_validate_event(c,a,payload,signature)
        if error:
            _receipt(c,a,payload,'quarantined',error,now)
            return {'accepted':False,'quarantined':True,'reason':error,'balance_changed':False,'real_debit':False}
        encoded=json.dumps(payload,sort_keys=True,separators=(',',':'));sha=hashlib.sha256(encoded.encode()).hexdigest()
        existing=c.execute("SELECT * FROM billing_provider_events WHERE event_id=? AND disposition IN ('applied','stale')",(payload['event_id'],)).fetchone()
        if existing:
            if existing['payload_sha256']==sha:return {'accepted':True,'duplicate':True,'balance_changed':False,'real_debit':False}
            _receipt(c,a,payload,'quarantined','event_id_payload_conflict',now)
            return {'accepted':False,'quarantined':True,'reason':'event_id_payload_conflict','real_debit':False}
        current=_event_state(c,a)['snapshot']
        if current and payload['sequence']<=current['sequence']:
            disposition='stale' if payload['sequence']<current['sequence'] else 'quarantined'
            reason='older_provider_snapshot' if disposition=='stale' else 'provider_sequence_conflict'
            _receipt(c,a,payload,disposition,reason,now)
            return {'accepted':disposition=='stale','stale':disposition=='stale','quarantined':disposition=='quarantined','balance_changed':False,'real_debit':False}
        old=current or {'gross_cents':0,'refunded_cents':0,'reversed_cents':0,'status':'pending'}
        if any(payload[k]<old[k] for k in ('gross_cents','refunded_cents','reversed_cents')) or (old['status']!='pending' and payload['gross_cents']!=old['gross_cents']) or (old['status']!='pending' and payload['status']!=old['status'] and payload['status'] in ('pending','failed','partially_collected')):
            _receipt(c,a,payload,'quarantined','invalid_terminal_or_cumulative_transition',now)
            return {'accepted':False,'quarantined':True,'reason':'invalid_terminal_or_cumulative_transition','real_debit':False}
        deltas={k:payload[k]-old[k] for k in ('gross_cents','refunded_cents','reversed_cents')}
        bill=c.execute('SELECT * FROM billing_bills WHERE id=?',(a['bill_id'],)).fetchone();balance=_bill_state(c,bill)
        new_retained=balance['collected_cents']+deltas['gross_cents']-deltas['refunded_cents']-deltas['reversed_cents']
        if not 0<=new_retained<=bill['amount_cents']:
            _receipt(c,a,payload,'quarantined','would_overcollect_or_overreturn',now)
            return {'accepted':False,'quarantined':True,'reason':'would_overcollect_or_overreturn','real_debit':False}
        rid,_=_receipt(c,a,payload,'applied','validated_cumulative_mock_snapshot',now)
        for field,kind,sign in [('gross_cents','collection',-1),('refunded_cents','refund',1),('reversed_cents','compensation',1)]:
            if deltas[field]:_post(c,p,bill,kind,sign*deltas[field],kind+':'+rid,now,a,rid)
        c.audit(p['id'],'mock_collection_reconciled',{'attempt_id':a['id'],'event_receipt_id':rid,'real_debit':False},iso(now))
        return {'accepted':True,'duplicate':False,'balance_changed':any(deltas.values()),'status':payload['status'],'real_debit':False}


def reconcile(stall,term_id,attempt_id,repository=None,*,provider=None,now=None):
    repo=repository or configured_repository();provider=provider or MockCollectionProvider(repo)
    if provider.name!=PROVIDER:raise ValueError('Only the deterministic mock is enabled.')
    with repo.transaction() as c:_attempt(c,life.term_context(c,stall,term_id=term_id),attempt_id)
    envelope=provider.status(attempt_id)
    if envelope is None:return {'accepted':False,'status':'uncertain','reason':'No definitive mock provider snapshot; reservation retained.','real_debit':False}
    return ingest_event(stall,term_id,attempt_id,envelope['payload'],envelope['signature'],repo,now=now)


def request_refund(stall,term_id,attempt_id,actor,key,repository=None,*,now=None):
    _key(key);repo=repository or configured_repository();now=now or utcnow()
    with repo.transaction() as c:
        p=life.term_context(c,stall,term_id=term_id);a=_attempt(c,p,attempt_id)
        who=c.execute('SELECT role,active FROM auth_principals WHERE id=?',(actor,)).fetchone()
        if not who or who['role']!='reviewer' or not who['active']:raise ValueError('Active reviewer required for explicit mock-only refund bookkeeping.')
        old=c.execute('SELECT * FROM billing_refund_requests WHERE attempt_id=? AND idempotency_key=?',(attempt_id,key)).fetchone()
        if old:request=dict(old)
        else:
            state=_event_state(c,a);snapshot=state['snapshot']
            amount=snapshot['gross_cents']-snapshot['refunded_cents']-snapshot['reversed_cents'] if snapshot else 0
            if not state['terminal'] or amount<=0:raise ValueError('Only confirmed retained mock collection may be explicitly returned; no customer refund entitlement is implied.')
            request={'id':entity_id('MOCK-REFUND',attempt_id+'|'+key),'attempt_id':attempt_id,'actor_id':actor,'amount_cents':amount,'idempotency_key':key,'recorded_at':iso(now)}
            c.execute('INSERT INTO billing_refund_requests VALUES (?,?,?,?,?,?)',tuple(request.values()))
            c.audit(p['id'],'mock_refund_explicitly_authorized',{'request_id':request['id'],'actor_id':actor,'real_refund':False},iso(now))
    envelope=MockCollectionProvider(repo).refund(request)
    return ingest_event(stall,term_id,attempt_id,envelope['payload'],envelope['signature'],repo,now=now) | {'refund_request_id':request['id'],'refund_eligibility':'not_specified_mock_bookkeeping_only'}


def cost_scenarios(success_fee_cents=20,failure_fee_cents=100,failure_rate=Decimal('0.05'),monthly_net_income_assumptions_cents=(50000,100000,150000)):
    """Illustrative collection costs, not live fees, affordability findings or risk pricing."""
    if type(success_fee_cents) is not int or type(failure_fee_cents) is not int or min(success_fee_cents,failure_fee_cents)<0:raise ValueError('Use nonnegative integer-cent fee assumptions.')
    probability=Decimal(str(failure_rate))
    if not probability.is_finite() or not 0<=probability<=1:raise ValueError('Failure probability must be 0–1.')
    result={}
    for name,count in [('selected_monthly',12),('unselected_weekly_comparison',52)]:
        cost=Decimal(count)*success_fee_cents+Decimal(count)*probability*failure_fee_cents
        result[name]={'attempted_successful_instalments':count,'expected_collection_cost_cents':str(cost),
                      'annual_premium_cents':10400,'premium_remaining_before_claims_other_costs_cents':str(Decimal(10400)-cost)}
    affordability=[]
    for income in monthly_net_income_assumptions_cents:
        if type(income) is not int or income<=0:raise ValueError('Hypothetical monthly net income must be positive integer cents.')
        affordability.append({'monthly_net_income_assumption_cents':income,'annual_premium_share_percent':str(Decimal(10400)*100/(Decimal(income)*12)),
                              'basis':'hypothetical_net_income_not_digital_sales','customer_income_verified':False})
    return {'hypothetical_affordability_scenarios':affordability,'assumptions':{'successful_fee_cents':success_fee_cents,'failed_fee_cents':failure_fee_cents,'one_additional_failure_probability':str(probability)},
            'scenarios':result,'actual_fee_quote_verified':False,'risk_premium_recalculated':False,'income_affordability_verified':False,
            'note':'Illustrative fee sensitivity only. Digital sales are not total revenue or net income; no transaction sharing or subsidy is required/created.'}
