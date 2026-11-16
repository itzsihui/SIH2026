"""Versioned Part 1 projections over canonical ledgers; no financial writes."""
from contextlib import contextmanager
import json

from fastapi import HTTPException
from . import auth, billing, daily_evidence as daily, policy_lifecycle as life, settlement
from .ledger_repository import configured_repository, cents
from .weather_ingestion import utcnow, iso, source_health
from .ingestion import SGT

VERSION = 'daycover.part2.v1'


class _SameTransaction:
    """Reuse one policy-locked transaction for existing canonical projections."""
    def __init__(self, unit): self.unit = unit

    @contextmanager
    def transaction(self): yield self.unit


def terms(stall, principal, repository=None, *, now=None):
    now = now or utcnow()
    auth.require_scope(principal, 'coverage:read')
    with (repository or configured_repository()).transaction() as c:
        auth.stall_access(c, principal, stall)
        view = life.overview(stall, _SameTransaction(c), as_of=now.astimezone(SGT).date())
        return {'schema_version': VERSION, 'generated_at': iso(now), **view}


def _reviews(c, evidence):
    result = []
    for key in ('rain', 'psi_today', 'psi_yesterday'):
        aggregate = evidence[key].get('aggregate_id')
        if aggregate:
            result.extend(dict(r) for r in c.execute('SELECT id,result_aggregate_id,decision,reviewer_id,source_ref,recorded_at FROM weather_daily_reviews WHERE result_aggregate_id=? ORDER BY sequence', (aggregate,)).fetchall())
        mapping = evidence[key].get('mapping_review_id')
        if mapping:
            result.extend(dict(r) for r in c.execute('SELECT id,station_version_id,valid_from,valid_until,decision,reviewer_id,source_ref,recorded_at FROM weather_mapping_reviews WHERE id=?', (mapping,)).fetchall())
        for revision in evidence[key].get('revision_review_ids', []):
            result.extend(dict(r) for r in c.execute('SELECT id,selected_observation_id,revision_set_sha256,reviewer_id,source_ref,recorded_at FROM weather_revision_reviews WHERE id=?', (revision,)).fetchall())
    closure = evidence['closure'].get('closure_id')
    if closure:
        result.extend(dict(r) for r in c.execute('SELECT id,closure_id,decision,reviewer_id,source_ref,recorded_at FROM weather_closure_reviews WHERE closure_id=? ORDER BY sequence', (closure,)).fetchall())
    return list({r["id"]:r for r in result}.values())


def snapshot(stall, term_id, day, principal, repository=None, *, now=None, operations=False):
    now = now or utcnow()
    auth.require_scope(principal, 'coverage:read')
    if operations and principal.role not in ('operator', 'reviewer', 'service'):
        raise HTTPException(403, 'Operator, reviewer or service role required.')
    with (repository or configured_repository()).transaction() as c:
        merchant = auth.stall_access(c, principal, stall)
        p = life.term_context(c, stall, term_id=term_id)
        # Acquire current source locks before projecting any financial state. Every
        # component below uses this same transaction, including source rechecks.
        evidence = daily.select_in_unit(c, stall, day, now=now, persist=False, policy_context=p)
        contract = json.loads(p['contract']); rules = contract['rules']; used = c.used(p['period_id'])
        remaining = {'rain_events': max(0, rules['rain_cap_days_per_year'] - used['rain']),
                     'rain_cents': max(0, rules['rain_cap_days_per_year'] - used['rain']) * cents(rules['rain_payout']),
                     'haze_days': max(0, rules['haze_cap_days_per_year'] - used['haze_days']),
                     'haze_cents': max(0, cents(rules['haze_cap_amount_per_year']) - cents(used['haze_sgd'])),
                     'combined_cents': max(0, cents(contract['combined_cap_sgd']) - cents(used['total']))}
        rows = c.execute('SELECT id,day,peril,payload FROM engine_decisions WHERE term_id=? ORDER BY sequence', (term_id,)).fetchall()
        latest = {(r['day'], r['peril']): json.loads(r['payload']) for r in rows}
        decisions = []
        for peril in ('rain', 'haze'):
            decision = latest.get((str(day), peril))
            if decision:
                decision = dict(decision)
                # Historical payloads intentionally retain original write-time facts.
                # Current settlement state is authoritative only in settlement below.
                decision['historical_snapshot'] = True
                current_hash = daily.digest({'term':term_id, 'period':p['period_id'], 'contract':p['contract_sha256'],
                                             'selection':evidence['fingerprint'], 'lifecycle_state':life.state(c,p,day)})
                decision['current_context_matches'] = decision['context_sha256'] == current_hash
                decision['display_message'] = decision['reason']
            else:
                decision = {'day':str(day), 'peril':peril, 'status':'NOT_EVALUATED', 'effect':None,
                            'decision_id':None, 'current_context_matches':False,
                            'display_message':'No engine decision has been recorded. Reading this view does not evaluate or pay an event.'}
            decisions.append(decision)
        bill = billing._statement(c, p, now.astimezone(SGT).date())
        payout = settlement.overview(stall, term_id, _SameTransaction(c), now=now)
        receipts = [dict(r) for r in c.execute('''SELECT e.id,e.instruction_id,e.event_id,e.provider_sequence,e.disposition,e.reason,e.recorded_at,e.payload
            FROM settlement_provider_events e JOIN settlement_instructions i ON i.id=e.instruction_id
            WHERE i.term_id=? AND e.disposition IN ('applied','stale') ORDER BY e.recorded_at DESC,e.id DESC LIMIT 101''', (term_id,)).fetchall()]
        for receipt in receipts: receipt['payload'] = json.loads(receipt['payload'])
        onboard = c.execute('SELECT centre_ref,external_namespace FROM auth_onboarding WHERE stall_id=?', (stall,)).fetchone()
        view = {'schema_version':VERSION, 'generated_at':iso(now), 'as_of_day':str(day), 'currency':'SGD', 'timezone':'Asia/Singapore',
                'identity':{'stall_id':stall, 'merchant_id':merchant, 'operator_id':p['operator_id'], 'stall_entity_id':p['stall_entity_id'],
                            'centre_id':p['centre_id'], 'centre_ref':onboard['centre_ref'] if onboard else stall,
                            'mapping_namespace':onboard['external_namespace'] if onboard else 'pilot_demo', 'identity_verified':False},
                'policy':{'policy_id':p['id'], 'term_id':term_id, 'period_id':p['period_id'], 'accepted_version':p['version_id'],
                          'contract_sha256':p['contract_sha256'], 'accepted_at':p['accepted_at'], 'start':p['start'], 'end':p['end'],
                          'state':life.state(c,p,now.astimezone(SGT).date()), 'event_day_state':life.state(c,p,day), 'terms':contract},
                'coverage':{'used':used, 'remaining':remaining, 'explanation':'Benefit caps are consumed by accepted allocations, not payment confirmations; reversals do not restore them.'},
                'weather':evidence, 'source_health':source_health(_SameTransaction(c), now=now), 'source_reviews':_reviews(c,evidence), 'decisions':decisions, 'billing':bill, 'settlement':payout,
                'receipts':receipts[:100], 'receipts_truncated':len(receipts)>100,
                'boundaries':{'mode':'simulation_only', 'real_policy_issued':False, 'real_collected_cents':0, 'real_paid_cents':0,
                              'external_wallet_bridge':False, 'rain_timing_verified':daily.RAIN_TIMING_VERIFIED, 'ml_sales_scope':'digital_only',
                              'message':'Entitlements and submissions are not real payments. All provider outcomes here are local mock simulations.'}}
        if operations:
            view['operations'] = {
                'source_gaps':[{'source':k, 'status':evidence[k]['status'], 'blocking_reasons':evidence[k].get('blocking_reasons',[])}
                               for k in ('rain','psi_today','psi_yesterday') if not evidence[k].get('eligible_for_phase6')],
                'not_evaluated_perils':[d['peril'] for d in decisions if d['status']=='NOT_EVALUATED'],
                'pending_decisions':[d for d in latest.values() if d['status']=='PENDING' or d['effect']!='accepted'],
                'settlement_queue':payout['outbox'],
                'reconciliation_queue':[i for i in payout['instructions'] if i['status'] in ('queued','submitted','uncertain','pending')],
                'review_required':bool(bill['review_required'] or payout['review_required']),
                'quarantined_callbacks':{'billing':bill['quarantined_callbacks'],'settlement':payout['quarantined_callbacks']},
                'replay_reviews':[dict(r) for r in c.execute('''SELECT r.id,r.plan_id,r.actor_id,r.source_ref,r.recorded_at
                   FROM engine_replay_reviews r JOIN engine_replay_plans p ON p.id=r.plan_id WHERE p.term_id=? ORDER BY r.recorded_at,r.id''',(term_id,)).fetchall()],
                'lifecycle_events':[dict(r) for r in c.execute('SELECT id,action,effective_on,actor_id,reason,recorded_at FROM engine_lifecycle_events WHERE policy_id=? ORDER BY sequence',(p['id'],)).fetchall()],
                'recipient_reviews':[dict(r) for r in c.execute('SELECT v.id,v.recipient_id,v.actor_id,v.decision,v.source_ref,v.recorded_at FROM settlement_recipient_reviews v JOIN settlement_recipients r ON r.id=v.recipient_id WHERE r.merchant_id=? ORDER BY v.sequence',(merchant,)).fetchall()],
                'review_actions':'Read-only projection. Use separately scoped review endpoints or trusted evidence CLI; no write permission is implied.'}
        view['state_sha256'] = daily.digest({k:v for k,v in view.items() if k!='generated_at'})
        return view
