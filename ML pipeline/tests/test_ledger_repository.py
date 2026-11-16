"""Execute the same ledger guarantees on SQLite and a real PostgreSQL service."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import hashlib
import json
import sqlite3

from fastapi.testclient import TestClient
import psycopg
import pytest

from src.daycover import pilot_store
from src.daycover.api import app
from src.daycover.contracts import M1_VERSION
from src.daycover.ledger_repository import SqlLedgerRepository, UnitOfWork, cents, configured_repository, period_id
from src.daycover.ledger_migrations import import_sqlite

DAY=date(2026,1,2)
START=date(2025,12,15)
client=TestClient(app)


def enrol():
    return pilot_store.enrol('HC001',START,'S79','south',M1_VERSION)


def event(day=DAY,peril='rain',rain=70,psi=151,closed=False):
    return pilot_store.simulate('HC001',day,peril,rain,psi,120,closed,'S79','south')


def count(repo,table):
    with repo.transaction() as c:
        return c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]


def test_persisted_identity_period_audit_and_exact_money(ledger_backend):
    assert client.get('/api/v1/ledger/health').json()['backend']==ledger_backend.backend
    p=enrol()
    r=event()
    assert r['amount']==30
    assert len({p['policy_id'],p['merchant_id'],p['operator_id'],p['stall_entity_id'],p['policy_period_id']})==5
    assert p['policy_period_id']==period_id(p['policy_id'],str(START))
    assert pilot_store.policy('HC001')['remaining_combined_sgd']==150
    # A new repository object/connection reconstructs balances from persisted entries.
    other=SqlLedgerRepository(ledger_backend.backend,path=ledger_backend.path,url=ledger_backend.url,schema=ledger_backend.schema)
    with other.transaction() as c:
        assert c.used(p['policy_period_id'])['total']==30
        assert c.execute('SELECT SUM(amount_cents) FROM pilot_financial_entries').fetchone()[0]==0
        assert c.execute('SELECT identity_status FROM pilot_merchants').fetchone()[0]=='unverified_simulation'
        audit=c.execute("SELECT details FROM pilot_audit WHERE action='terms_accepted'").fetchone()[0]
        assert json.loads(audit)['identity']=='unverified_simulation'
    assert count(other,'pilot_instructions')==1
    assert count(other,'pilot_settlement_attempts')==1
    assert count(other,'pilot_billing_entries')==0 # Phase 7, not a fabricated collection.
    assert pilot_store.reconcile('HC001')['status']=='balanced'
    assert client.get('/api/v1/payouts/HC001').json()['reconciliation']['allocated_cents']==3000
    with pytest.raises(ValueError): cents('30.001')
    assert cents('8.67')==867


def test_concurrent_duplicates_and_distinct_perils_never_overspend(ledger_backend):
    enrol()
    event(DAY,'haze')
    event(DAY+timedelta(days=1),'haze') # S$120 haze consumed.
    jobs=['rain','haze']*5
    with ThreadPoolExecutor(max_workers=8) as pool:
        out=list(pool.map(lambda peril:event(DAY+timedelta(days=2),peril),jobs))
    assert sum(r['disbursed'] for r in out)==2
    p=pilot_store.policy('HC001')
    assert p['annual_haze_paid_sgd']==150 and p['remaining_combined_sgd']==0
    assert pilot_store.history('HC001')['total_disbursed']==180
    assert count(ledger_backend,'pilot_instructions')==4
    assert count(ledger_backend,'pilot_financial_entries')==8
    assert pilot_store.reconcile('HC001')['status']=='balanced'


def test_transaction_failure_rolls_back_decision_and_all_postings(ledger_backend,monkeypatch):
    enrol()
    original=UnitOfWork.post_financial
    def fail_after_post(self,*args):
        original(self,*args)
        raise RuntimeError('Simulated crash after financial insert')
    monkeypatch.setattr(UnitOfWork,'post_financial',fail_after_post)
    with pytest.raises(RuntimeError): event()
    for table in ('pilot_decisions','pilot_evidence','pilot_decision_revisions','pilot_instructions','pilot_settlement_attempts','pilot_financial_entries'):
        assert count(ledger_backend,table)==0
    assert pilot_store.policy('HC001')['remaining_combined_sgd']==180
    monkeypatch.setattr(UnitOfWork,'post_financial',original)
    assert event()['amount']==30
    assert count(ledger_backend,'pilot_instructions')==1


def test_pending_resolution_retains_evidence_and_revisions(ledger_backend):
    enrol()
    assert event(rain=None)['status']=='PENDING'
    assert event(rain=70)['amount']==30
    assert count(ledger_backend,'pilot_decisions')==1
    assert count(ledger_backend,'pilot_decision_revisions')==2
    assert count(ledger_backend,'pilot_evidence')==2
    assert event()['duplicate']
    assert count(ledger_backend,'pilot_decision_revisions')==2


def test_append_only_corrections_are_idempotent_and_do_not_restore_caps(ledger_backend):
    enrol(); original=event()
    with ledger_backend.transaction() as c:
        entry=c.execute("SELECT id FROM pilot_financial_entries WHERE kind='simulated_settlement'").fetchone()[0]
    correction=pilot_store.compensate_simulation('HC001',entry,'Test reconciliation correction','key-1')
    assert pilot_store.compensate_simulation('HC001',entry,'Test reconciliation correction','key-1')==correction
    with pytest.raises(ValueError): pilot_store.compensate_simulation('HC001',entry,'Other reason','key-1')
    with pytest.raises(ValueError): pilot_store.compensate_simulation('HC001',entry,'Another correction','key-2')
    assert count(ledger_backend,'pilot_financial_entries')==3
    assert pilot_store.policy('HC001')['remaining_rain_events']==0
    assert event(DAY+timedelta(days=1))['status']=='CAPPED'
    report=pilot_store.reconcile('HC001')
    assert report['compensated_cents']==3000 and report['outstanding_simulated_cents']==3000
    assert report['status']=='review_required'
    assert pilot_store.history('HC001')['claims'][0]['claim_id']==original['claim_id']
    for statement in ["UPDATE pilot_financial_entries SET amount_cents=0", "DELETE FROM pilot_audit", "UPDATE pilot_decisions SET amount=0,amount_cents=0"]:
        with pytest.raises((sqlite3.DatabaseError,psycopg.Error)):
            with ledger_backend.transaction() as c: c.execute(statement)


def test_foreign_keys_and_backend_failures_do_not_fallback(ledger_backend,monkeypatch,tmp_path):
    with pytest.raises((sqlite3.DatabaseError,psycopg.Error)):
        with ledger_backend.transaction() as c:
            c.execute('INSERT INTO pilot_operator_merchants VALUES (?,?)',('unknown','unknown'))
    monkeypatch.setenv('DAYCOVER_PILOT_BACKEND','postgres')
    monkeypatch.setenv('DAYCOVER_PILOT_DATABASE_URL','postgresql://invalid@127.0.0.1:1/no_database')
    monkeypatch.setenv('DAYCOVER_PILOT_DB',str(tmp_path/'must-not-exist.sqlite3'))
    assert client.get('/api/v1/policy/HC001').status_code==503
    assert client.get('/api/v1/ledger/health').status_code==503
    assert not (tmp_path/'must-not-exist.sqlite3').exists()


def legacy_file(tmp_path,corrupt=False):
    # Capture a real canonical scenario as the exact original six/five-column M1 layout.
    enrol(); event()
    with pilot_store.connection() as c:
        p=c.execute('SELECT id,stall_id,start,"end",contract,accepted_at FROM pilot_policies').fetchone()
        d=c.execute('SELECT policy_id,day,peril,response,amount FROM pilot_decisions').fetchone()
    source=tmp_path/'original-m1.sqlite3'
    with sqlite3.connect(source) as conn:
        conn.execute('CREATE TABLE pilot_policies(id TEXT PRIMARY KEY,stall_id TEXT UNIQUE,start TEXT,end TEXT,contract TEXT,accepted_at TEXT)')
        conn.execute('CREATE TABLE pilot_decisions(policy_id TEXT,day TEXT,peril TEXT,response TEXT,amount REAL,PRIMARY KEY(policy_id,day,peril))')
        conn.execute('INSERT INTO pilot_policies VALUES (?,?,?,?,?,?)',tuple(p.values()))
        values=list(d.values()); values[-1]=31 if corrupt else float(values[-1])
        conn.execute('INSERT INTO pilot_decisions VALUES (?,?,?,?,?)',values)
    return source,p,d


def test_legacy_import_preserves_ids_snapshots_receipts_and_is_repeatable(ledger_backend,tmp_path,monkeypatch):
    # Generate source in a separate SQLite demo, then import to either destination.
    source_repo=SqlLedgerRepository(path=tmp_path/'source-canonical.sqlite3')
    with monkeypatch.context() as m:
        m.setattr(pilot_store,'configured_repository',lambda:source_repo)
        source,p,d=legacy_file(tmp_path)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    result=import_sqlite(ledger_backend,source)
    assert result['policies']==1 and result['decisions']==1
    assert import_sqlite(ledger_backend,source)['already_imported']
    assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
    read=pilot_store.policy('HC001')
    assert read['policy_id']==p['id'] and read['policy_period_id']==period_id(p['id'],p['start'])
    with ledger_backend.transaction() as c:
        assert c.execute('SELECT contract FROM pilot_policies').fetchone()[0]==p['contract']
        assert c.execute('SELECT response FROM pilot_decisions').fetchone()[0]==d['response']
    assert event()['duplicate']
    assert count(ledger_backend,'pilot_financial_entries')==2
    assert pilot_store.reconcile('HC001')['allocated_cents']==3000


def test_invalid_import_rolls_back_every_destination_row(ledger_backend,tmp_path,monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(pilot_store,'configured_repository',lambda:SqlLedgerRepository(path=tmp_path/'bad-source.sqlite3'))
        source,_,_=legacy_file(tmp_path,corrupt=True)
    with pytest.raises(ValueError): import_sqlite(ledger_backend,source)
    for table in ('pilot_merchants','pilot_policies','pilot_decisions','pilot_audit','pilot_financial_entries','pilot_imports'):
        assert count(ledger_backend,table)==0


def test_migration_repeatability_and_legacy_tables_not_used(ledger_backend):
    with ledger_backend.transaction() as c:
        c.execute('CREATE TABLE policies (id TEXT PRIMARY KEY)')
        c.execute('INSERT INTO policies VALUES (?)',('legacy-sentinel',))
    enrol(); event()
    ledger_backend.migrate(); ledger_backend.migrate()
    with ledger_backend.transaction() as c:
        assert c.execute('SELECT id FROM policies').fetchone()[0]=='legacy-sentinel'
    assert count(ledger_backend,'pilot_schema_migrations')==8
    assert count(ledger_backend,'pilot_instructions')==1
    assert pilot_store.policy('HC001')['remaining_combined_sgd']==150


def test_sqlite_in_place_migration_preserves_original_tables_and_failure_rolls_back(tmp_path,monkeypatch):
    source,p,_=legacy_file(tmp_path)
    repo=SqlLedgerRepository(path=source)
    repo.migrate()
    with repo.transaction() as c:
        assert c.execute('SELECT contract FROM legacy_m1_policies').fetchone()[0]==p['contract']
        assert c.execute('SELECT id FROM pilot_policies').fetchone()[0]==p['id']
    # Migration rollback includes renames and all DDL/data inserts.
    other=tmp_path/'bad-old.sqlite3'
    with sqlite3.connect(other) as conn:
        conn.execute('CREATE TABLE pilot_policies(id TEXT,stall_id TEXT,start TEXT,end TEXT,contract TEXT,accepted_at TEXT)')
        conn.execute('CREATE TABLE pilot_decisions(policy_id TEXT,day TEXT,peril TEXT,response TEXT,amount REAL)')
        conn.execute('INSERT INTO pilot_policies VALUES (?,?,?,?,?,?)',('bad','bad','2026-01-01','2026-12-31','{}','2026-01-01T00:00:00+08:00'))
    with pytest.raises(ValueError): SqlLedgerRepository(path=other).migrate()
    with sqlite3.connect(other) as conn:
        names={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names=={'pilot_policies','pilot_decisions'}
        assert conn.execute('SELECT contract FROM pilot_policies').fetchone()[0]=='{}'


@pytest.mark.parametrize('ledger_backend',['postgres'],indirect=True)
def test_sqlite_postgres_scenario_parity(ledger_backend,tmp_path,monkeypatch):
    def scenario():
        enrol()
        result=[]
        actions=[(DAY,'rain',None,151,False), (DAY,'rain',69.9,151,False),
                 (DAY+timedelta(days=1),'rain',70,151,False),
                 (DAY+timedelta(days=1),'haze',70,151,False),
                 (DAY+timedelta(days=2),'haze',70,151,False),
                 (DAY+timedelta(days=3),'haze',70,151,False),
                 (DAY+timedelta(days=4),'haze',70,151,True)]
        for args in actions:
            row=event(*args)
            result.append((row['status'],row['amount'],row['reason'],row['evidence']))
        p=pilot_store.policy('HC001')
        return {'events':result,'balances':{k:v for k,v in p.items() if k.startswith('remaining_')},
                'reconciliation':{k:v for k,v in pilot_store.reconcile('HC001').items() if k!='policy_id'}}
    pg=scenario()
    with monkeypatch.context() as m:
        m.setattr(pilot_store,'configured_repository',lambda:SqlLedgerRepository(path=tmp_path/'parity.sqlite3'))
        sqlite=scenario()
    assert pg==sqlite


@pytest.mark.parametrize('ledger_backend',['postgres'],indirect=True)
def test_postgres_requires_explicit_migration(ledger_backend,monkeypatch):
    import uuid
    absent='daycover_pilot_missing_'+uuid.uuid4().hex
    monkeypatch.setenv('DAYCOVER_PILOT_PG_SCHEMA',absent)
    assert client.get('/api/v1/ledger/health').status_code==503
    assert client.get('/api/v1/policy/HC001').status_code==503
    with ledger_backend.transaction() as c:
        assert c.execute('SELECT to_regnamespace(?)',(absent,)).fetchone()[0] is None


def test_legacy_empty_policy_cannot_import_invalid_term_or_naive_acceptance(ledger_backend,tmp_path,monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(pilot_store,'configured_repository',lambda:SqlLedgerRepository(path=tmp_path/'bad-term-source.sqlite3'))
        source,p,_=legacy_file(tmp_path)
    with sqlite3.connect(source) as c:
        c.execute('DELETE FROM pilot_decisions')
        c.execute('UPDATE pilot_policies SET end=?',('2028-12-31',))
    with pytest.raises(ValueError,match='anniversary'): import_sqlite(ledger_backend,source)
    assert count(ledger_backend,'pilot_policies')==0
    with sqlite3.connect(source) as c:
        c.execute('UPDATE pilot_policies SET end=?,accepted_at=?',(p['end'],'2025-12-15T00:00:00'))
    with pytest.raises(ValueError,match='timezone'): import_sqlite(ledger_backend,source)
    assert count(ledger_backend,'pilot_policies')==0
