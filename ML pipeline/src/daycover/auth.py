"""Local-only opaque credentials and merchant grants; not Singpass/OTP verification."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid

from fastapi import HTTPException
from .ledger_repository import configured_repository

ROLES = {
    'customer': {'coverage:read', 'policy:enrol', 'onboarding:write', 'consent:write', 'billing:authorize', 'settlement:recipient'},
    'operator': {'coverage:read', 'policy:enrol', 'onboarding:write', 'consent:write', 'billing:authorize', 'settlement:recipient'},
    'reviewer': {'coverage:read', 'eligibility:review', 'policy:manage', 'decision:review', 'billing:review', 'settlement:review'},
    'service': {'coverage:read', 'decision:simulate', 'decision:evaluate', 'billing:collect', 'billing:reconcile', 'settlement:queue', 'settlement:submit', 'settlement:reconcile', 'transactions:read', 'transactions:retain'},
}
SESSION_SECONDS = 900
ABSOLUTE_SECONDS = 28800


def now():
    return int(time.time())


def audit_time():
    return datetime.fromtimestamp(now(), timezone.utc).isoformat()


def mode():
    value = os.getenv('DAYCOVER_AUTH_MODE', 'local')
    if value not in ('local', 'demo'):
        raise HTTPException(503, 'Invalid identity mode.')
    return value


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1, maxmem=67108864).hex()
    return salt + ':' + value


def verify_password(password, encoded):
    return hmac.compare_digest(password_hash(password, encoded.split(':')[0]), encoded)


# No real password; unknown aliases still perform the same expensive hash operation.
_DUMMY = password_hash(secrets.token_urlsafe(32))


def provision(alias, role, password=None):
    """Trusted local administration only. Never exposed as an HTTP role-grant route."""
    if not re.fullmatch(r'[a-z][a-z0-9_-]{2,47}', alias) or role not in ROLES:
        raise ValueError('Use a local alias (3–48 characters) and a supported role.')
    if role != 'service' and (not password or not 12 <= len(password) <= 128):
        raise ValueError('A 12–128 character password is required.')
    if role == 'service' and password:
        raise ValueError('Services use controlled scoped credentials, not passwords.')
    pid = 'LOCAL-PRINCIPAL-' + uuid.uuid4().hex
    with configured_repository().transaction() as c:
        if c.execute('SELECT id FROM auth_principals WHERE alias=?', (alias,)).fetchone():
            raise ValueError('Alias already exists.')
        c.execute('INSERT INTO auth_principals VALUES (?,?,?,?,1)', (pid, alias, role, password_hash(password) if password else None))
        c.audit(None, 'principal_provisioned', {'principal_id':pid,'role':role}, audit_time())
    return pid


@dataclass(frozen=True)
class Principal:
    id: str
    role: str
    scopes: frozenset
    credential_id: str


def _issue(c, principal, kind, scopes, ttl, family=None, absolute=None):
    stamp = now()
    if not scopes or not set(scopes) <= ROLES[principal['role']]:
        raise ValueError('Credential scopes exceed role permissions or are empty.')
    if (kind == 'service') != (principal['role'] == 'service') or not 1 <= ttl <= (86400 if kind == 'service' else SESSION_SECONDS):
        raise ValueError('Invalid credential kind or lifetime.')
    if not principal['active']:
        raise ValueError('Principal disabled.')
    token, cid = secrets.token_urlsafe(32), 'LOCAL-CREDENTIAL-' + uuid.uuid4().hex
    absolute = absolute or stamp + (86400 if kind == 'service' else ABSOLUTE_SECONDS)
    expires = min(stamp + ttl, absolute)
    if expires <= stamp:
        raise HTTPException(401, 'Session expired; sign in again.')
    c.execute('INSERT INTO auth_credentials VALUES (?,?,?,?,?,?,?,?,?,0)',
              (cid, principal['id'], digest(token), kind, json.dumps(sorted(scopes)), family or cid, stamp, expires, absolute))
    c.audit(None, 'credential_issued', {'principal_id':principal['id'],'credential_id':cid,'kind':kind}, audit_time())
    return {'access_token':token,'token_type':'bearer','expires_at':expires,'credential_id':cid,'identity_verified':False,'mode':'local_simulation'}


def issue_service(principal_id, scopes, ttl=3600, rotate=False):
    with configured_repository().transaction() as c:
        p = c.execute('SELECT * FROM auth_principals WHERE id=?', (principal_id,)).fetchone()
        if not p or p['role'] != 'service':
            raise ValueError('Service principal required.')
        if rotate:
            c.execute('UPDATE auth_credentials SET revoked=1 WHERE principal_id=?', (principal_id,))
        return _issue(c, p, 'service', scopes, ttl)


def login(alias, password):
    """Persistent alias rate limit; failure writes must commit before raising."""
    key, stamp, result = digest(alias.lower()), now(), None
    with configured_repository().transaction() as c:
        if c.backend == 'postgres':
            c.execute('SELECT pg_advisory_xact_lock(hashtext(?))', ('login:'+key,))
        limit = c.execute('SELECT * FROM auth_login_limits WHERE key_hash=?', (key,)).fetchone()
        if limit and stamp - limit['window_start'] < 900 and limit['failures'] >= 5:
            raise HTTPException(429, 'Too many attempts; try later.')
        p = c.execute('SELECT * FROM auth_principals WHERE alias=?', (alias,)).fetchone()
        valid = verify_password(password, p['password_hash'] if p and p['password_hash'] else _DUMMY)
        if valid and p and p['active'] and p['role'] != 'service':
            c.execute('DELETE FROM auth_login_limits WHERE key_hash=?', (key,))
            result = _issue(c, p, 'session', ROLES[p['role']], SESSION_SECONDS)
        else:
            failures = limit['failures'] + 1 if limit and stamp-limit['window_start'] < 900 else 1
            start = limit['window_start'] if failures > 1 else stamp
            c.execute('INSERT INTO auth_login_limits VALUES (?,?,?) ON CONFLICT(key_hash) DO UPDATE SET failures=excluded.failures,window_start=excluded.window_start', (key,failures,start))
    if not result:
        raise HTTPException(401, 'Invalid credentials.', headers={'WWW-Authenticate':'Bearer'})
    return result


def authenticate(c, token):
    row = c.execute('''SELECT a.*,p.role,p.active FROM auth_credentials a JOIN auth_principals p ON p.id=a.principal_id
                       WHERE a.token_hash=?''', (digest(token),)).fetchone()
    if not row or row['revoked'] or not row['active'] or row['expires_at'] <= now() or row['absolute_expires_at'] <= now():
        raise HTTPException(401, 'Invalid or expired credential.', headers={'WWW-Authenticate':'Bearer'})
    scopes = frozenset(json.loads(row['scopes'])) & ROLES[row['role']]
    return Principal(row['principal_id'], row['role'], scopes, row['id']), row


def require_scope(p, scope):
    if scope not in p.scopes:
        raise HTTPException(403, 'Permission required.')


def require_merchant(c, p, merchant):
    grant = c.execute('SELECT active FROM auth_grants WHERE principal_id=? AND merchant_id=?', (p.id,merchant)).fetchone()
    if not grant or not grant['active']:
        raise HTTPException(404, 'Resource not found.')


def stall_access(c, p, stall):
    row = c.execute('SELECT merchant_id FROM auth_onboarding WHERE stall_id=?', (stall,)).fetchone()
    row = row or c.execute('SELECT merchant_id FROM pilot_policies WHERE stall_id=?', (stall,)).fetchone()
    if not row:
        raise HTTPException(404, 'Resource not found.')
    require_merchant(c, p, row['merchant_id'])
    return row['merchant_id']


def set_grant(principal_id, merchant_id, active=True):
    with configured_repository().transaction() as c:
        c.execute('INSERT INTO auth_grants VALUES (?,?,?) ON CONFLICT(principal_id,merchant_id) DO UPDATE SET active=excluded.active', (principal_id,merchant_id,int(active)))
        c.audit(None, 'merchant_grant_changed', {'principal_id':principal_id,'merchant_id':merchant_id,'active':active}, audit_time())


def disable(principal_id):
    with configured_repository().transaction() as c:
        c.execute('UPDATE auth_principals SET active=0 WHERE id=?', (principal_id,))
        c.execute('UPDATE auth_credentials SET revoked=1 WHERE principal_id=?', (principal_id,))
        c.audit(None, 'principal_disabled', {'principal_id':principal_id}, audit_time())


def lifecycle(token, action):
    with configured_repository().transaction() as c:
        p, row = authenticate(c, token)
        if c.backend == 'postgres':
            # Serialize refresh/logout; recheck after acquiring the principal lock.
            c.execute('SELECT id FROM auth_principals WHERE id=? FOR UPDATE', (p.id,))
            p, row = authenticate(c, token)
        if action == 'refresh':
            if row['kind'] != 'session':
                raise HTTPException(403, 'Service credentials require local administrator rotation.')
            owner = c.execute('SELECT * FROM auth_principals WHERE id=?', (p.id,)).fetchone()
            result = _issue(c, owner, 'session', p.scopes, SESSION_SECONDS, row['family_id'], row['absolute_expires_at'])
            c.execute('UPDATE auth_credentials SET revoked=1 WHERE id=?', (p.credential_id,))
        elif action == 'logout-all':
            c.execute('UPDATE auth_credentials SET revoked=1 WHERE principal_id=?', (p.id,))
            result = {'revoked':True}
        else:
            c.execute('UPDATE auth_credentials SET revoked=1 WHERE id=?', (p.credential_id,))
            result = {'revoked':True}
        c.audit(None, 'credential_'+action, {'principal_id':p.id,'credential_id':p.credential_id}, audit_time())
        return result
