import pytest

@pytest.fixture(autouse=True)
def isolate_pilot_db(tmp_path, monkeypatch):
    # Legacy contract/ledger scenarios explicitly opt into the isolated demo API.
    monkeypatch.setenv('DAYCOVER_AUTH_MODE', 'demo')
    monkeypatch.setenv('DAYCOVER_PILOT_BACKEND', 'sqlite')
    monkeypatch.delenv('DAYCOVER_PILOT_DATABASE_URL', raising=False)
    monkeypatch.delenv('DAYCOVER_PILOT_PG_SCHEMA', raising=False)
    monkeypatch.setenv('DAYCOVER_PILOT_DB', str(tmp_path / 'pilot.sqlite3'))


@pytest.fixture(params=['sqlite', 'postgres'])
def ledger_backend(request, monkeypatch, tmp_path):
    import os
    import uuid
    import psycopg
    from psycopg import sql
    from src.daycover.ledger_repository import SqlLedgerRepository
    if request.param=='sqlite':
        repo=SqlLedgerRepository(path=tmp_path/'canonical.sqlite3')
        monkeypatch.setenv('DAYCOVER_PILOT_DB', str(repo.path))
        repo.migrate()
        yield repo
    else:
        url=os.getenv('DAYCOVER_TEST_POSTGRES_URL')
        if not url:
            pytest.skip('Set DAYCOVER_TEST_POSTGRES_URL to run real Postgres parity tests')
        schema='daycover_pilot_test_'+uuid.uuid4().hex
        repo=SqlLedgerRepository('postgres',url=url,schema=schema)
        repo.migrate()
        monkeypatch.setenv('DAYCOVER_PILOT_BACKEND','postgres')
        monkeypatch.setenv('DAYCOVER_PILOT_DATABASE_URL',url)
        monkeypatch.setenv('DAYCOVER_PILOT_PG_SCHEMA',schema)
        try:
            yield repo
        finally:
            # Only the fresh schema created by this fixture, never shared application data.
            with psycopg.connect(url,autocommit=True) as conn:
                conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
