"""Scoped routes for delivering a queued mock settlement instruction to the app sandbox. Never confirms engine payouts."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from . import auth, app_wallet_bridge as bridge
from .identity_api import principal
from .ledger_repository import configured_repository

router = APIRouter(prefix='/api/v1', tags=['app wallet bridge (sandbox)'])


class Deliver(BaseModel):
    model_config = ConfigDict(extra='forbid')
    simulation_only: Literal[True]


@router.post('/settlements/{stall}/{term_id}/instructions/{instruction_id}/deliver-to-app')
def deliver(stall: str, term_id: str, instruction_id: str, body: Deliver, p=Depends(principal)):
    try:
        return bridge.deliver(stall, term_id, instruction_id, p)
    except bridge.BridgeDisabled as exc:
        raise HTTPException(503, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, 'Resource not found.') from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/settlements/{stall}/{term_id}/instructions/{instruction_id}/app-delivery')
def delivery(stall: str, term_id: str, instruction_id: str, p=Depends(principal)):
    auth.require_scope(p, 'coverage:read')
    with configured_repository().transaction() as c:
        auth.stall_access(c, p, stall)
    try:
        return bridge.delivery_status(stall, term_id, instruction_id)
    except LookupError as exc:
        raise HTTPException(404, 'Resource not found.') from exc
