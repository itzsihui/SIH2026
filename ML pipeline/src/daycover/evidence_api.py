"""Merchant-scoped read-only evidence. No HTTP review, build or settlement operations."""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from . import auth, daily_evidence
from .identity_api import principal
from .ledger_repository import configured_repository

router=APIRouter(prefix='/api/v1/evidence',tags=['daily evidence'])


@router.get('/{stall}/{day}')
def read_evidence(stall:str,day:date,p=Depends(principal)):
    auth.require_scope(p,'coverage:read')
    with configured_repository().transaction() as c:
        auth.stall_access(c,p,stall)
    try:
        return daily_evidence.select_evidence(stall,day,persist=False)
    except LookupError as exc:raise HTTPException(404,'Resource not found.') from exc
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc
