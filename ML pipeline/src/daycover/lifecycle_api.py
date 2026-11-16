"""Scoped simulation lifecycle and reviewed-weather decisions; amounts are server-owned."""
from datetime import date
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from . import auth, evidence_engine, policy_lifecycle as life
from .identity_api import principal
from .ledger_repository import configured_repository

router=APIRouter(prefix='/api/v1',tags=['simulation lifecycle and decisions'])


class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class Renewal(Strict):
    start_date:date
    accepted_version:str
    consent:Literal[True]
class Transition(Strict):
    term_id:str
    action:Literal['activate_simulation','cancel_simulation','record_expiry']
    effective_on:date | None=None
class Slice(Strict):
    start:date
    end:date
class Replay(Strict):
    term_id:str
    through_day:date
class Approval(Strict):source_ref:str


def access(stall,p,scope):
    auth.require_scope(p,scope)
    with configured_repository().transaction() as c:auth.stall_access(c,p,stall)


def call(fn,*args):
    try:return fn(*args)
    except LookupError as exc:raise HTTPException(404,'Resource not found.') from exc
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc


@router.get('/lifecycle/{stall}')
def lifecycle(stall:str,p=Depends(principal)):
    access(stall,p,'coverage:read');return call(life.overview,stall)


@router.post('/lifecycle/{stall}/renew')
def renewal(stall:str,req:Renewal,p=Depends(principal)):
    access(stall,p,'policy:enrol')
    if p.role not in ('customer','operator'):raise HTTPException(403,'Customer/operator acceptance required.')
    return call(life.renew,stall,req.start_date,req.accepted_version)


@router.post('/lifecycle/{stall}/transition')
def transition(stall:str,req:Transition,p=Depends(principal)):
    access(stall,p,'policy:manage')
    return call(life.transition,stall,req.term_id,req.action,p.id,req.effective_on)


@router.get('/engine-decisions/{stall}')
def history(stall:str,p=Depends(principal)):
    access(stall,p,'coverage:read');return call(evidence_engine.history,stall)


@router.post('/engine-decisions/{stall}/evaluate')
def evaluate(stall:str,req:Slice,p=Depends(principal)):
    access(stall,p,'decision:evaluate');return call(evidence_engine.evaluate,stall,req.start,req.end)


@router.post('/engine-decisions/{stall}/replay')
def replay(stall:str,req:Replay,p=Depends(principal)):
    access(stall,p,'decision:evaluate');return call(evidence_engine.plan_replay,stall,req.term_id,req.through_day)


@router.post('/engine-decisions/{stall}/replay/{plan_id}/approve')
def approve(stall:str,plan_id:str,req:Approval,p=Depends(principal)):
    access(stall,p,'decision:review');return call(evidence_engine.approve_replay,stall,plan_id,p.id,req.source_ref)
