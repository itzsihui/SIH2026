"""Operator dashboard read model: policies, premium, entitlements, mock payouts and queues. Read-only, role-restricted."""
import json
from fastapi import APIRouter, Depends, HTTPException, Response
from .identity_api import principal
from .ledger_repository import configured_repository
from . import ops

router = APIRouter(prefix='/api/v1/dashboard', tags=['operator dashboard'])
VERSION = 'daycover.dashboard.v1'


def portfolio(repo=None) -> dict:
    repo = repo or configured_repository()
    with repo.transaction() as c:
        n = lambda q: c.execute(q).fetchone()['n']
        decisions = [json.loads(r['payload']) for r in c.execute('SELECT payload FROM engine_decisions').fetchall()]
        by_status = {}
        for d in decisions:
            by_status[d['status']] = by_status.get(d['status'], 0) + 1
        term_cap = c.execute('SELECT COUNT(*) n FROM engine_terms').fetchone()['n']
        out = {
            'schema_version': VERSION, 'mode': 'simulation_only',
            'policies': {'policies': n('SELECT COUNT(*) n FROM pilot_policies'), 'accepted_terms': term_cap,
                         'by_version': {r['version_id']: r['n'] for r in c.execute('SELECT version_id,COUNT(*) n FROM engine_terms GROUP BY version_id').fetchall()}},
            'premium_mock': {'annual_obligation_cents': n("SELECT COALESCE(SUM(b.amount_cents),0) n FROM billing_bills b"),
                             'mock_collected_cents': n("SELECT COALESCE(SUM(amount_cents),0) n FROM pilot_billing_entries WHERE kind='collection'"),
                             'failed_or_timeout_attempts': n("SELECT COUNT(*) n FROM billing_attempts WHERE scenario IN ('failed','timeout')"),
                             'real_collected_cents': 0},
            'decisions': {'by_status': by_status,
                          'net_entitlement_cents': n('SELECT COALESCE(SUM(amount_cents),0) n FROM engine_entitlement_entries')},
            'payouts_mock': {'instructions': n('SELECT COUNT(*) n FROM settlement_instructions'),
                             'confirmed_mock_cents': n("SELECT COALESCE(SUM(amount_cents),0) n FROM settlement_cash_entries"),
                             'real_paid_cents': 0},
            'queues': {'outbox_without_instruction': n('SELECT COUNT(*) n FROM settlement_outbox o WHERE NOT EXISTS (SELECT 1 FROM settlement_instructions i WHERE i.outbox_id=o.id)')},
            'rules_decide_ml_advises': True}
    out['alerts'] = [{k: a[k] for k in ('code', 'severity', 'count')} for a in ops.collect_alerts(repo)]
    return out


@router.get('/portfolio')
def get_portfolio(response: Response, p=Depends(ops.operator)):
    response.headers['Cache-Control'] = 'no-store'
    return portfolio()
