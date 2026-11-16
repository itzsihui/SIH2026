"""DayCover+ 3.0 Simulation FastAPI Server.
Deterministic Parametric Microinsurance Engine & Mobile Gateway.
Prototype only; no insurer approval or real settlement.
"""
from __future__ import annotations
import datetime
from dataclasses import asdict, replace
from datetime import date, timezone
from pathlib import Path
from typing import List, Optional, Literal

from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict

from . import data, db, pilot_store
from .pilot import RULES as PILOT_RULES
from .contracts import M1_VERSION, catalogue, get_contract, simulation_contract
from .integration import boundaries
from .ledger_repository import LedgerUnavailable, configured_repository
from .engine import evaluate, replay, summarise
from .rules import DEFAULT_RULES, RuleSet
from . import dash, identity_api, evidence_api, lifecycle_api, billing_api, settlement_api, read_models_api
import os

app = FastAPI(
    title="DayCover+ 3.0 Parametric Microinsurance Gateway",
    description="Unified API gateway powering the deterministic climate engine and native mobile app.",
    version=PILOT_RULES.version,
)

app.include_router(dash.router)
app.include_router(identity_api.router)
app.include_router(evidence_api.router)
app.include_router(lifecycle_api.router)
app.include_router(billing_api.router)
app.include_router(settlement_api.router)
app.include_router(read_models_api.router)


@app.exception_handler(LedgerUnavailable)
async def ledger_unavailable(request, exc):
    return JSONResponse(status_code=503, content={'detail':'Local ledger unavailable or migration required.'})


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request, exc):
    # Do not echo passwords, document references, arbitrary fields or personal inputs.
    return JSONResponse(status_code=422, content={'detail':[{'loc':list(e['loc']), 'type':e['type']} for e in exc.errors()]})


@app.middleware('http')
async def identity_boundary(request: Request, call_next):
    try:
        await identity_api.protect_legacy(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={'detail':exc.detail}, headers=exc.headers)
    except LedgerUnavailable:
        return JSONResponse(status_code=503, content={'detail':'Identity ledger unavailable.'})
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("DAYCOVER_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_STALLS = {s.id: s for s in data.load_stalls()}
_EVENTS: List[dict] = []

def _rules(rain_mm: Optional[float]) -> RuleSet:
    return RuleSet(rain_daily_mm=rain_mm) if rain_mm else DEFAULT_RULES

# -----------------------------------------------------------------------------
# Pydantic Schemas
# -----------------------------------------------------------------------------

class SingpassAuthRequest(BaseModel):
    persona_id: Optional[str] = "auntie_mei"
    custom_nric: Optional[str] = None
    custom_name: Optional[str] = None

class PhoneOtpRequest(BaseModel):
    phone_number: str
    otp_code: str = "123456"

class MerchantProfile(BaseModel):
    id: str
    name: str
    stall_name: str
    hawker_centre: str
    stall_number: str
    nric_masked: str
    mobile: str
    paynow_vpa: str
    assigned_station_id: str
    assigned_station_name: str
    policy_tier: str
    preferred_language: str
    social_equity_enabled: bool
    cash_volume_pct: float
    identity_verified: bool = False
    demo_only: bool = True

class TelemetryStatus(BaseModel):
    """Latest record ON FILE (historical NEA data, not a live feed). Dates say exactly what each number is."""
    stall_id: str
    psi_region: str
    psi_value: Optional[int] = None
    psi_band: str
    psi_as_of: Optional[str] = None
    rain_gauge_id: str
    rain_mm: Optional[float] = None
    rain_as_of: Optional[str] = None
    rain_trigger_mm: float
    haze_tier1_psi: int
    haze_tier2_psi: int
    scheduled_closure_active: bool
    closure_reason: Optional[str] = None
    source_note: str

class PolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stall_id: str
    accepted_version: str
    consent: Literal[True]
    start_date: Optional[date] = None

class TriggerSimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Optional[str] = None
    peril: Literal["RAIN_70MM", "HAZE_151_ACUTE", "HAZE_201", "HAZE_101_CONSECUTIVE", "CLEANING_CLOSURE"]
    stall_id: str = "HC001"
    station_id: Optional[str] = None
    event_date: Optional[date] = None
    # Omitted values use the named demo scenario. Explicit null means missing.
    rain_daily_mm: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    psi_today: Optional[float] = Field(default=None, ge=0, le=500, allow_inf_nan=False)
    psi_yesterday: Optional[float] = Field(default=None, ge=0, le=500, allow_inf_nan=False)

class ChatRequest(BaseModel):
    message: str
    language: str = "en"
    merchant_id: Optional[str] = None

class QuoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: str = M1_VERSION
    stall_id: str
    plan: Literal["haze+rain"] = "haze+rain"

class VersionedQuoteIn(QuoteIn):
    contract_version: str = Field(...)

# -----------------------------------------------------------------------------
# Fictional demo personas (mapped to reference centres; never verified identities)
# -----------------------------------------------------------------------------

PERSONA_DATA = {
    "auntie_mei": {
        "id": "HC076",
        "name": "Tan Mei Ling (Auntie Mei)",
        "stall_name": "Ah Mei Hainanese Chicken Rice",
        "hawker_centre": "Maxwell Food Centre",
        "stall_number": "#01-28",
        "nric_masked": "SXXXX782A",
        "mobile": "+65 9123 4567",
        "paynow_vpa": "UEN: 201828192K",
        "assigned_station_id": "S117",
        "assigned_station_name": "Marina Barrage (S117)",
        "policy_tier": "HAZE_RAIN",
        "preferred_language": "zh",
        "social_equity_enabled": False,
        "cash_volume_pct": 25.0,
    },
    "uncle_huat": {
        "id": "HC096",
        "name": "Lim Ah Huat (Uncle Huat)",
        "stall_name": "Huat Huat Traditional Kopi & Toast",
        "hawker_centre": "Chinatown Complex",
        "stall_number": "#02-114",
        "nric_masked": "SXXXX194E",
        "mobile": "+65 8234 5678",
        "paynow_vpa": "NRIC: SXXXX194E",
        "assigned_station_id": "S114",
        "assigned_station_name": "Central District (S114)",
        "policy_tier": "HAZE_RAIN",
        "preferred_language": "zh",
        "social_equity_enabled": True,
        "cash_volume_pct": 80.0,
    },
    "ravi": {
        "id": "HC026",
        "name": "Ravi Shankar",
        "stall_name": "Ravi Crispy Roti Prata",
        "hawker_centre": "Tekka Centre",
        "stall_number": "#01-55",
        "nric_masked": "SXXXX432G",
        "mobile": "+65 9345 6789",
        "paynow_vpa": "UEN: 53392819X",
        "assigned_station_id": "S108",
        "assigned_station_name": "Newton / Central (S108)",
        "policy_tier": "HAZE_RAIN",
        "preferred_language": "ta",
        "social_equity_enabled": False,
        "cash_volume_pct": 30.0,
    }
}

# -----------------------------------------------------------------------------
# Health & Engine Core Endpoints
# -----------------------------------------------------------------------------

@app.get("/health")
@app.get("/api/v1/health")
def health():
    db_ok = db.is_connected()
    return {
        "ok": True,
        "status": "HEALTHY",
        "service": "DayCover+ 3.0 Engine & Mobile Gateway",
        "rule_version": PILOT_RULES.version,
        "mode": "simulation_only",
        "postgres_postgis_connected": db_ok,
        "stalls": len(_STALLS),
        "psi_days": len(data.psi_daily()),
        "rain_sample_days": len(data.rain_dates()),
        "timestamp": datetime.datetime.now(timezone.utc).isoformat()
    }

@app.get("/rules")
def rules():
    return asdict(DEFAULT_RULES)

@app.get("/api/v1/rules")
def pilot_rules(version: str = M1_VERSION):
    return _select_contract(version).terms["rules"]

@app.get("/stalls")
@app.get("/api/v1/stalls")
def stalls():
    return [{"id": s.id, "centre": s.centre, "lat": s.lat, "lon": s.lon, "region": s.region, "gauge": s.gauge} for s in _STALLS.values()]

def _select_contract(version):
    try:
        return simulation_contract(version)
    except (LookupError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get('/api/v1/contracts')
def contract_catalogue():
    return {'schema_version': 1, 'contracts': catalogue(),
            'approved_for_real_issuance': [], 'real_issuance_supported': False}


@app.get('/api/v1/contracts/{version}')
def contract_detail(version: str):
    try:
        entry = get_contract(version)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    detail = entry.describe()
    if entry.lifecycle == 'simulation':
        detail['terms'] = entry.terms
    return detail


@app.get('/api/v1/ledger/health')
def pilot_ledger_health():
    try:
        repository = configured_repository()
        with repository.transaction() as unit:
            unit.execute('SELECT version FROM pilot_schema_migrations WHERE version=1').fetchone()
    except (LedgerUnavailable, ValueError) as exc:
        raise HTTPException(503, 'Pilot ledger unavailable or requires migration.') from exc
    return {'ready': True, 'backend': repository.backend, 'schema_version': 7, 'mode': 'simulation_only'}


@app.get('/api/v1/integration')
def integration_boundaries():
    return boundaries()


@app.post('/api/v1/quotes', dependencies=[Depends(identity_api.bearer)])
def versioned_quote(q: VersionedQuoteIn):
    return _quote(q, legacy_default=False)


@app.post("/quote", dependencies=[Depends(identity_api.bearer)])
def quote(q: QuoteIn):
    # Retain the M1 client alias; the response makes its implicit selection visible.
    return _quote(q, legacy_default='contract_version' not in q.model_fields_set)


def _quote(q: QuoteIn, *, legacy_default: bool):
    s = _known_stall(q.stall_id)
    selected = _select_contract(q.contract_version)
    terms, r = selected.terms, selected.rules()
    return {
        "stall": s.id,
        "plan": q.plan,
        "gauge": s.gauge,
        "psi_region": s.region,
        "haze": {
            "psi_101_two_days": r.haze_tier1_payout,
            "psi_151": r.haze_tier2_payout,
            "max_paid_days": r.haze_cap_days_per_year,
            "max_paid_amount": r.haze_cap_amount_per_year
        },
        "rain": {
            "mm_per_day": r.rain_daily_mm,
            "payout": r.rain_payout,
            "once_per_year": True
        },
        "no_pay_notice": "You can lose income on a day and receive nothing: DayCover+ pays only when the published NEA reading crosses the trigger.",
        "premium": terms["annual_premium_sgd"],
        "contract": terms,
        "premium_note": "Indicative S$104/year, monthly GIRO proposed; simulation only, no collection.",
        "weekly_premium_sgd": terms["weekly_equivalent_sgd"],
        "rule_version": selected.version,
        "product_version_id": selected.version,
        "contract_sha256": selected.sha256,
        "contract_stage": selected.lifecycle,
        "quote_state": "indicative_simulation_quote",
        "policy_created": False,
        "real_policy_issued": False,
        "legacy_default_applied": legacy_default
    }

@app.post("/engine/evaluate")
def engine_evaluate(day: date = Query(..., alias="date"), stall_id: Optional[str] = None,
                    plan: str = "haze+rain", rain_mm: Optional[float] = None):
    rs = _rules(rain_mm)
    if stall_id and stall_id not in _STALLS:
        raise HTTPException(404, "unknown stall")
    targets = [replace(s, plan=plan) for s in ([_STALLS[stall_id]] if stall_id else _STALLS.values())]
    evs = []
    for s in targets:
        evs += [e.to_dict() for e in evaluate(s, day, rs)]
    _EVENTS.extend(evs)
    return {"date": day.isoformat(), "rule_version": rs.version, "events": evs, "research_only": True, "settlement_ready": False}

@app.post("/engine/replay")
def engine_replay(start: date, end: date, plan: str = "haze+rain", rain_mm: Optional[float] = None, stall_id: Optional[str] = None):
    if end < start:
        raise HTTPException(422, "end before start")
    rs = _rules(rain_mm)
    if stall_id and stall_id not in _STALLS:
        raise HTTPException(404, "unknown stall")
    targets = [replace(s, plan=plan) for s in ([_STALLS[stall_id]] if stall_id else _STALLS.values())]
    evs = replay(targets, start, end, rs)
    out = summarise(evs, len(targets), (end - start).days / 365.25)
    out["research_only"] = True
    out["settlement_ready"] = False
    out["cap_period_mode"] = "legacy_calendar_year_research_only"
    out["note"] = "rain evaluated only on dates in the 701-date sample; elsewhere unknown, not zero"
    return out

@app.get("/events")
def events(limit: int = 100):
    return _EVENTS[-limit:]

# -----------------------------------------------------------------------------
# Mobile App Native Endpoints
# -----------------------------------------------------------------------------

@app.post("/api/v1/auth/singpass", response_model=MerchantProfile)
def singpass_auth(req: SingpassAuthRequest):
    p = dict(PERSONA_DATA.get(req.persona_id, PERSONA_DATA["auntie_mei"]))
    st = _STALLS.get(p["id"])
    if st:  # use the real stall record, not the persona's label
        p["hawker_centre"] = st.centre
        p["assigned_station_id"] = st.gauge
        p["assigned_station_name"] = f"NEA rain gauge {st.gauge}"
    # Fake personas never reflect submitted personal details. Explicit demo mode only.
    return MerchantProfile(**p)

@app.post("/api/v1/auth/phone-otp", response_model=MerchantProfile)
def phone_otp_auth(req: PhoneOtpRequest):
    p = dict(PERSONA_DATA["auntie_mei"])
    # No phone or OTP verification is performed; do not reflect personal input.
    return MerchantProfile(**p)

@app.get("/api/v1/hawker-centres")
def get_hawker_centres():
    stalls_list = stalls()
    return {"total": len(stalls_list), "centres": stalls_list}

def _psi_band(v: Optional[float]) -> str:
    if v is None:
        return "no reading"
    return "Good" if v <= 50 else "Moderate" if v <= 100 else "Unhealthy" if v <= 200 else "Very unhealthy" if v <= 300 else "Hazardous"

@app.get("/api/v1/telemetry/live", dependencies=[Depends(identity_api.bearer)], response_model=TelemetryStatus)
def get_live_telemetry(stall_id: str = "HC001"):
    stall = _known_stall(stall_id)
    r = _select_contract(M1_VERSION).rules()
    psi_all = data.psi_daily()
    last_psi_day = max(psi_all) if psi_all else None
    psi_v = psi_all[last_psi_day].get(stall.region) if last_psi_day else None
    rain_day, rain_mm = None, None
    tab = data.rain_daily_table()
    for d in sorted(data.rain_dates(), reverse=True):
        row = tab.get((d, stall.gauge))
        if row and row["valid"]:
            rain_day, rain_mm = d, row["mm"]
            break
    is_closed, reason = db.is_centre_closed_on_date(stall.centre, date.today()) if db.is_connected() else (False, None)
    return TelemetryStatus(
        stall_id=stall.id, psi_region=stall.region, psi_value=int(psi_v) if psi_v is not None else None,
        psi_band=_psi_band(psi_v), psi_as_of=last_psi_day.isoformat() if last_psi_day else None,
        rain_gauge_id=stall.gauge, rain_mm=rain_mm, rain_as_of=rain_day.isoformat() if rain_day else None,
        rain_trigger_mm=r.rain_daily_mm, haze_tier1_psi=r.haze_tier1_psi, haze_tier2_psi=r.haze_tier2_psi,
        scheduled_closure_active=is_closed, closure_reason=reason,
        source_note="Latest record on file from NEA historical data (PSI to Oct 2026; rain from the sampled dates). The live feed is not connected yet.")

def _known_stall(stall_id):
    return _STALLS[stall_id] if stall_id in _STALLS else identity_api.resolve_stall(stall_id)


def _pilot_call(fn, *args):
    try:
        return fn(*args)
    except LedgerUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/v1/contract")
def pilot_contract(version: str = M1_VERSION):
    return _select_contract(version).terms


@app.post("/policies", dependencies=[Depends(identity_api.bearer)])
@app.post("/api/v1/policies", dependencies=[Depends(identity_api.bearer)])
def create_policy(req: PolicyCreate):
    stall = _known_stall(req.stall_id)
    selected = _select_contract(req.accepted_version)
    return _pilot_call(pilot_store.enrol, req.stall_id, req.start_date or pilot_store.today_sgt(), stall.gauge, stall.region, selected.version)


@app.post("/api/v1/triggers/simulate", dependencies=[Depends(identity_api.bearer)])
def simulate_trigger(req: TriggerSimulateRequest):
    stall = _known_stall(req.stall_id)
    enrolled = _pilot_call(pilot_store.policy, stall.id)
    if req.station_id is not None and req.station_id != enrolled["contract"]["assigned_gauge"]:
        raise HTTPException(422, "Use the policy assigned gauge; demo does not invent fallback readings.")
    day = req.event_date or pilot_store.today_sgt()
    if day > pilot_store.today_sgt():
        raise HTTPException(422, "Future weather cannot be evaluated.")
    rain = req.rain_daily_mm if 'rain_daily_mm' in req.model_fields_set else 74.5
    psi = req.psi_today if 'psi_today' in req.model_fields_set else (122 if req.peril == 'HAZE_101_CONSECUTIVE' else 159)
    yesterday = req.psi_yesterday if 'psi_yesterday' in req.model_fields_set else 118
    closed = req.peril == 'CLEANING_CLOSURE' or day in stall.closures
    result = _pilot_call(pilot_store.simulate, stall.id, day,
                         'haze' if req.peril.startswith('HAZE') else 'rain',
                         rain, psi, yesterday, closed, stall.gauge, stall.region, req.contract_version)
    result['remaining_coverage'] = _pilot_call(pilot_store.policy, stall.id)
    return result


@app.get("/api/v1/payouts/{stall_id}", dependencies=[Depends(identity_api.bearer)])
def get_payouts(stall_id: str):
    _known_stall(stall_id)
    return _pilot_call(pilot_store.history, stall_id)


@app.get("/api/v1/policy/{stall_id}", dependencies=[Depends(identity_api.bearer)])
def get_policy(stall_id: str):
    _known_stall(stall_id)
    return _pilot_call(pilot_store.policy, stall_id)

@app.post("/api/v1/concierge/chat")
def concierge_chat(req: ChatRequest):
    """Read-only explainer. Answers come from the locked rule values; it cannot trigger, size, approve or deny a payout."""
    r = _select_contract(M1_VERSION).rules()
    msg = req.message.lower()
    if any(k in msg for k in ("rain", "storm")):
        reply = (f"Rain cover pays S${r.rain_payout:.0f} once per policy year when your assigned NEA gauge records {r.rain_daily_mm:.0f} mm or more in one calendar day. "
                 "Only that gauge counts: you can lose income on a day and receive nothing.")
    elif any(k in msg for k in ("haze", "psi")):
        reply = (f"Haze cover pays S${r.haze_tier1_payout:.0f} a day when the 24-hour PSI in your region is {r.haze_tier1_psi} or more on 2 days in a row, "
                 f"or S${r.haze_tier2_payout:.0f} on any day at {r.haze_tier2_psi} or more. Up to {r.haze_cap_days_per_year} paid days a year "
                 f"(S${r.haze_cap_amount_per_year:.0f} cap in the simulation contract).")
    elif any(k in msg for k in ("heat", "wbgt", "flood")):
        reply = "Heat and flood are only being logged for study. They do not pay anything."
    elif any(k in msg for k in ("cost", "premium", "pay ", "price")):
        reply = ("The indicative price is S$104/year (S$2/week equivalent), billed monthly: eight S$8.67 and four S$8.66 instalments. GIRO is proposed and not connected. "
                 "Any subsidy would be time-limited with a published end date.")
    elif any(k in msg for k in ("close", "wash", "clean", "spring")):
        reply = "On days your centre is closed for scheduled NEA cleaning or works, nothing is paid for that day and your yearly limit is not used."
    elif any(k in msg for k in ("when", "how long", "fast", "settle")):
        reply = "Each day is checked at 23:59 SGT and any payment is made the next day. In this prototype, payments are simulated."
    else:
        reply = ("I can explain how DayCover+ works: rain (70 mm), haze (PSI 101 and 151), cleaning closures, the premium, and when payments are made. "
                 "I only explain; fixed rules decide every payout.")
    return {"reply": reply, "persona": "DayCover+ explainer (read-only)", "decides_payouts": False,
            "grounding": "Locked rule set " + r.version}

# Mount React Underwriter Dashboard
_dashboard_dist = Path(__file__).resolve().parents[2] / "dashboard" / "dist"
if _dashboard_dist.exists():
    app.mount("/dashboard", StaticFiles(directory=str(_dashboard_dist), html=True), name="dashboard")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.daycover.api:app", host="0.0.0.0", port=8000, reload=True)
