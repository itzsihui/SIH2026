"""Authenticated local onboarding and optional consent. No transaction/provider connector."""
from dataclasses import replace
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from typing import Literal

from . import auth, data
from .contracts import simulation_contract
from .ledger_repository import configured_repository, entity_id

router = APIRouter(prefix='/api/v1', tags=['local identity and consent'])
bearer = HTTPBearer(auto_error=False)
CENTRES = {s.id:s for s in data.load_stalls()}
PURPOSES = {'income_baseline':'transactions:read', 'weather_impact_research':'transactions:read', 'transaction_retention':'transactions:retain'}


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Login(Strict):
    alias: str = Field(pattern=r'^[a-z][a-z0-9_-]{2,47}$')
    password: SecretStr = Field(min_length=1, max_length=128)


class Onboarding(Strict):
    centre_id: str
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    external_namespace: Literal['manual_local','wallet_sandbox']
    external_ref: SecretStr = Field(min_length=3, max_length=128)
    licence_ref: SecretStr = Field(min_length=3, max_length=128)
    evidence_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    accepted_version: str


class Review(Strict):
    status: Literal['eligible_simulation','rejected','revoked']
    # A bounded reason code avoids collecting arbitrary personal documents/text.
    reason: Literal['local_evidence_checked','insufficient_evidence','eligibility_withdrawn']


class Consent(Strict):
    purpose: Literal['income_baseline','weather_impact_research','transaction_retention']
    action: Literal['grant','revoke']
    scope: Literal['transactions:read','transactions:retain']
    retention_days: int = Field(default=0, ge=0, le=90)
    valid_days: int = Field(default=30, ge=1, le=90)


def credential(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    auth.mode()
    if not credentials or credentials.scheme.lower() != 'bearer':
        raise HTTPException(401, 'Bearer credential required.', headers={'WWW-Authenticate':'Bearer'})
    return credentials.credentials


def principal(token: str = Depends(credential)):
    with configured_repository().transaction() as c:
        return auth.authenticate(c, token)[0]


@router.post('/auth/login')
def login(req: Login):
    auth.mode()
    return auth.login(req.alias, req.password.get_secret_value())


@router.get('/auth/me')
def me(p=Depends(principal)):
    return {'principal_id':p.id, 'role':p.role, 'scopes':sorted(p.scopes), 'identity_verified':False, 'provider':'local_only'}


@router.post('/auth/refresh')
def refresh(token=Depends(credential)):
    return auth.lifecycle(token, 'refresh')


@router.post('/auth/logout')
def logout(token=Depends(credential)):
    return auth.lifecycle(token, 'logout')


@router.post('/auth/logout-all')
def logout_all(token=Depends(credential)):
    return auth.lifecycle(token, 'logout-all')


def public_onboarding(row):
    return {k:row[k] for k in ('stall_id','merchant_id','operator_id','stall_entity_id','centre_ref','gauge','psi_region','accepted_version','status')} | {
        'identity_verified':False, 'eligibility_authority':'local_simulation_review',
        'assignment_note':'Reference gauge and approximate PSI region; official assignment not verified.',
        'transactions_required':False}


@router.post('/onboarding')
def onboard(req: Onboarding, p=Depends(principal)):
    auth.require_scope(p, 'onboarding:write')
    try:
        simulation_contract(req.accepted_version)
    except (ValueError, LookupError) as exc:
        raise HTTPException(422, 'Unsupported acceptance version.') from exc
    centre = CENTRES.get(req.centre_id)
    if not centre or data.km((req.latitude,req.longitude), (centre.lat,centre.lon)) > .25:
        raise HTTPException(422, 'Location must be within 250 m of the selected reference centre.')
    if centre.gauge not in data.gauges() or centre.region not in data.REGION_CENTROIDS:
        raise HTTPException(409, 'Reference assignment unavailable.')
    external = auth.digest(req.external_ref.get_secret_value().strip())
    licence = auth.digest(req.licence_ref.get_secret_value().strip())
    if not req.external_ref.get_secret_value().strip() or not req.licence_ref.get_secret_value().strip():
        raise HTTPException(422, 'Nonempty opaque references required.')
    with configured_repository().transaction() as c:
        # Serialize duplicate references on PostgreSQL; SQLite already uses BEGIN IMMEDIATE.
        if c.backend == 'postgres':
            c.execute('SELECT pg_advisory_xact_lock(hashtext(?))', ('onboard:'+licence,))
            c.execute('SELECT pg_advisory_xact_lock(hashtext(?))', ('onboard:'+req.external_namespace+external,))
        old = c.execute('SELECT * FROM auth_onboarding WHERE (external_namespace=? AND external_ref_hash=?) OR licence_ref_hash=?', (req.external_namespace,external,licence)).fetchall()
        if old:
            row = old[0]
            same = len(old)==1 and row['owner_id']==p.id and all(row[k]==v for k,v in {
                'external_namespace':req.external_namespace, 'external_ref_hash':external, 'licence_ref_hash':licence,
                'centre_ref':req.centre_id, 'latitude':req.latitude, 'longitude':req.longitude,
                'evidence_sha256':req.evidence_sha256, 'accepted_version':req.accepted_version}.items())
            if not same:
                raise HTTPException(409, 'Onboarding reference already in use; local review required.')
            auth.require_merchant(c, p, row['merchant_id'])
            return public_onboarding(row)
        stall = 'LOCAL-STALL-' + uuid.uuid4().hex
        merchant = entity_id('MERCHANT',stall)
        operator = entity_id('OPERATOR',p.id)
        stall_entity = entity_id('STALL',stall)
        centre_id = entity_id('CENTRE','pilot|'+centre.id)
        c.execute('INSERT INTO pilot_merchants VALUES (?,?,?,?)', (merchant,'engine_local',stall,'unverified_simulation'))
        c.execute('INSERT INTO pilot_operators VALUES (?,?,?,?) ON CONFLICT DO NOTHING', (operator,'engine_local',p.id,'unverified_simulation'))
        c.execute('INSERT INTO pilot_operator_merchants VALUES (?,?)', (operator,merchant))
        c.execute('INSERT INTO pilot_centres VALUES (?,?,?) ON CONFLICT DO NOTHING', (centre_id,'pilot',centre.id))
        c.execute('INSERT INTO pilot_stalls VALUES (?,?,?,?)', (stall_entity,centre_id,'engine_local',stall))
        c.execute('INSERT INTO auth_grants VALUES (?,?,1)', (p.id,merchant))
        c.execute('INSERT INTO auth_onboarding VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (stall,merchant,operator,stall_entity,p.id,centre.id,req.latitude,req.longitude,centre.gauge,centre.region,
                   req.external_namespace,external,licence,req.evidence_sha256,req.accepted_version,'pending_review',auth.now()))
        c.audit(None, 'onboarding_submitted', {'principal_id':p.id,'stall_id':stall,'merchant_id':merchant}, auth.audit_time())
        row = c.execute('SELECT * FROM auth_onboarding WHERE stall_id=?', (stall,)).fetchone()
        return public_onboarding(row)


@router.get('/me/stalls')
def my_stalls(p=Depends(principal)):
    with configured_repository().transaction() as c:
        rows = c.execute('''SELECT o.* FROM auth_onboarding o JOIN auth_grants g ON g.merchant_id=o.merchant_id
                            WHERE g.principal_id=? AND g.active=1 ORDER BY o.stall_id''', (p.id,)).fetchall()
        return {'stalls':[public_onboarding(row) for row in rows]}


@router.get('/onboarding/{stall}')
def onboarding(stall: str, p=Depends(principal)):
    with configured_repository().transaction() as c:
        auth.stall_access(c, p, stall)
        row = c.execute('SELECT * FROM auth_onboarding WHERE stall_id=?', (stall,)).fetchone()
        if not row:
            raise HTTPException(404, 'Resource not found.')
        return public_onboarding(row)


@router.post('/onboarding/{stall}/review')
def review(stall: str, req: Review, p=Depends(principal)):
    auth.require_scope(p, 'eligibility:review')
    with configured_repository().transaction() as c:
        auth.stall_access(c,p,stall)
        row = c.execute('SELECT * FROM auth_onboarding WHERE stall_id=?', (stall,)).fetchone()
        if not row or row['owner_id']==p.id:
            raise HTTPException(403, 'Independent assigned reviewer required.')
        if (req.status,req.reason) not in {('eligible_simulation','local_evidence_checked'),('rejected','insufficient_evidence'),('revoked','eligibility_withdrawn')}:
            raise HTTPException(422, 'Review status and reason do not match.')
        c.execute('UPDATE auth_onboarding SET status=? WHERE stall_id=?', (req.status,stall))
        c.audit(None, 'local_eligibility_review', {'principal_id':p.id,'stall_id':stall,'status':req.status,'reason':req.reason}, auth.audit_time())
        row['status']=req.status
        return public_onboarding(row)


def consent_state(c, merchant, purpose):
    row = c.execute('SELECT * FROM auth_consent_events WHERE merchant_id=? AND purpose=? ORDER BY sequence DESC LIMIT 1', (merchant,purpose)).fetchone()
    return {'purpose':purpose, 'scope':PURPOSES[purpose], 'granted':bool(row and row['action']=='grant' and row['expires_at']>auth.now()),
            'expires_at':row['expires_at'] if row else None,'retention_days':row['retention_days'] if row else 0}


@router.get('/consents/{stall}')
def consents(stall: str, p=Depends(principal)):
    with configured_repository().transaction() as c:
        merchant = auth.stall_access(c,p,stall)
        return {'optional':True,'affects_fixed_cover':False,'permissions':[consent_state(c,merchant,k) for k in PURPOSES]}


@router.post('/consents/{stall}')
def consent(stall: str, req: Consent, p=Depends(principal)):
    auth.require_scope(p,'consent:write')
    if req.scope != PURPOSES[req.purpose] or (req.purpose=='transaction_retention' and req.action=='grant' and req.retention_days==0):
        raise HTTPException(422, 'Purpose/scope or retention duration mismatch.')
    if req.purpose != 'transaction_retention' and req.retention_days:
        raise HTTPException(422, 'Analysis permission does not grant retention.')
    with configured_repository().transaction() as c:
        merchant = auth.stall_access(c,p,stall)
        if c.backend == 'postgres':
            c.execute('SELECT id FROM pilot_merchants WHERE id=? FOR UPDATE', (merchant,))
        stamp = auth.now()
        c.execute('''INSERT INTO auth_consent_events (merchant_id,principal_id,purpose,action,scope,expires_at,retention_days,recorded_at)
                     VALUES (?,?,?,?,?,?,?,?)''', (merchant,p.id,req.purpose,req.action,req.scope,stamp+req.valid_days*86400,req.retention_days,stamp))
        c.audit(None,'optional_consent_'+req.action, {'principal_id':p.id,'merchant_id':merchant,'purpose':req.purpose},auth.audit_time())
        return consent_state(c,merchant,req.purpose) | {'affects_fixed_cover':False,'data_connector_available':False}


@router.get('/transaction-access/{stall}')
def transaction_access(stall: str, purpose: Literal['income_baseline','weather_impact_research','transaction_retention'], p=Depends(principal)):
    scope = PURPOSES[purpose]
    auth.require_scope(p,scope)
    with configured_repository().transaction() as c:
        merchant = auth.stall_access(c,p,stall)
        state = consent_state(c,merchant,purpose)
        if not state['granted']:
            raise HTTPException(403, 'Current purpose-specific consent required.')
        return state | {'authorized':True,'data_connector_available':False,'transactions':[]}


def resolve_stall(stall):
    if stall in CENTRES:
        return CENTRES[stall]
    with configured_repository().transaction() as c:
        row = c.execute('SELECT * FROM auth_onboarding WHERE stall_id=?', (stall,)).fetchone()
    if not row:
        raise HTTPException(404,'Resource not found.')
    return replace(CENTRES[row['centre_ref']],id=stall,lat=row['latitude'],lon=row['longitude'],gauge=row['gauge'],region=row['psi_region'])


async def protect_legacy(request: Request):
    """Complete route allowlist. New routes use explicit dependencies above.

    Demo bypass applies only to legacy representative HC stalls, never local onboarding.
    Unknown future routes remain FastAPI 404; private legacy groups are explicitly closed.
    """
    path = request.url.path
    mode = auth.mode()
    private_scope = None
    stall = None
    if path.startswith('/dash') or path in ('/engine/evaluate','/engine/replay','/events'):
        if mode != 'demo':
            raise HTTPException(403, 'Legacy global research APIs are disabled in local identity mode. Use merchant-scoped policy/history APIs.')
        return
    if path in ('/api/v1/auth/singpass','/api/v1/auth/phone-otp'):
        if mode != 'demo':
            raise HTTPException(501,'Identity provider is not connected; use local authentication.')
        return
    if path in ('/api/v1/policies','/policies','/api/v1/triggers/simulate','/api/v1/quotes','/quote'):
        try:
            body = await request.json()
            stall = body.get('stall_id','HC001') if isinstance(body,dict) else None
        except (ValueError,TypeError):
            body = {}
        private_scope = 'decision:simulate' if path.endswith('/simulate') else 'policy:enrol' if path.endswith('policies') else 'coverage:read'
    elif path.startswith('/api/v1/policy/') or path.startswith('/api/v1/payouts/'):
        stall = path.rsplit('/',1)[-1]
        private_scope = 'coverage:read'
    elif path == '/api/v1/telemetry/live':
        stall = request.query_params.get('stall_id','HC001')
        private_scope = 'coverage:read'
    if not private_scope:
        return
    if mode == 'demo' and not request.headers.get('authorization') and isinstance(stall,str) and not stall.startswith('LOCAL-'):
        return
    header = request.headers.get('authorization','')
    if not header.lower().startswith('bearer ') or len(header)>512:
        raise HTTPException(401,'Bearer credential required.',headers={'WWW-Authenticate':'Bearer'})
    with configured_repository().transaction() as c:
        p, _ = auth.authenticate(c,header[7:])
        auth.require_scope(p,private_scope)
        if not isinstance(stall,str):
            raise HTTPException(422,'A stall identifier is required.')
        auth.stall_access(c,p,stall)
        if private_scope=='policy:enrol':
            row=c.execute('SELECT status,accepted_version FROM auth_onboarding WHERE stall_id=?',(stall,)).fetchone()
            if not row or row['status']!='eligible_simulation':
                raise HTTPException(409,'Local eligibility review required before enrolment.')
            if body.get('accepted_version') != row['accepted_version']:
                raise HTTPException(422,'Acceptance version differs from reviewed onboarding.')
        request.state.principal=p
