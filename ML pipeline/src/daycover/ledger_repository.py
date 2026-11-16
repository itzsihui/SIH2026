"""SQL repository/unit-of-work for the isolated canonical simulation ledger."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import ContextManager, Protocol
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg import sql

from .contracts import canonical_json, fingerprint, simulation_contract, validate_snapshot

MIGRATIONS = Path(__file__).resolve().parents[2] / 'migrations' / 'pilot'


class LedgerUnavailable(RuntimeError):
    pass


def cents(amount):
    value = Decimal(str(amount)) * 100
    if not value.is_finite() or value != value.to_integral_value():
        raise ValueError('Money must have exact cent precision.')
    return int(value)


def sgd(value):
    return float(Decimal(value) / 100)


def entity_id(kind, key):
    return 'SIM-' + kind + '-' + uuid.uuid5(uuid.NAMESPACE_URL, key).hex


def period_id(policy_id, start):
    return entity_id('PERIOD', f'{policy_id}|{start}')


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def row_data(row):
    if row is None:
        return None
    return Row({key: value.isoformat() if isinstance(value, (date, datetime)) else value for key, value in dict(row).items()})


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        return row_data(self.cursor.fetchone())

    def fetchall(self):
        return [row_data(row) for row in self.cursor.fetchall()]


class LedgerRepository(Protocol):
    def transaction(self) -> ContextManager['UnitOfWork']: ...


class UnitOfWork:
    def __init__(self, native, backend):
        self.native, self.backend = native, backend

    def execute(self, query, params=()):
        return Cursor(self.native.execute(query.replace('?', '%s') if self.backend == 'postgres' else query, params))

    def lock_policy(self, stall):
        p = self.execute('SELECT * FROM pilot_policies WHERE stall_id=?', (stall,)).fetchone()
        if not p:
            raise LookupError('Accept the demo contract before simulating coverage.')
        suffix = ' FOR UPDATE' if self.backend == 'postgres' else ''
        period = self.execute('SELECT * FROM pilot_periods WHERE policy_id=? AND start=?' + suffix, (p['id'],p['start'])).fetchone()
        if not period:
            raise ValueError('Policy period missing; reconciliation required.')
        if period['id']!=period_id(p['id'],p['start']) or period['start']!=p['start'] or period['end']!=p['end'] or period['version_id']!=p['version_id']:
            raise ValueError('Policy and period metadata differ; review required.')
        if period['combined_cap_cents'] != cents(simulation_contract(p['version_id']).terms['combined_cap_sgd']):
            raise ValueError('Stored period cap differs from accepted version.')
        p['period_id'] = period['id']
        p['identity_namespace'] = self.execute('SELECT namespace FROM pilot_merchants WHERE id=?',(p['merchant_id'],)).fetchone()['namespace']
        p['centre_id'] = self.execute('SELECT centre_id FROM pilot_stalls WHERE id=?',(p['stall_entity_id'],)).fetchone()['centre_id']
        return p

    def used(self, period):
        rows = self.execute("SELECT e.peril,e.amount_cents,d.day FROM pilot_financial_entries e JOIN pilot_decisions d ON d.decision_id=e.decision_id WHERE e.period_id=? AND e.kind='allocation'", (period,)).fetchall()
        if self.execute('SELECT version FROM pilot_schema_migrations WHERE version=5').fetchone():
            rows += self.execute('SELECT peril,amount_cents,day FROM engine_cap_entries WHERE period_id=?',(period,)).fetchall()
        return {'rain':len({r['day'] for r in rows if r['peril']=='rain'}), 'haze_days':len({r['day'] for r in rows if r['peril']=='haze'}),
                'haze_sgd':sgd(sum(r['amount_cents'] for r in rows if r['peril']=='haze')),'total':sgd(sum(r['amount_cents'] for r in rows))}

    def audit(self, policy, action, details, timestamp):
        self.execute('INSERT INTO pilot_audit VALUES (?,?,?,?,?)', (str(uuid.uuid4()), policy, action, canonical_json(details), timestamp))

    def create_policy(self, p):
        snapshot = json.loads(p['contract'])
        entry = validate_snapshot(snapshot)
        identity = self.execute('SELECT * FROM auth_onboarding WHERE stall_id=?', (p['stall_id'],)).fetchone() if self.execute("SELECT version FROM pilot_schema_migrations WHERE version=2").fetchone() else None
        if identity:
            if identity['status'] != 'eligible_simulation' or identity['accepted_version'] != entry.version:
                raise ValueError('Local eligibility review and matching acceptance version required.')
            if snapshot['assigned_gauge'] != identity['gauge'] or snapshot['psi_region'] != identity['psi_region']:
                raise ValueError('Assignment differs from reviewed onboarding.')
            ids = {'merchant':identity['merchant_id'], 'operator':identity['operator_id'], 'stall':identity['stall_entity_id']}
        else:
            ids = {kind: entity_id(kind.upper(), 'pilot|' + p['stall_id']) for kind in ('merchant','operator','centre','stall')}
            self.execute('INSERT INTO pilot_merchants VALUES (?,?,?,?) ON CONFLICT DO NOTHING', (ids['merchant'], 'pilot_demo',p['stall_id'],'unverified_simulation'))
            self.execute('INSERT INTO pilot_operators VALUES (?,?,?,?) ON CONFLICT DO NOTHING', (ids['operator'], 'pilot_demo',p['stall_id'],'unverified_simulation'))
            self.execute('INSERT INTO pilot_operator_merchants VALUES (?,?) ON CONFLICT DO NOTHING', (ids['operator'],ids['merchant']))
            self.execute('INSERT INTO pilot_centres VALUES (?,?,?) ON CONFLICT DO NOTHING', (ids['centre'],'pilot',p['stall_id']))
            self.execute('INSERT INTO pilot_stalls VALUES (?,?,?,?) ON CONFLICT DO NOTHING', (ids['stall'],ids['centre'],'pilot',p['stall_id']))
        self.execute('INSERT INTO pilot_product_versions VALUES (?,?,?,?) ON CONFLICT DO NOTHING', (entry.version,canonical_json(entry.terms),entry.sha256,'simulation'))
        registered = self.execute('SELECT * FROM pilot_product_versions WHERE id=?', (entry.version,)).fetchone()
        if registered['contract_sha256'] != entry.sha256 or canonical_json(json.loads(registered['contract'])) != canonical_json(entry.terms):
            raise ValueError('Stored product version differs from registry.')
        self.execute('''INSERT INTO pilot_policies
          (id,stall_id,merchant_id,operator_id,stall_entity_id,version_id,start,"end",contract,contract_sha256,accepted_at,status)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (p['id'],p['stall_id'],ids['merchant'],ids['operator'],ids['stall'],entry.version,p['start'],p['end'],p['contract'],entry.sha256,p['accepted_at'],'enrolled_simulation'))
        self.execute('INSERT INTO pilot_periods VALUES (?,?,?,?,?,?,?)', (period_id(p['id'],p['start']),p['id'],entry.version,p['start'],p['end'],'SGD',cents(entry.terms['combined_cap_sgd'])))
        if self.execute('SELECT version FROM pilot_schema_migrations WHERE version=5').fetchone():
            from .policy_lifecycle import initial_term
            initial_term(self,p)
        self.audit(p['id'],'terms_accepted',{'version':entry.version,'contract_sha256':entry.sha256,'assigned_gauge':snapshot['assigned_gauge'],'psi_region':snapshot['psi_region'],'identity':'unverified_simulation'},p['accepted_at'])

    def post_decision(self, p, day, peril, response):
        amount = cents(response['amount'])
        claim, period, ts = response['claim_id'], p['period_id'], response['timestamp']
        evidence = response['evidence']
        evidence_id = entity_id('EVIDENCE', canonical_json(evidence))
        self.execute('INSERT INTO pilot_evidence VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING', (evidence_id,str(day),evidence['source'],canonical_json(evidence),fingerprint(evidence)))
        # Only pending decisions may advance. The facade has locked the period.
        self.execute('''INSERT INTO pilot_decisions (policy_id,day,peril,response,amount_cents,currency,period_id,decision_id)
         VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(policy_id,day,peril) DO UPDATE SET response=excluded.response,amount_cents=excluded.amount_cents''',
          (p['id'],str(day),peril,json.dumps(response),amount,'SGD',period,claim))
        self.execute('INSERT INTO pilot_decision_revisions VALUES (?,?,?,?,?,?,?)', (str(uuid.uuid4()),p['id'],period,claim,evidence_id,json.dumps(response),ts))
        if amount:
            self.post_financial(p, peril, response)
        self.audit(p['id'],'decision_recorded',{'decision_id':claim,'status':response['status'],'amount_cents':amount,'currency':'SGD'},ts)

    def post_financial(self, p, peril, response):
        claim, amount, ts = response['claim_id'], cents(response['amount']), response['timestamp']
        instruction = entity_id('INSTRUCTION', claim)
        self.execute('INSERT INTO pilot_instructions VALUES (?,?,?,?,?,?,?,?,?)', (instruction,p['id'],p['period_id'],claim,amount,'SGD','simulation_only','simulated_confirmed','instruction:'+claim))
        self.execute('INSERT INTO pilot_settlement_attempts VALUES (?,?,?,?,?,?)', (entity_id('ATTEMPT',claim),instruction,'simulated_confirmed','simulation',response['reference_number'],ts))
        for kind, value in [('allocation',amount),('simulated_settlement',-amount)]:
            self.execute('INSERT INTO pilot_financial_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (entity_id('ENTRY',kind+claim),p['id'],p['period_id'],claim,peril,kind,value,'SGD',None,kind+':'+claim,'M1 simulation only',ts))


class SqlLedgerRepository:
    def __init__(self, backend='sqlite', *, path=None, url=None, schema='daycover_pilot'):
        if backend not in ('sqlite','postgres'):
            raise ValueError('Unsupported pilot ledger backend.')
        if not re.fullmatch(r'daycover_pilot(?:_[a-z0-9_]+)?', schema):
            raise ValueError('Invalid isolated pilot schema name.')
        if backend == 'postgres' and not url:
            raise ValueError('Postgres pilot ledger requires its own database URL.')
        self.backend, self.path, self.url, self.schema = backend, Path(path or 'var/pilot.sqlite3'), url, schema

    def _connect(self):
        if self.backend == 'sqlite':
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=20, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            return conn
        try:
            conn = psycopg.connect(self.url, autocommit=True, row_factory=dict_row, connect_timeout=5)
            conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
            return conn
        except psycopg.Error as exc:
            raise LedgerUnavailable('Pilot Postgres ledger is unavailable; no SQLite fallback.') from exc

    @contextmanager
    def transaction(self):
        native = self._connect()
        try:
            if self.backend == 'sqlite':
                from .ledger_migrations import migrate_native
                migrate_native(self,native)
                native.execute('BEGIN IMMEDIATE')
                try:
                    yield UnitOfWork(native,self.backend)
                    native.commit()
                except Exception:
                    native.rollback()
                    raise
            else:
                with native.transaction():
                    try:
                        for version in (1, 2, 3, 4, 5, 6, 7):
                            ready = native.execute('SELECT checksum FROM pilot_schema_migrations WHERE version=%s', (version,)).fetchone()
                            expected = hashlib.sha256((MIGRATIONS / f'{version:03d}_postgres.sql').read_text().encode()).hexdigest()
                            if not ready or ready['checksum'] != expected:
                                raise LedgerUnavailable('Pilot ledger migration is incomplete or incompatible.')
                    except psycopg.errors.UndefinedTable as exc:
                        raise LedgerUnavailable('Pilot ledger needs explicit migration; no legacy-table fallback.') from exc
                    yield UnitOfWork(native,self.backend)
        finally:
            native.close()

    def migrate(self):
        from .ledger_migrations import migrate_native
        native = self._connect()
        try:
            migrate_native(self,native)
        finally:
            native.close()


def configured_repository():
    if os.getenv('DAYCOVER_PILOT_DATABASE_URL') and 'DAYCOVER_PILOT_BACKEND' not in os.environ:
        raise ValueError('Select DAYCOVER_PILOT_BACKEND explicitly when supplying a pilot database URL.')
    return SqlLedgerRepository(os.getenv('DAYCOVER_PILOT_BACKEND','sqlite'), path=os.getenv('DAYCOVER_PILOT_DB','var/pilot.sqlite3'),
        url=os.getenv('DAYCOVER_PILOT_DATABASE_URL'), schema=os.getenv('DAYCOVER_PILOT_PG_SCHEMA','daycover_pilot'))
