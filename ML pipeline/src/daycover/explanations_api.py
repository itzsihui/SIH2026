"""Authenticated read-only explanation route. Reuses the Phase 9 snapshot (same grants, scopes and no-store caching)."""
from datetime import date
from typing import Literal
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from .identity_api import principal
from .read_models_api import invoke
from . import read_models, explanations

router = APIRouter(prefix='/api/v1/explanations', tags=['Read-only explanations'])


class Ask(BaseModel):
    message: str = Field(max_length=500)
    language: Literal['en', 'zh', 'ms', 'ta'] = 'en'


@router.get('/stalls/{stall}/terms/{term_id}')
def explain(stall: str, term_id: str, day: date, response: Response, language: Literal['en', 'zh', 'ms', 'ta'] = 'en', p=Depends(principal)):
    response.headers['Cache-Control'] = 'no-store'
    return explanations.explain(invoke(read_models.snapshot, stall, term_id, day, p), language)


@router.post('/stalls/{stall}/terms/{term_id}/ask')
def ask(stall: str, term_id: str, day: date, body: Ask, response: Response, p=Depends(principal)):
    response.headers['Cache-Control'] = 'no-store'
    return explanations.answer(invoke(read_models.snapshot, stall, term_id, day, p), body.message, body.language)
