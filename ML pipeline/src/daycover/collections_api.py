"""Scoped mock transaction ingestion and transaction-linked premium accrual. Never decides claims or changes terms."""
import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from . import auth, policy_lifecycle as life, collection_accrual as acc
from .identity_api import principal, consent_state
from .ledger_repository import configured_repository
from .weather_ingestion import utcnow
from .ingestion import SGT

router = APIRouter(prefix='/api/v1', tags=['mock transactions and collection accrual'])


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Txn(Strict):
    provider_event_id: str = Field(min_length=1, max_length=120)
    kind: Literal['sale', 'refund']
    original_event_id: str | None = Field(default=None, max_length=120)
    channel: str = Field(min_length=1, max_length=40)
    timestamp_sgt: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+08:00$')
    amount_cents: StrictInt = Field(gt=0, lt=10**7)


class Batch(Strict):
    simulation_only: Literal[True]
    transactions: list[Txn] = Field(min_length=1, max_length=100)


class Confirmation(Strict):
    simulation_only: Literal[True]
    provider_ref: str = Field(min_length=1, max_length=120)
    cycle_index: int = Field(ge=0, le=12)
    amount_cents: StrictInt = Field(gt=0, lt=10**7)
    reverse: bool = False


def store():
    return acc.AccrualStore(configured_repository())


def term(stall, term_id, p, scope):
    auth.require_scope(p, scope)
    with configured_repository().transaction() as c:
        merchant = auth.stall_access(c, p, stall)
        ctx = life.term_context(c, stall, term_id=term_id)
        annual = int(round(json.loads(ctx['contract'])['annual_premium_sgd'] * 100))
        consent = bool(consent_state(c, merchant, 'transaction_retention')['granted'])
    return ctx, annual, consent


def key(ctx):
    return ctx['term_id']


@router.post('/transactions/{stall}/{term_id}/ingest')
def ingest(stall: str, term_id: str, body: Batch, p=Depends(principal)):
    try:
        ctx, annual, consent = term(stall, term_id, p, 'transactions:retain')
    except LookupError as exc:
        raise HTTPException(404, 'Resource not found.') from exc
    s, start, end = store(), date.fromisoformat(ctx['start']), date.fromisoformat(ctx['end'])
    results = []
    for t in body.transactions:
        try:
            results.append({'provider_event_id': t.provider_event_id, **s.ingest(key(ctx), start, end, annual, t.model_dump(), consent)})
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return {'simulated': True, 'consent_granted': consent, 'results': results, 'decides_claims': False}


class Summary(Strict):
    """Consented digital-sales summary from Part 1. Digital sales only; cash is never inferred."""
    simulation_only: Literal[True]
    avg_day_cents: StrictInt = Field(ge=0, lt=10**8)
    avg_week_cents: StrictInt = Field(ge=0, lt=10**9)
    qr_share: float = Field(ge=0, le=1, allow_inf_nan=False)
    days_observed: StrictInt = Field(ge=0, le=800)


@router.post('/collections/{stall}/{term_id}/suggested-cap')
def suggested_cap(stall: str, term_id: str, body: Summary, p=Depends(principal)):
    try:
        ctx, annual, consent = term(stall, term_id, p, 'transactions:read')
    except LookupError as exc:
        raise HTTPException(404, 'Resource not found.') from exc
    return acc.suggest_weekly_cap(body.model_dump(), annual, consent)


@router.get('/collections/{stall}/{term_id}')
def collection_summary(stall: str, term_id: str, p=Depends(principal)):
    try:
        ctx, annual, _ = term(stall, term_id, p, 'coverage:read')
    except LookupError as exc:
        raise HTTPException(404, 'Resource not found.') from exc
    return store().summary(key(ctx), date.fromisoformat(ctx['start']), annual, utcnow().astimezone(SGT).date())


@router.post('/collections/{stall}/{term_id}/confirm')
def confirm(stall: str, term_id: str, body: Confirmation, p=Depends(principal)):
    try:
        ctx, annual, _ = term(stall, term_id, p, 'billing:collect')
        return {'simulated': True, 'real_collected_cents': 0, **store().confirm(key(ctx), body.cycle_index, body.amount_cents, body.provider_ref, body.reverse)}
    except LookupError as exc:
        raise HTTPException(404, 'Resource not found.') from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
