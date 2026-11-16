"""Explicit local simulation terms/events; no insurance issuance or inferred billing rules."""
from datetime import date, timedelta
import json
import uuid

from .contracts import canonical_json, simulation_contract, validate_snapshot
from .ledger_repository import configured_repository, period_id, cents
from .policy_year import anniversary
from .weather_ingestion import utcnow, iso
from .ingestion import SGT


def initial_term(c,p):
    """Called only after schema v5 is available; old migration/import paths stay valid."""
    c.execute('''INSERT INTO engine_terms VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING''',
              ('SIM-TERM-'+period_id(p['id'],p['start']),p['id'],period_id(p['id'],p['start']),json.loads(p['contract'])['version'],
               p['start'],p['end'],p['contract'],validate_snapshot(json.loads(p['contract'])).sha256,p['accepted_at']))


def root(c,stall):
    p=c.lock_policy(stall);entry=validate_snapshot(json.loads(p['contract']))
    if entry.version!=p['version_id'] or entry.sha256!=p['contract_sha256']:raise ValueError('Accepted contract metadata differs.')
    return p


def term_context(c,stall,day=None,term_id=None):
    p=root(c,stall)
    if term_id:
        t=c.execute('SELECT * FROM engine_terms WHERE id=? AND policy_id=?',(term_id,p['id'])).fetchone()
    elif day:
        t=c.execute('SELECT * FROM engine_terms WHERE policy_id=? AND start<=? AND "end">=?',(p['id'],str(day),str(day))).fetchone()
    else:
        t=c.execute('SELECT * FROM engine_terms WHERE policy_id=? ORDER BY start DESC LIMIT 1',(p['id'],)).fetchone()
    if not t:raise LookupError('No explicitly accepted term covers this selection.')
    entry=validate_snapshot(json.loads(t['contract']))
    period=c.execute('SELECT * FROM pilot_periods WHERE id=?',(t['period_id'],)).fetchone()
    expected_period=period_id(p['id'],t['start'])
    expected_end=anniversary(date.fromisoformat(p['start']),date.fromisoformat(t['start']).year+1)-timedelta(days=1)
    if entry.version!=t['version_id'] or entry.sha256!=t['contract_sha256'] or not period or period['id']!=expected_period or period['version_id']!=t['version_id'] or t['id']!='SIM-TERM-'+expected_period or t['end']!=str(expected_end) or period['policy_id']!=p['id'] or period['start']!=t['start'] or period['end']!=t['end'] or period['combined_cap_cents']!=cents(entry.terms['combined_cap_sgd']):
        raise ValueError('Term/period differs from its accepted version.')
    return {**p,**{k:t[k] for k in ('period_id','version_id','start','end','contract','contract_sha256','accepted_at')},'term_id':t['id']}


def state(c,p,day):
    canceled=c.execute("SELECT effective_on FROM engine_lifecycle_events WHERE policy_id=? AND action='cancel_simulation' AND effective_on<=? ORDER BY effective_on LIMIT 1",(p['id'],str(day))).fetchone()
    if canceled:return 'CANCELED_SIMULATION'
    if str(day)<p['start']:return 'NOT_STARTED'
    if str(day)>p['end']:return 'EXPIRED'
    active=c.execute("SELECT id FROM engine_lifecycle_events WHERE term_id=? AND action='activate_simulation' AND effective_on<=?",(p['term_id'],str(day))).fetchone()
    return 'ACTIVE_SIMULATION' if active else 'ENROLLED_SIMULATION'


def ensure_mode(c,p,mode):
    row=c.execute('SELECT mode FROM engine_period_modes WHERE period_id=?',(p['period_id'],)).fetchone()
    if row and row['mode']!=mode:raise ValueError('Synthetic and reviewed-evidence decisions cannot share one period; use an explicit new term.')
    c.execute('INSERT INTO engine_period_modes VALUES (?,?) ON CONFLICT DO NOTHING',(p['period_id'],mode))


def overview(stall,repository=None,*,as_of=None):
    as_of=as_of or utcnow().astimezone(SGT).date()
    with (repository or configured_repository()).transaction() as c:
        p=root(c,stall)
        terms=c.execute('SELECT id FROM engine_terms WHERE policy_id=? ORDER BY start',(p['id'],)).fetchall()
        result=[]
        for row in terms:
            context=term_context(c,stall,term_id=row['id'])
            result.append({'term_id':context['term_id'],'period_id':context['period_id'],'start':context['start'],'end':context['end'],
                           'accepted_version':context['version_id'],'contract_sha256':context['contract_sha256'],'state':state(c,context,as_of),
                           'used':c.used(context['period_id']),'contract':json.loads(context['contract'])})
        events=[dict(r) for r in c.execute('SELECT * FROM engine_lifecycle_events WHERE policy_id=? ORDER BY sequence',(p['id'],)).fetchall()]
        return {'stall_id':stall,'policy_id':p['id'],'as_of':str(as_of),'terms':result,'events':events,'mode':'simulation_only',
                'real_policy_issued':False,'waiting_period':'not_specified_not_invented','refund_grace_endorsement_rules':'not_specified','real_settlement_supported':False}


def renew(stall,start,version,repository=None,*,now=None):
    now=now or utcnow()
    try:entry=simulation_contract(version)
    except (LookupError,ValueError) as exc:raise ValueError('Unsupported accepted simulation version.') from exc
    with (repository or configured_repository()).transaction() as c:
        p=root(c,stall)
        if c.execute("SELECT id FROM engine_lifecycle_events WHERE policy_id=? AND action='cancel_simulation'",(p['id'],)).fetchone():raise ValueError('Canceled simulations need a separately reviewed new enrolment; renewal is disabled.')
        existing=c.execute('SELECT * FROM engine_terms WHERE policy_id=? AND start=?',(p['id'],str(start))).fetchone()
        if existing:
            if existing['version_id']!=version:raise ValueError('An accepted renewal cannot be overwritten.')
            return {'term_id':existing['id'],'duplicate':True,'real_policy_issued':False}
        latest=c.execute('SELECT * FROM engine_terms WHERE policy_id=? ORDER BY start DESC LIMIT 1',(p['id'],)).fetchone()
        inception=date.fromisoformat(p['start'])
        expected=date.fromisoformat(latest['end'])+timedelta(days=1)
        if start!=expected:raise ValueError('Renewal must explicitly accept the next anniversary term; gaps/overlap are not inferred.')
        onboarding=c.execute('SELECT status,accepted_version FROM auth_onboarding WHERE stall_id=?',(stall,)).fetchone()
        if onboarding and (onboarding['status']!='eligible_simulation' or onboarding['accepted_version']!=version):raise ValueError('Current matching local eligibility review required.')
        end=anniversary(inception,start.year+1)-timedelta(days=1)
        contract=canonical_json({**entry.terms,'assigned_gauge':json.loads(latest['contract'])['assigned_gauge'],'psi_region':json.loads(latest['contract'])['psi_region'],'contract_sha256':entry.sha256})
        period=period_id(p['id'],str(start));tid='SIM-TERM-'+period
        c.execute('INSERT INTO pilot_periods VALUES (?,?,?,?,?,?,?)',(period,p['id'],version,str(start),str(end),'SGD',cents(entry.terms['combined_cap_sgd'])))
        c.execute('INSERT INTO engine_terms VALUES (?,?,?,?,?,?,?,?,?)',(tid,p['id'],period,version,str(start),str(end),contract,entry.sha256,iso(now)))
        c.audit(p['id'],'simulation_renewal_accepted',{'term_id':tid,'version':version,'start':str(start),'end':str(end),'real_issuance':False},iso(now))
        return {'term_id':tid,'period_id':period,'start':str(start),'end':str(end),'duplicate':False,'state':'ENROLLED_SIMULATION','real_policy_issued':False}


def transition(stall,term_id,action,actor,effective_on=None,repository=None,*,now=None):
    now=now or utcnow()
    from .ingestion import SGT
    if action not in ('activate_simulation','cancel_simulation','record_expiry'):raise ValueError('Unsupported simulation lifecycle transition.')
    if action!='cancel_simulation' and effective_on is not None:raise ValueError('Activation uses accepted inception; expiry uses the next anniversary. Only cancellation accepts an effective date.')
    with (repository or configured_repository()).transaction() as c:
        p=term_context(c,stall,term_id=term_id)
        principal=c.execute('SELECT role,active FROM auth_principals WHERE id=?',(actor,)).fetchone()
        if not principal or principal['role']!='reviewer' or not principal['active']:raise ValueError('Active reviewer required for simulation lifecycle changes.')
        if action=='activate_simulation':
            effective=date.fromisoformat(p['start'])
            if c.execute("SELECT id FROM engine_lifecycle_events WHERE policy_id=? AND action='cancel_simulation'",(p['id'],)).fetchone():raise ValueError('Canceled simulation cannot be reactivated.')
            onboarding=c.execute('SELECT status FROM auth_onboarding WHERE stall_id=?',(stall,)).fetchone()
            if onboarding and onboarding['status']!='eligible_simulation':raise ValueError('Current local eligibility review required.')
        elif action=='cancel_simulation':
            effective=effective_on
            prior=c.execute("SELECT * FROM engine_lifecycle_events WHERE policy_id=? AND action='cancel_simulation'",(p['id'],)).fetchone()
            if prior:
                if prior['effective_on']!=str(effective):raise ValueError('Cancellation cannot be overwritten.')
                return {'event_id':prior['id'],'duplicate':True,'real_policy_issued':False}
            if type(effective) is not date or effective<now.astimezone(SGT).date() or not p['start']<=str(effective)<=p['end']:
                raise ValueError('Cancellation is prospective, inclusive from the chosen date, within its accepted term; backdating is not supported.')
        else:
            effective=date.fromisoformat(p['end'])+timedelta(days=1)
            if now.astimezone(SGT).date()<effective:raise ValueError('Term has not expired.')
        previous=c.execute('SELECT * FROM engine_lifecycle_events WHERE term_id=? AND action=?',(p['term_id'],action)).fetchone()
        if previous:return {'event_id':previous['id'],'duplicate':True,'real_policy_issued':False}
        eid='SIM-LIFECYCLE-'+uuid.uuid4().hex
        c.execute('''INSERT INTO engine_lifecycle_events (id,policy_id,term_id,action,effective_on,actor_id,reason,recorded_at) VALUES (?,?,?,?,?,?,?,?)''',
                  (eid,p['id'],p['term_id'],action,str(effective),actor,'local_'+action,iso(now)))
        c.audit(p['id'],action,{'event_id':eid,'term_id':p['term_id'],'effective_on':str(effective),'actor_id':actor},iso(now))
        return {'event_id':eid,'effective_on':str(effective),'duplicate':False,'real_policy_issued':False,'financial_effect':False}
