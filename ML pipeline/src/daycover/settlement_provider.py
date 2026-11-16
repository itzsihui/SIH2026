"""Persistent, signed local settlement simulator; no external bank/wallet adapter."""
from dataclasses import dataclass
import hashlib
import hmac
import secrets
from typing import Protocol
from .contracts import canonical_json
from .ledger_repository import entity_id

PROVIDER='deterministic_mock_settlement_v1'


@dataclass(frozen=True)
class Dispatch:
    provider_ref:str
    state:str


class SettlementProvider(Protocol):
    def submit(self,instruction:dict)->Dispatch: ...
    def status(self,instruction_id:str)->dict | None: ...


class MockSettlementProvider:
    name=PROVIDER
    def __init__(self,repository):self.repo=repository

    @staticmethod
    def _key(c):
        c.execute('INSERT INTO settlement_mock_key VALUES (?,?) ON CONFLICT DO NOTHING',('local_mock_only',secrets.token_hex(32)))
        return c.execute('SELECT secret FROM settlement_mock_key WHERE id=?',('local_mock_only',)).fetchone()['secret']

    @classmethod
    def sign(cls,c,payload):return hmac.new(cls._key(c).encode(),canonical_json(payload).encode(),hashlib.sha256).hexdigest()

    @classmethod
    def verify(cls,c,payload,signature):return isinstance(signature,str) and hmac.compare_digest(cls.sign(c,payload),signature)

    def submit(self,instruction):
        amount=instruction['amount_cents'];scenario=instruction['scenario']
        gross=0 if scenario in ('failed','pending') else amount//2 if scenario=='partial' else amount
        status='pending' if scenario=='pending' else 'failed' if scenario=='failed' or (scenario=='partial' and not gross) else 'partially_confirmed' if scenario=='partial' else 'confirmed'
        with self.repo.transaction() as c:
            c.execute('''INSERT INTO settlement_mock_jobs VALUES (?,?,?,?,?,?,1,?,0,?,0) ON CONFLICT DO NOTHING''',
                      (instruction['id'],instruction['provider_ref'],instruction['recipient_id'],instruction['recipient_review_id'],amount,scenario,gross,status))
            job=c.execute('SELECT * FROM settlement_mock_jobs WHERE instruction_id=?',(instruction['id'],)).fetchone()
            if any(job[k]!=instruction[k] for k in ('provider_ref','recipient_id','recipient_review_id','amount_cents','scenario')):raise ValueError('Settlement provider idempotency binding mismatch.')
        return Dispatch(instruction['provider_ref'],'uncertain' if scenario=='timeout' else 'submitted')

    def status(self,instruction_id):
        with self.repo.transaction() as c:
            suffix=' FOR UPDATE' if c.backend=='postgres' else ''
            job=c.execute('SELECT * FROM settlement_mock_jobs WHERE instruction_id=?'+suffix,(instruction_id,)).fetchone()
            if not job:return None
            if job['scenario']=='reversal' and job['polls']>=1 and job['status']=='confirmed':
                c.execute("UPDATE settlement_mock_jobs SET provider_sequence=2,reversed_cents=gross_cents,status='reversed' WHERE instruction_id=?",(instruction_id,))
                job=c.execute('SELECT * FROM settlement_mock_jobs WHERE instruction_id=?',(instruction_id,)).fetchone()
            c.execute('UPDATE settlement_mock_jobs SET polls=polls+1 WHERE instruction_id=?',(instruction_id,))
            payload={'provider':PROVIDER,'instruction_id':instruction_id,'provider_ref':job['provider_ref'],'recipient_id':job['recipient_id'],
                     'recipient_review_id':job['recipient_review_id'],'currency':'SGD','event_id':entity_id('MOCK-SETTLEMENT-EVENT',instruction_id+'|'+str(job['provider_sequence'])),
                     'sequence':job['provider_sequence'],'status':job['status'],'gross_cents':job['gross_cents'],'reversed_cents':job['reversed_cents']}
            return {'payload':payload,'signature':self.sign(c,payload)}
