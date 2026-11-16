"""Merchant-scoped mock settlement APIs. No real recipient, wallet or banking rail."""
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field,StrictInt
from . import auth,settlement
from .identity_api import principal
from .ledger_repository import configured_repository

router=APIRouter(prefix='/api/v1',tags=['mock settlement'])


class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class Recipient(Strict):
    mock_reference:str=Field(pattern=r'^MOCK-[A-Za-z0-9_-]{3,48}$')
class Review(Strict):
    decision:Literal['approved','revoked']
    source_ref:str=Field(min_length=3,max_length=512)
class Queue(Strict):
    outbox_id:str
    recipient_id:str
    idempotency_key:str=Field(min_length=1,max_length=96)
    scenario:Literal['success','partial','failed','timeout','pending','reversal']
class Event(Strict):
    provider:Literal['deterministic_mock_settlement_v1']
    instruction_id:str=Field(min_length=1,max_length=200)
    provider_ref:str=Field(min_length=1,max_length=200)
    recipient_id:str=Field(min_length=1,max_length=200)
    recipient_review_id:str=Field(min_length=1,max_length=200)
    currency:str=Field(min_length=1,max_length=200)
    event_id:str=Field(min_length=1,max_length=200)
    sequence:StrictInt=Field(ge=1,lt=2**31)
    status:Literal['pending','failed','confirmed','partially_confirmed','reversed']
    gross_cents:StrictInt=Field(ge=0,lt=2**31)
    reversed_cents:StrictInt=Field(ge=0,lt=2**31)
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


@router.post('/settlement-recipients/{stall}')
def register(stall:str,req:Recipient,p=Depends(principal)):
    access(stall,p,'settlement:recipient');return call(settlement.register_recipient,stall,req.mock_reference,p.id)


@router.post('/settlement-recipients/{stall}/{recipient_id}/review')
def review(stall:str,recipient_id:str,req:Review,p=Depends(principal)):
    access(stall,p,'settlement:review');return call(settlement.review_recipient,stall,recipient_id,req.decision,p.id,req.source_ref)


@router.get('/settlements/{stall}/{term_id}')
def overview(stall:str,term_id:str,p=Depends(principal)):
    access(stall,p,'coverage:read');return call(settlement.overview,stall,term_id)


@router.post('/settlements/{stall}/{term_id}/sync')
def sync(stall:str,term_id:str,p=Depends(principal)):
    access(stall,p,'settlement:queue');return call(settlement.sync,stall,term_id)


@router.post('/settlements/{stall}/{term_id}/queue')
def queue(stall:str,term_id:str,req:Queue,p=Depends(principal)):
    access(stall,p,'settlement:queue');return call(settlement.queue,stall,term_id,req.outbox_id,req.recipient_id,req.idempotency_key,req.scenario,p.id)


@router.post('/settlements/{stall}/{term_id}/instructions/{instruction_id}/submit')
def submit(stall:str,term_id:str,instruction_id:str,p=Depends(principal)):
    access(stall,p,'settlement:submit');return call(settlement.dispatch,stall,term_id,instruction_id,p.id)


@router.post('/settlements/{stall}/{term_id}/instructions/{instruction_id}/reconcile')
def reconcile(stall:str,term_id:str,instruction_id:str,p=Depends(principal)):
    access(stall,p,'settlement:reconcile');return call(settlement.reconcile,stall,term_id,instruction_id)


@router.post('/settlements/{stall}/{term_id}/instructions/{instruction_id}/callback')
def callback(stall:str,term_id:str,instruction_id:str,req:Callback,p=Depends(principal)):
    access(stall,p,'settlement:reconcile');return call(settlement.ingest_event,stall,term_id,instruction_id,req.payload.model_dump(),req.signature)
