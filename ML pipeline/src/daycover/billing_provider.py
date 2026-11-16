"""Provider contract and persistent deterministic local mock. No network/debit adapter."""
from dataclasses import dataclass
import hashlib
import hmac
import json
import secrets
from typing import Protocol

from .contracts import canonical_json
from .ledger_repository import entity_id

PROVIDER='deterministic_mock_v1'


@dataclass(frozen=True)
class Dispatch:
    provider_ref:str
    state:str


class CollectionProvider(Protocol):
    def submit(self,attempt:dict)->Dispatch: ...
    def status(self,attempt_id:str)->dict | None: ...
    def refund(self,request:dict)->dict: ...


class MockCollectionProvider:
    name=PROVIDER
    def __init__(self,repository):self.repo=repository

    @staticmethod
    def _key(c):
        c.execute('INSERT INTO billing_mock_key VALUES (?,?) ON CONFLICT DO NOTHING',('local_mock_only',secrets.token_hex(32)))
        return c.execute('SELECT secret FROM billing_mock_key WHERE id=?',('local_mock_only',)).fetchone()['secret']

    @classmethod
    def sign(cls,c,payload):
        return hmac.new(cls._key(c).encode(),canonical_json(payload).encode(),hashlib.sha256).hexdigest()

    @classmethod
    def verify(cls,c,payload,signature):
        return isinstance(signature,str) and hmac.compare_digest(cls.sign(c,payload),signature)

    def submit(self,attempt):
        amount=attempt['amount_cents'];scenario=attempt['scenario']
        gross=0 if scenario in ('failed','pending') else amount//2 if scenario=='partial' else amount
        status='pending' if scenario=='pending' else 'failed' if scenario=='failed' or (scenario=='partial' and gross==0) else 'partially_collected' if scenario=='partial' else 'confirmed'
        with self.repo.transaction() as c:
            c.execute('''INSERT INTO billing_mock_jobs (attempt_id,provider_ref,bill_id,amount_cents,scenario,provider_sequence,gross_cents,refunded_cents,reversed_cents,status,polls,refund_request_id)
                         VALUES (?,?,?,?,?,1,?,0,0,?,0,NULL) ON CONFLICT DO NOTHING''',
                      (attempt['id'],attempt['provider_ref'],attempt['bill_id'],amount,scenario,gross,status))
            job=c.execute('SELECT * FROM billing_mock_jobs WHERE attempt_id=?',(attempt['id'],)).fetchone()
            if any(job[k]!=attempt[k] for k in ('provider_ref','bill_id','amount_cents','scenario')):raise ValueError('Mock provider idempotency conflict.')
        return Dispatch(attempt['provider_ref'],'uncertain' if scenario=='timeout' else 'submitted')

    def _envelope(self,c,job):
        payload={'provider':PROVIDER,'attempt_id':job['attempt_id'],'bill_id':job['bill_id'],'provider_ref':job['provider_ref'],
                 'event_id':entity_id('MOCK-COLLECTION-EVENT',job['attempt_id']+'|'+str(job['provider_sequence'])),
                 'sequence':job['provider_sequence'],'currency':'SGD','status':job['status'],
                 'gross_cents':job['gross_cents'],'refunded_cents':job['refunded_cents'],'reversed_cents':job['reversed_cents'],
                 'refund_request_id':job['refund_request_id']}
        return {'payload':payload,'signature':self.sign(c,payload)}

    def status(self,attempt_id):
        with self.repo.transaction() as c:
            suffix=' FOR UPDATE' if c.backend=='postgres' else ''
            job=c.execute('SELECT * FROM billing_mock_jobs WHERE attempt_id=?'+suffix,(attempt_id,)).fetchone()
            if not job:return None
            if job['scenario']=='reversal' and job['polls']>=1 and job['status']=='confirmed':
                c.execute("UPDATE billing_mock_jobs SET provider_sequence=2,reversed_cents=gross_cents,status='reversed' WHERE attempt_id=?",(attempt_id,))
                job=c.execute('SELECT * FROM billing_mock_jobs WHERE attempt_id=?',(attempt_id,)).fetchone()
            c.execute('UPDATE billing_mock_jobs SET polls=polls+1 WHERE attempt_id=?',(attempt_id,))
            return self._envelope(c,job)

    def refund(self,request):
        with self.repo.transaction() as c:
            existing=c.execute('SELECT payload FROM billing_mock_refunds WHERE request_id=?',(request['id'],)).fetchone()
            if existing:return json.loads(existing['payload'])
            suffix=' FOR UPDATE' if c.backend=='postgres' else ''
            job=c.execute('SELECT * FROM billing_mock_jobs WHERE attempt_id=?'+suffix,(request['attempt_id'],)).fetchone()
            if not job or job['status']=='pending' or request['amount_cents']>job['gross_cents']-job['refunded_cents']-job['reversed_cents']:
                raise ValueError('Mock refund exceeds provider-confirmed retained collection.')
            c.execute("UPDATE billing_mock_jobs SET refunded_cents=refunded_cents+?,provider_sequence=provider_sequence+1,status='refunded',refund_request_id=? WHERE attempt_id=?",
                      (request['amount_cents'],request['id'],request['attempt_id']))
            result=self._envelope(c,c.execute('SELECT * FROM billing_mock_jobs WHERE attempt_id=?',(request['attempt_id'],)).fetchone())
            c.execute('INSERT INTO billing_mock_refunds VALUES (?,?)',(request['id'],canonical_json(result)))
            return result
