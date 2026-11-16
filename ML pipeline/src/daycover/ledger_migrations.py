"""Transactional additive migration/import. Legacy records stay; external sources are read-only."""
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from psycopg import sql

from .contracts import canonical_json, validate_snapshot
from .pilot import decide
from .policy_year import policy_year_bounds
from .ledger_repository import MIGRATIONS, UnitOfWork, cents, period_id


def _apply(native, backend, script):
    if backend == 'postgres':
        native.execute(script, prepare=False)
    else:
        # executescript() implicitly commits; execute complete statements instead.
        buffer = ''
        for line in script.splitlines(True):
            buffer += line
            if sqlite3.complete_statement(buffer):
                native.execute(buffer)
                buffer = ''
        if buffer.strip():
            raise ValueError('Incomplete migration SQL.')


def migrate_native(repo, native):
    scripts = [(v, (MIGRATIONS / f'{v:03d}_{repo.backend}.sql').read_text()) for v in (1, 2, 3, 4, 5, 6, 7)]
    if repo.backend == 'postgres':
        with native.transaction():
            native.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('daycover-migration:'+repo.schema,))
            native.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(repo.schema)))
            _migrate_all(UnitOfWork(native,repo.backend), scripts)
    else:
        native.execute('BEGIN IMMEDIATE')
        try:
            _migrate_all(UnitOfWork(native,repo.backend), scripts)
            native.commit()
        except Exception:
            native.rollback()
            raise


def _migrate_all(uow, scripts):
    for version, script in scripts:
        checksum = hashlib.sha256(script.encode()).hexdigest()
        if version == 1:
            _migrate(uow, script, checksum)
            continue
        row = uow.execute('SELECT checksum FROM pilot_schema_migrations WHERE version=?', (version,)).fetchone()
        if row:
            if row['checksum'] != checksum:
                raise ValueError('Pilot migration checksum differs; review required.')
        else:
            _apply(uow.native, uow.backend, script)
            uow.execute('INSERT INTO pilot_schema_migrations VALUES (?,?)', (version, checksum))


def _migrate(uow, script, checksum):
    if uow.backend == 'sqlite':
        ready = uow.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pilot_schema_migrations'").fetchone()
    else:
        ready = uow.execute("SELECT to_regclass('pilot_schema_migrations') AS name").fetchone()['name']
    if ready:
        row = uow.execute('SELECT checksum FROM pilot_schema_migrations WHERE version=1').fetchone()
        if not row or row['checksum'] != checksum:
            raise ValueError('Pilot migration checksum/version differs; explicit migration review required.')
        return
    legacy = False
    if uow.backend == 'sqlite':
        legacy = uow.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pilot_policies'").fetchone() is not None
        if legacy:
            uow.execute('ALTER TABLE pilot_policies RENAME TO legacy_m1_policies')
            uow.execute('ALTER TABLE pilot_decisions RENAME TO legacy_m1_decisions')
    _apply(uow.native,uow.backend,script)
    if legacy:
        policies = [dict(row) for row in uow.execute('SELECT * FROM legacy_m1_policies').fetchall()]
        decisions = [dict(row) for row in uow.execute('SELECT * FROM legacy_m1_decisions ORDER BY day,peril').fetchall()]
        import_rows(uow,policies,decisions)
    uow.execute('INSERT INTO pilot_schema_migrations VALUES (?,?)', (1,checksum))


def import_rows(uow, policies, decisions):
    digest = hashlib.sha256(canonical_json({'policies':policies,'decisions':decisions}).encode()).hexdigest()
    if uow.execute('SELECT source_sha256 FROM pilot_imports WHERE source_sha256=?', (digest,)).fetchone():
        return {'already_imported':True,'policies':len(policies),'decisions':len(decisions)}
    known = {}
    for row in policies:
        validate_snapshot(json.loads(row['contract']))
        inception=date.fromisoformat(row['start'])
        if date.fromisoformat(row['end']) != policy_year_bounds(inception,inception)[1]:
            raise ValueError('Legacy term differs from the supported enrolled anniversary term.')
        if datetime.fromisoformat(row['accepted_at']).tzinfo is None:
            raise ValueError('Legacy acceptance timestamp requires timezone.')
        existing = uow.execute('SELECT * FROM pilot_policies WHERE stall_id=? OR id=?', (row['stall_id'],row['id'])).fetchall()
        if existing:
            if len(existing)!=1 or any(existing[0][key]!=row[key] for key in ('id','stall_id','start','end','contract')):
                raise ValueError('Import conflicts with an existing policy; no overwrite permitted.')
        else:
            uow.create_policy(row)
        known[row['id']] = row
    for row in decisions:
        p = known.get(row['policy_id'])
        if p is None or not p['start'] <= row['day'] <= p['end']:
            raise ValueError('Legacy decision outside a known policy term.')
        response = json.loads(row['response'])
        if cents(response['amount']) != cents(row['amount']) or row['peril'] not in ('rain','haze'):
            raise ValueError('Legacy decision money/peril mismatch.')
        if response['policy_id'] != p['id'] or response['rule_version'] != json.loads(p['contract'])['version']:
            raise ValueError('Legacy decision version/policy mismatch.')
        existing = uow.execute('SELECT response FROM pilot_decisions WHERE policy_id=? AND day=? AND peril=?', (p['id'],row['day'],row['peril'])).fetchone()
        if existing:
            if canonical_json(json.loads(existing['response'])) != canonical_json(response):
                raise ValueError('Import conflicts with an existing decision; no overwrite permitted.')
            continue
        p = {**p,'period_id':period_id(p['id'],p['start'])}
        evidence=response['evidence']
        if evidence.get('source')!='synthetic_demo':
            raise ValueError('Legacy import supports only labelled M1 simulation evidence.')
        state, amount, _ = decide(row['peril'],evidence.get('daily_rain_mm'),evidence.get('psi_today'),evidence.get('psi_yesterday'),
            response['status']=='SUPPRESSED',uow.used(p['period_id']),version=json.loads(p['contract'])['version'])
        if state!=response['status'] or cents(amount)!=cents(row['amount']):
            raise ValueError('Legacy decision does not reproduce under its accepted terms.')
        if datetime.fromisoformat(response['timestamp']).tzinfo is None or datetime.fromisoformat(p['accepted_at']).tzinfo is None:
            raise ValueError('Legacy acceptance/decision timestamps require timezone.')
        uow.post_decision(p,row['day'],row['peril'],response)
        terms = validate_snapshot(json.loads(p['contract'])).terms
        used = uow.used(p['period_id'])
        if used['rain']>terms['rules']['rain_cap_days_per_year'] or used['haze_days']>terms['rules']['haze_cap_days_per_year'] or cents(used['haze_sgd'])>cents(terms['rules']['haze_cap_amount_per_year']) or cents(used['total'])>cents(terms['combined_cap_sgd']):
            raise ValueError('Legacy source exceeds frozen policy caps; review instead of importing.')
    uow.execute('INSERT INTO pilot_imports VALUES (?,?,?)', (digest,canonical_json({'policy_count':len(policies),'decision_count':len(decisions)}),datetime.now(timezone.utc).isoformat()))
    return {'already_imported':False,'policies':len(policies),'decisions':len(decisions)}


def import_sqlite(repo, source):
    source = Path(source).resolve()
    if repo.backend == 'sqlite' and source == repo.path.resolve():
        raise ValueError('Use a separate read-only import source; in-place legacy migration is automatic.')
    native = sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
    native.row_factory=sqlite3.Row
    try:
        native.execute('BEGIN')
        names={r[0] for r in native.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'pilot_schema_migrations' in names:
            raise ValueError('Source is already canonical; use a verified full backup/restore, not legacy import.')
        policies=[dict(r) for r in native.execute('SELECT * FROM pilot_policies ORDER BY id')]
        decisions=[dict(r) for r in native.execute('SELECT * FROM pilot_decisions ORDER BY day,peril')]
    finally:
        native.close()
    with repo.transaction() as uow:
        return import_rows(uow,policies,decisions)
