"""Part 1 read API v1. GET only; canonical merchant grants apply in demo too."""
from datetime import date
from typing import Any, Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from .identity_api import principal
from . import read_models

router = APIRouter(prefix='/api/v1/read-models', tags=['Part 1 read models v1'])


class Projection(BaseModel):
    model_config = ConfigDict(extra='allow')


class Identity(Projection):
    stall_id: str
    merchant_id: str
    operator_id: str
    stall_entity_id: str
    centre_id: str
    centre_ref: str
    identity_verified: Literal[False]


class Policy(Projection):
    policy_id: str
    term_id: str
    period_id: str
    accepted_version: str
    contract_sha256: str
    start: date
    end: date
    state: str
    event_day_state: str
    terms: dict[str,Any]


class Remaining(BaseModel):
    rain_events: int
    rain_cents: int
    haze_days: int
    haze_cents: int
    combined_cents: int


class Coverage(Projection):
    used: dict[str,Any]
    remaining: Remaining
    explanation: str


class Terms(Projection):
    schema_version: Literal['daycover.part2.v1']
    generated_at: str
    stall_id: str
    policy_id: str
    terms: list[dict[str,Any]]


class Snapshot(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['daycover.part2.v1']
    generated_at: str
    as_of_day: date
    currency: Literal['SGD']
    timezone: Literal['Asia/Singapore']
    identity: Identity
    policy: Policy
    coverage: Coverage
    weather: dict[str,Any]
    source_health: dict[str,Any]
    source_reviews: list[dict[str,Any]]
    decisions: list[dict[str,Any]]
    billing: dict[str,Any]
    settlement: dict[str,Any]
    receipts: list[dict[str,Any]]
    receipts_truncated: bool
    boundaries: dict[str,Any]
    operations: dict[str,Any] | None = None
    state_sha256: str


def invoke(fn, *args, **kwargs):
    try: return fn(*args, **kwargs)
    except LookupError as exc: raise HTTPException(404, 'Resource not found.') from exc
    except ValueError as exc: raise HTTPException(409, 'Accepted term or ledger requires review; check term/date and canonical records.') from exc


@router.get('/stalls/{stall}/terms', response_model=Terms)
def terms(stall:str, response:Response, p=Depends(principal)):
    response.headers['Cache-Control']='no-store'
    return invoke(read_models.terms, stall, p)


@router.get('/stalls/{stall}/terms/{term_id}', response_model=Snapshot, response_model_exclude_none=True)
def snapshot(stall:str, term_id:str, day:date, response:Response, p=Depends(principal)):
    response.headers['Cache-Control']='no-store'
    return invoke(read_models.snapshot, stall, term_id, day, p)


@router.get('/stalls/{stall}/terms/{term_id}/operations', response_model=Snapshot, response_model_exclude_none=True)
def operations(stall:str, term_id:str, day:date, response:Response, p=Depends(principal)):
    response.headers['Cache-Control']='no-store'
    return invoke(read_models.snapshot, stall, term_id, day, p, operations=True)
