"""Scoped mock-only billing. No actual mandate, debit, automatic retry or lapse."""
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field,StrictInt
from . import auth,billing
from .identity_api import principal
from .ledger_repository import configured_repository

router=APIRouter(prefix='/api/v1',tags=['simulation billing'])


class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class Authorization(Strict):
    action:Literal['grant','revoke']
    simulation_only:Literal[True]
class Attempt(Strict):
    bill_id:str
    idempotency_key:str=Field(min_length=1,max_length=96)
    scenario:Literal['success','partial','failed','timeout','pending','reversal']
class Refund(Strict):
    idempotency_key:str=Field(min_length=1,max_length=96)
    acknowledge_mock_only:Literal[True]
class Event(Strict):
    provider:Literal['deterministic_mock_v1']
    attempt_id:str=Field(min_length=1,max_length=200)
    bill_id:str=Field(min_length=1,max_length=200)
    provider_ref:str=Field(min_length=1,max_length=200)
    event_id:str=Field(min_length=1,max_length=200)
    sequence:StrictInt=Field(ge=1,lt=2**31)
    currency:str=Field(min_length=1,max_length=200)
    status:Literal['pending','failed','partially_collected','confirmed','refunded','reversed']
    gross_cents:StrictInt=Field(ge=0,lt=2**31)
    refunded_cents:StrictInt=Field(ge=0,lt=2**31)
    reversed_cents:StrictInt=Field(ge=0,lt=2**31)
    refund_request_id:str | None=Field(default=None,max_length=200)
class Callback(Strict):
    payload:Event
    signature:str=Field(pattern=r'^[a-f0-9]{64}$')


def access(stall,p,scope):
    auth.require_scope(p,scope)
    with configured_repository().transaction() as c:auth.stall_access(c,p,stall)


def call(fn,*args):
    try:return fn(*args)
    except LookupError as exc:raise HTTPException(404,'Resource not found.') from exc
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc


@router.get('/billing-cost-scenarios')
def scenarios():return billing.cost_scenarios()


@router.get('/billing/{stall}/{term_id}')
def statement(stall:str,term_id:str,p=Depends(principal)):
    access(stall,p,'coverage:read');return call(billing.statement,stall,term_id)


@router.post('/billing/{stall}/{term_id}/prepare')
def prepare(stall:str,term_id:str,p=Depends(principal)):
    access(stall,p,'billing:collect');return call(billing.prepare,stall,term_id)


@router.post('/billing/{stall}/{term_id}/authorization')
def authorize(stall:str,term_id:str,req:Authorization,p=Depends(principal)):
    access(stall,p,'billing:authorize');return call(billing.authorize,stall,term_id,p.id,req.action)


@router.post('/billing/{stall}/{term_id}/attempts')
def attempt(stall:str,term_id:str,req:Attempt,p=Depends(principal)):
    access(stall,p,'billing:collect');return call(billing.create_attempt,stall,term_id,req.bill_id,req.idempotency_key,req.scenario,p.id)


@router.post('/billing/{stall}/{term_id}/attempts/{attempt_id}/submit')
def submit(stall:str,term_id:str,attempt_id:str,p=Depends(principal)):
    access(stall,p,'billing:collect');return call(billing.submit,stall,term_id,attempt_id)


@router.post('/billing/{stall}/{term_id}/attempts/{attempt_id}/reconcile')
def reconcile(stall:str,term_id:str,attempt_id:str,p=Depends(principal)):
    access(stall,p,'billing:reconcile');return call(billing.reconcile,stall,term_id,attempt_id)


@router.post('/billing/{stall}/{term_id}/attempts/{attempt_id}/callback')
def callback(stall:str,term_id:str,attempt_id:str,req:Callback,p=Depends(principal)):
    access(stall,p,'billing:reconcile');return call(billing.ingest_event,stall,term_id,attempt_id,req.payload.model_dump(),req.signature)


@router.post('/billing/{stall}/{term_id}/attempts/{attempt_id}/mock-refund')
def refund(stall:str,term_id:str,attempt_id:str,req:Refund,p=Depends(principal)):
    access(stall,p,'billing:review');return call(billing.request_refund,stall,term_id,attempt_id,p.id,req.idempotency_key)
