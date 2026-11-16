"""Pilot facade over SQLite/Postgres unit-of-work; all settlement remains simulated."""
import json
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo
from .ledger_repository import configured_repository, cents, sgd, period_id
from .pilot import decide
from .contracts import M1_VERSION, simulation_contract, validate_snapshot
from .policy_year import policy_year_bounds
from .integration import PILOT_NAMESPACE, DECISION_AUTHORITY, SETTLEMENT_AUTHORITY, SIMULATION_POLICY_STATE


def today_sgt():
    return datetime.now(ZoneInfo('Asia/Singapore')).date()


@contextmanager
def connection():
    with configured_repository().transaction() as unit:
        yield unit


def _policy(c, stall):
    row = c.lock_policy(stall)
    if row is None:
        raise LookupError('Accept the demo contract before simulating coverage.')
    policy_row = dict(row)
    snapshot = json.loads(policy_row['contract'])
    policy_row['_registered'] = validate_snapshot(snapshot)
    if policy_row['version_id'] != policy_row['_registered'].version or policy_row['contract_sha256'] != policy_row['_registered'].sha256:
        raise ValueError('Policy version metadata differs from accepted terms.')
    policy_row['_snapshot'] = snapshot
    return policy_row


def _scope(p):
    entry = p['_registered']
    return {'product_version_id': entry.version, 'contract_sha256': entry.sha256,
            'contract_stage': entry.lifecycle, 'policy_state': SIMULATION_POLICY_STATE,
            'identity_namespace': 'engine_local' if p.get('identity_namespace') == 'engine_local' else PILOT_NAMESPACE, 'decision_authority': DECISION_AUTHORITY,
            'settlement_authority': SETTLEMENT_AUTHORITY, 'real_policy_issued': False,
            'policy_period_id': p['period_id'], 'currency': 'SGD',
            'centre_id': p['centre_id'], 'merchant_id': p['merchant_id'], 'operator_id': p['operator_id'], 'stall_entity_id': p['stall_entity_id']}


def enrol(stall, start, gauge, region, version=M1_VERSION):
    entry = simulation_contract(version)
    with connection() as c:
        if c.backend == 'postgres':
            c.execute('SELECT pg_advisory_xact_lock(hashtext(?))', ('pilot-enrol:'+stall,))
        old = c.execute('SELECT * FROM pilot_policies WHERE stall_id=?', (stall,)).fetchone()
        if old:
            accepted = _policy(c, stall)
            if accepted['_registered'].version != entry.version or old['start'] != start.isoformat():
                raise ValueError('An enrolled term cannot be overwritten; renewal is not automatic.')
        else:
            _, end = policy_year_bounds(start, start)
            c.create_policy({'id':'SIM-POL-'+uuid.uuid4().hex, 'stall_id':stall,
                'start':start.isoformat(), 'end':end.isoformat(),
                'contract':json.dumps({**entry.terms,'assigned_gauge':gauge,'psi_region':region,'contract_sha256':entry.sha256},sort_keys=True),
                'accepted_at':datetime.now(ZoneInfo('Asia/Singapore')).isoformat()})
    return policy(stall)


def _used(c, policy_id):
    return c.used(period_id(policy_id, c.execute('SELECT start FROM pilot_policies WHERE id=?', (policy_id,)).fetchone()['start']))


def policy(stall):
    with connection() as c:
        p = _policy(c, stall)
        from . import policy_lifecycle as life
        terms=c.execute('SELECT id FROM engine_terms WHERE policy_id=? AND start<=? ORDER BY start DESC',(p['id'],str(today_sgt()))).fetchall()
        if terms:
            context=life.term_context(c,stall,term_id=terms[0]['id'])
            p={**context,'_snapshot':json.loads(context['contract']),'_registered':validate_snapshot(json.loads(context['contract']))}
        lifecycle_state=life.state(c,p,today_sgt()) if 'term_id' in p else 'ENROLLED_SIMULATION'
        used = c.used(p['period_id'])
        canceled=bool(c.execute("SELECT id FROM engine_lifecycle_events WHERE policy_id=? AND action='cancel_simulation' AND effective_on<=?",(p['id'],str(today_sgt()))).fetchone())
        mock_billing=None
        if p.get('term_id') and c.execute('SELECT version FROM pilot_schema_migrations WHERE version=6').fetchone() and c.execute('SELECT id FROM billing_schedules WHERE term_id=?',(p['term_id'],)).fetchone():
            from .billing import _statement
            try:
                statement=_statement(c,p,today_sgt())
                mock_billing={'summary':statement['summary'],'authorization':statement['authorization'],'review_required':statement['review_required'],'mode':'mock_billing_only','real_collected_cents':0}
            except ValueError:
                mock_billing={'status':'REVIEW_REQUIRED','mode':'mock_billing_only','real_collected_cents':0}
    contract, entry = p['_snapshot'], p['_registered']
    r = entry.rules()
    return {'policy_id': p['id'], 'stall_id': stall, 'status': 'DEMO_CANCELED' if canceled else 'DEMO_ACTIVE' if p['start'] <= today_sgt().isoformat() <= p['end'] else 'DEMO_INACTIVE',
            **_scope(p), 'simulation_lifecycle_state':lifecycle_state, 'term_id':p.get('term_id'), 'policy_start': p['start'], 'policy_end': p['end'], 'rule_version': contract['version'],
            'simulated': True, 'contract': contract, 'weekly_premium_sgd': contract['weekly_equivalent_sgd'],
            'annual_rain_events_paid': used['rain'], 'annual_haze_days_paid': used['haze_days'],
            'annual_haze_paid_sgd': used['haze_sgd'], 'max_rain_events': r.rain_cap_days_per_year, 'max_haze_days': r.haze_cap_days_per_year,
            'max_haze_amount_sgd': r.haze_cap_amount_per_year, 'remaining_rain_events': r.rain_cap_days_per_year-used['rain'],
            'remaining_haze_days': r.haze_cap_days_per_year-used['haze_days'], 'remaining_haze_sgd': r.haze_cap_amount_per_year-used['haze_sgd'],
            'remaining_combined_sgd': contract['combined_cap_sgd']-used['total'],
            'billing': {'annual_premium_sgd': contract['annual_premium_sgd'], 'instalments_cents': contract['instalments_cents'],
                        'collected_sgd': 0, 'outstanding_sgd': contract['annual_premium_sgd'], 'status': 'SIMULATION_NOT_COLLECTED',
                        'real_mandate_connected':False, 'mock_billing':mock_billing}}


def simulate(stall, day, peril, rain, psi, yesterday, closed, gauge, region, requested_version=None):
    with connection() as c:
        p = _policy(c, stall)
        entry = p['_registered']
        from .policy_lifecycle import ensure_mode
        ensure_mode(c,p,'synthetic_demo')
        if c.execute("SELECT id FROM engine_lifecycle_events WHERE policy_id=? AND action='cancel_simulation' AND effective_on<=?",(p['id'],str(day))).fetchone():
            raise ValueError('Simulation canceled from this event date.')
        if requested_version is not None and requested_version != entry.version:
            raise ValueError('Requested version differs from the accepted policy version.')
        if not p['start'] <= day.isoformat() <= p['end']:
            raise ValueError('Event date is outside the enrolled term; no automatic renewal.')
        old = c.execute('SELECT response FROM pilot_decisions WHERE policy_id=? AND day=? AND peril=?', (p['id'], str(day), peril)).fetchone()
        if old and json.loads(old['response'])['status'] != 'PENDING':
            return {**json.loads(old['response']), **_scope(p), 'duplicate': True, 'disbursed': False, 'message': 'Already recorded: no additional simulated payment.'}
        # Prevent cap allocation from changing when out-of-order payable events arrive.
        later = c.execute('SELECT 1 FROM pilot_decisions WHERE policy_id=? AND day>? AND amount>0', (p['id'], str(day))).fetchone()
        if later:
            raise ValueError('Earlier event needs ordered replay/reconciliation; simulation accepts chronological events only.')
        locked = p['_snapshot']
        gauge, region = locked['assigned_gauge'], locked['psi_region']
        state, amount, reason = decide(peril, rain, psi, yesterday, closed, _used(c, p['id']), version=entry.version)
        claim = 'SIM-' + uuid.uuid5(uuid.NAMESPACE_URL, f"{p['id']}|{day}|{peril}").hex
        evidence = {'daily_rain_mm': rain, 'psi_today': psi, 'psi_yesterday': yesterday,
                    'gauge': gauge, 'region': region, 'source': 'synthetic_demo', 'event_date_sgt': str(day)}
        response = {'status': state, 'simulated': True, 'disbursed': amount > 0, 'duplicate': False,
                    'claim_id': claim, 'amount': amount, 'reference_number': claim + '-REF',
                    'message': reason, 'weather_proof': 'SIMULATED: ' + reason, 'reason': reason,
                    'evidence': evidence, 'policy_id': p['id'], 'rule_version': entry.version, **_scope(p),
                    'policy_period_start': p['start'], 'policy_period_end': p['end'],
                    'settlement_rail': 'Simulated only. No money sent or partner connected.',
                    'timestamp': datetime.now(ZoneInfo('Asia/Singapore')).isoformat()}
        c.post_decision(p, day, peril, response)
    return response


def history(stall):
    with connection() as c:
        p = _policy(c, stall)
        rows = c.execute('SELECT response,peril FROM pilot_decisions WHERE policy_id=? ORDER BY day,peril', (p['id'],)).fetchall()
        reconciliation = _reconciliation(c,p)
        reviewed_net=sum(r['amount_cents'] for r in c.execute('SELECT amount_cents FROM engine_entitlement_entries WHERE policy_id=?',(p['id'],)).fetchall())
        mock_settlement={'payment_execution':'NOT_SUBMITTED','real_paid_cents':0}
        if c.execute('SELECT version FROM pilot_schema_migrations WHERE version=7').fetchone():
            from .settlement import policy_summary_in_unit
            mock_settlement=policy_summary_in_unit(c,p['id'])
    decisions = [{**json.loads(r['response']), **_scope(p), 'id': json.loads(r['response'])['claim_id'], 'event_type': r['peril']} for r in rows]
    claims = [r for r in decisions if r['amount'] > 0]
    return {'stall_id': stall, **_scope(p), 'simulated': True, 'total_disbursed': sum(r['amount'] for r in claims),
            'claims_count': len(claims), 'claims': claims, 'decisions': decisions, 'reconciliation': reconciliation,
            'reviewed_evidence_entitlements':{'net_entitlement_cents':reviewed_net,'payment_execution':mock_settlement['payment_execution'],'mock_settlement':mock_settlement,'disbursed_sgd':0}}


def _reconciliation(c, p):
    entries = c.execute('SELECT kind,amount_cents FROM pilot_financial_entries WHERE policy_id=?', (p['id'],)).fetchall()
    allocated = sum(e['amount_cents'] for e in entries if e['kind']=='allocation')
    settled = -sum(e['amount_cents'] for e in entries if e['kind']=='simulated_settlement')
    compensated = sum(e['amount_cents'] for e in entries if e['kind']=='compensation')
    decisions = c.execute('SELECT amount_cents FROM pilot_decisions WHERE policy_id=?', (p['id'],)).fetchall()
    instructions = c.execute('SELECT amount_cents FROM pilot_instructions WHERE policy_id=?', (p['id'],)).fetchall()
    issues=[]
    if allocated != sum(d['amount_cents'] for d in decisions):
        issues.append('Decision allocations do not reconcile.')
    if allocated != sum(i['amount_cents'] for i in instructions):
        issues.append('Instructions do not reconcile to entitlement.')
    if settled != allocated:
        issues.append('Simulated postings do not reconcile to allocation.')
    return {'policy_id':p['id'],'currency':'SGD','mode':'simulation_only',
            'allocated_cents':allocated,'simulated_settled_cents':settled,'compensated_cents':compensated,
            'outstanding_simulated_cents':allocated-settled+compensated,
            'status':'review_required' if issues or compensated else 'balanced','issues':issues}


def reconcile(stall):
    with connection() as c:
        return _reconciliation(c,_policy(c,stall))


def compensate_simulation(stall, entry_id, reason, idempotency_key):
    """Internal correction only, not an HTTP operation or permission to retry a rail.

    Append an opposite entry for a simulated settlement. Preserve the original
    decision, receipt and cap allocation; real settlement/review is a later phase.
    """
    if not reason or not reason.strip() or not idempotency_key:
        raise ValueError('A correction needs a reason and idempotency key.')
    with connection() as c:
        p=_policy(c,stall)
        key='compensation:'+idempotency_key
        existing=c.execute('SELECT * FROM pilot_financial_entries WHERE idempotency_key=?',(key,)).fetchone()
        if existing:
            if existing['policy_id']!=p['id'] or existing['reverses_entry_id']!=entry_id or existing['reason']!=reason:
                raise ValueError('Conflicting correction request.')
            return existing['id']
        original=c.execute("SELECT * FROM pilot_financial_entries WHERE id=? AND policy_id=? AND kind='simulated_settlement'",(entry_id,p['id'])).fetchone()
        if not original:
            raise ValueError('Only a policy-owned simulated settlement may be compensated.')
        if c.execute('SELECT id FROM pilot_financial_entries WHERE reverses_entry_id=?',(entry_id,)).fetchone():
            raise ValueError('Settlement already compensated; reconcile before further correction.')
        identifier='SIM-CORRECTION-'+uuid.uuid4().hex
        timestamp=datetime.now(ZoneInfo('Asia/Singapore')).isoformat()
        c.execute('INSERT INTO pilot_financial_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (identifier,p['id'],p['period_id'],original['decision_id'],original['peril'],'compensation',-original['amount_cents'],'SGD',entry_id,key,reason,timestamp))
        c.audit(p['id'],'simulation_compensated',{'entry_id':identifier,'reverses':entry_id,'reason':reason},timestamp)
        return identifier
