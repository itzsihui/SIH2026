"""Contract authority regressions: research and mutable defaults cannot rewrite M1."""
from dataclasses import replace
from datetime import date
import json

from fastapi.testclient import TestClient
import pytest

from src.daycover import api, contracts, pilot, pilot_store
from src.daycover.contracts import M1_VERSION, M1_SHA256

client = TestClient(api.app)
DAY = date(2026, 1, 2)


def enrol(**extra):
    return client.post('/api/v1/policies', json={
        'stall_id': 'HC001', 'start_date': '2025-12-15',
        'accepted_version': M1_VERSION, 'consent': True, **extra})


def simulate(**extra):
    return client.post('/api/v1/triggers/simulate', json={
        'stall_id': 'HC001', 'peril': 'RAIN_70MM', 'event_date': str(DAY), **extra})


def test_catalogue_separates_authority_and_exposes_conflicting_sources():
    catalogue = client.get('/api/v1/contracts').json()
    entries = {e['version']: e for e in catalogue['contracts']}
    assert catalogue['approved_for_real_issuance'] == []
    assert not catalogue['real_issuance_supported']
    assert [e['version'] for e in entries.values() if e['simulation_enrolment_allowed']] == [M1_VERSION]
    assert entries['wallet-sandbox-08fc23f']['summary']['runtime_config_mutable']
    assert '100 mm' in entries['wallet-sandbox-08fc23f']['summary']['rain']
    assert entries['candidate-plan4-150-proposal-v1']['lifecycle'] == 'candidate_proposal'
    detail = client.get('/api/v1/contracts/'+M1_VERSION).json()
    assert detail['contract_sha256'] == M1_SHA256
    assert detail['terms'] == client.get('/api/v1/contract').json()
    assert 'terms' not in client.get('/api/v1/contracts/wallet-sandbox-08fc23f').json()
    assert client.get('/api/v1/contracts/no-such-version').status_code == 404
    assert client.post('/api/v1/contracts/'+M1_VERSION, json={'lifecycle':'approved'}).status_code == 405


def test_explicit_quote_selection_and_legacy_alias_do_not_issue_policy():
    assert client.post('/api/v1/quotes', json={'stall_id':'HC001'}).status_code == 422
    q = client.post('/api/v1/quotes', json={'stall_id':'HC001','contract_version':M1_VERSION}).json()
    assert q['product_version_id'] == M1_VERSION and q['contract_stage'] == 'simulation'
    assert q['contract_sha256'] == M1_SHA256
    assert q['premium'] == 104 and q['rain']['mm_per_day'] == 70
    assert not q['legacy_default_applied'] and not q['policy_created'] and not q['real_policy_issued']
    assert client.get('/api/v1/policy/HC001').status_code == 404
    assert client.post('/quote', json={'stall_id':'HC001'}).json()['legacy_default_applied']


@pytest.mark.parametrize('version', ['wallet-sandbox-08fc23f', '2026.11-draft2',
    'train-2026.11-v1', 'legacy-engine-50mm-v1', 'candidate-plan4-150-proposal-v1', 'candidate-checkout-104-monthly-v1', 'unknown'])
def test_research_and_proposals_cannot_enrol_or_quote_as_pilot(version):
    assert enrol(accepted_version=version).status_code == 422
    assert client.post('/api/v1/quotes', json={'stall_id':'HC001','contract_version':version}).status_code == 422
    assert client.get('/api/v1/policy/HC001').status_code == 404


@pytest.mark.parametrize('override', [{'rain_mm':100}, {'rules':{'rain_daily_mm':100}},
    {'status':'approved'}, {'settlement':'paynow'}, {'policy_state':'issued_policy'}])
def test_extra_policy_override_fields_are_rejected(override):
    assert enrol(**override).status_code == 422
    assert client.post('/api/v1/quotes', json={'stall_id':'HC001','contract_version':M1_VERSION,**override}).status_code == 422


def test_request_version_cannot_replace_accepted_version(monkeypatch):
    monkeypatch.setattr(api._STALLS['HC001'], 'closures', set())
    enrol()
    assert simulate(contract_version='wallet-sandbox-08fc23f').status_code == 409
    assert simulate(rules={'rain_daily_mm':100}).status_code == 422
    assert simulate(contract_version=M1_VERSION, rain_daily_mm=70).json()['amount'] == 30


def test_research_override_and_global_mutation_do_not_change_policy_terms(monkeypatch):
    monkeypatch.setattr(api._STALLS['HC001'], 'closures', set())
    enrolled = enrol().json()
    # Simulate a research edit and mutation of old compatibility exports.
    monkeypatch.setattr(api, 'DEFAULT_RULES', replace(api.DEFAULT_RULES, rain_daily_mm=100, rain_payout=90))
    monkeypatch.setattr(pilot, 'RULES', replace(pilot.RULES, rain_daily_mm=100, rain_payout=90))
    monkeypatch.setitem(pilot.CONTRACT, 'combined_cap_sgd', 1)
    monkeypatch.setitem(pilot.CONTRACT, 'annual_premium_sgd', 999)
    assert client.get('/rules').json()['rain_daily_mm'] == 100
    assert client.get('/api/v1/rules').json()['rain_daily_mm'] == 70
    client.post('/engine/evaluate', params={'date':str(DAY),'stall_id':'HC001','rain_mm':200})
    assert client.get('/api/v1/policy/HC001').json()['remaining_combined_sgd'] == 180
    result = simulate(rain_daily_mm=70).json()
    assert result['amount'] == 30 and result['contract_sha256'] == M1_SHA256
    p = client.get('/api/v1/policy/HC001').json()
    assert p['policy_id'] == enrolled['policy_id'] and p['policy_period_id'] == enrolled['policy_period_id']
    assert p['product_version_id'] == M1_VERSION and p['remaining_combined_sgd'] == 150
    assert p['billing']['annual_premium_sgd'] == 104
    quote = client.post('/quote', json={'stall_id':'HC001'}).json()
    assert quote['rain']['mm_per_day'] == 70 and quote['premium'] == 104
    reply = client.post('/api/v1/concierge/chat', json={'message':'explain rain'}).json()
    assert '70' in reply['reply'] and M1_VERSION in reply['grounding']


def test_persisted_snapshot_validation_including_duplicate_path(monkeypatch):
    monkeypatch.setattr(api._STALLS['HC001'], 'closures', set())
    enrol()
    assert simulate().json()['amount'] == 30
    with pilot_store.connection() as conn:
        snapshot = json.loads(conn.execute('SELECT contract FROM pilot_policies').fetchone()[0])
        snapshot['rules']['rain_daily_mm'] = 100
        conn.execute('UPDATE pilot_policies SET contract=?', (json.dumps(snapshot),))
    for response in [client.get('/api/v1/policy/HC001'), client.get('/api/v1/payouts/HC001'), simulate()]:
        assert response.status_code == 409
        assert 'snapshot' in response.json()['detail']
    with pilot_store.connection() as conn:
        assert conn.execute('SELECT SUM(amount) FROM pilot_decisions').fetchone()[0] == 30


def test_original_m1_snapshot_without_hash_is_read_without_rewriting():
    enrolled = enrol().json()
    with pilot_store.connection() as conn:
        row = conn.execute('SELECT contract FROM pilot_policies').fetchone()
        original = json.loads(row[0]); original.pop('contract_sha256')
        original_json = json.dumps(original, sort_keys=True)
        conn.execute('UPDATE pilot_policies SET contract=?', (original_json,))
    p = client.get('/api/v1/policy/HC001').json()
    assert p['policy_id'] == enrolled['policy_id'] and p['contract_sha256'] == M1_SHA256
    assert p['policy_state'] == 'enrolled_simulation' and not p['real_policy_issued']
    with pilot_store.connection() as conn:
        assert conn.execute('SELECT contract FROM pilot_policies').fetchone()[0] == original_json


def test_frozen_file_and_returned_copies_cannot_rewrite_registry(tmp_path):
    terms = contracts.simulation_contract(M1_VERSION).terms
    terms['annual_premium_sgd'] = 999
    path = tmp_path/'edited.json'; path.write_text(json.dumps(terms))
    with pytest.raises(ValueError, match='Frozen M1 terms changed'):
        contracts._load_pilot(path)
    assert contracts.simulation_contract(M1_VERSION).terms['annual_premium_sgd'] == 104
    metadata = contracts.catalogue(); metadata[0]['lifecycle'] = 'approved'
    assert contracts.catalogue()[0]['lifecycle'] == 'simulation'


def test_service_boundaries_make_bridge_and_issuance_unavailable():
    b = client.get('/api/v1/integration').json()
    assert b['decision_authority'] == 'daycover.pilot'
    assert b['settlement_authority'] == 'pilot_simulation_ledger'
    assert not b['identity_mapping']['wallet_bridge_enabled']
    assert not b['real_issuance_supported'] and not b['real_settlement_supported']
    enrol()
    assert client.get('/api/v1/policy/HC001').json()['identity_namespace'] == 'pilot'


def test_nonpaying_flood_explanation_is_not_rain():
    r = client.post('/api/v1/concierge/chat', json={'message':'Does flood pay?'}).json()
    assert 'do not pay' in r['reply'].lower()
