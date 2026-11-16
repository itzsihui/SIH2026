"""Read-only product catalogue. Research metadata never grants execution authority.

M1 terms are loaded from the original JSON, pinned independently of research
RuleSet defaults. No approval/issuance or real-settlement operation exists here.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .rules import RuleSet
from .integration import PILOT_NAMESPACE, DECISION_AUTHORITY, SETTLEMENT_AUTHORITY

M1_VERSION = 'daycover-pilot-m1-2026.11-v1'
M1_SHA256 = 'b8e27a5a534f1697dab8a8de1fac2bfd4acad963ec87309654b2c60f8065aa6f'
CONTRACTS_DIR = Path(__file__).resolve().parents[2] / 'contracts'


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(terms: dict) -> str:
    return hashlib.sha256(canonical_json(terms).encode()).hexdigest()


@dataclass(frozen=True)
class RegisteredContract:
    version: str
    lifecycle: str
    _metadata_json: str
    _terms_json: str | None = None

    @property
    def terms(self) -> dict:
        if self._terms_json is None:
            raise ValueError('Catalogue summary only; no executable contract terms.')
        return json.loads(self._terms_json)

    @property
    def sha256(self) -> str | None:
        return fingerprint(self.terms) if self._terms_json is not None else None

    def describe(self) -> dict:
        return {**json.loads(self._metadata_json), 'contract_sha256': self.sha256}

    def rules(self) -> RuleSet:
        terms = self.terms['rules']
        # Require every field: new research defaults must not leak into old terms.
        expected = {f.name for f in fields(RuleSet)}
        if set(terms) != expected:
            raise ValueError('Contract rules schema changed; explicit version adapter required.')
        kwargs = {f.name: terms[f.name] for f in fields(RuleSet) if f.init}
        kwargs['heat_rolling_hour_c'] = tuple(kwargs['heat_rolling_hour_c'])
        result = RuleSet(**kwargs)
        if result.haze_day_definition != terms['haze_day_definition']:
            raise ValueError('Unsupported haze-day definition.')
        return result


def _load_pilot(path: Path) -> str:
    terms = json.loads(path.read_text())
    if terms.get('version') != M1_VERSION or fingerprint(terms) != M1_SHA256:
        raise ValueError('Frozen M1 terms changed; create a new version instead.')
    return canonical_json(terms)


def _load_catalogue() -> MappingProxyType:
    manifest = json.loads((CONTRACTS_DIR / 'registry.json').read_text())
    if manifest['schema_version'] != 1:
        raise ValueError('Unsupported catalogue schema.')
    records = {}
    for metadata in manifest['contracts']:
        version, lifecycle = metadata['version'], metadata['lifecycle']
        if version in records or lifecycle not in {'simulation', 'research', 'candidate_proposal', 'approved'}:
            raise ValueError('Invalid/duplicate catalogue entry.')
        # Executable adapters are code-reviewed allowlists, not a JSON flag.
        executable = version == M1_VERSION and lifecycle == 'simulation'
        if metadata['simulation_enrolment_allowed'] != executable:
            raise ValueError('Catalogue cannot enable an unsupported execution adapter.')
        if executable and (metadata['identity_namespace'], metadata['decision_authority'], metadata['settlement_authority']) != (PILOT_NAMESPACE, DECISION_AUTHORITY, SETTLEMENT_AUTHORITY):
            raise ValueError('M1 authority does not match the supported adapter.')
        terms = _load_pilot(CONTRACTS_DIR / (M1_VERSION + '.json')) if executable else None
        records[version] = RegisteredContract(version, lifecycle, canonical_json(metadata), terms)
    if M1_VERSION not in records:
        raise ValueError('M1 contract missing from catalogue.')
    return MappingProxyType(records)


_REGISTRY = _load_catalogue()


def get_contract(version: str) -> RegisteredContract:
    try:
        return _REGISTRY[version]
    except KeyError as exc:
        raise LookupError(f'Unknown contract version: {version}') from exc


def catalogue() -> list[dict]:
    return [entry.describe() for entry in _REGISTRY.values()]


def simulation_contract(version: str) -> RegisteredContract:
    entry = get_contract(version)
    if entry.version != M1_VERSION or entry.lifecycle != 'simulation' or entry._terms_json is None:
        raise ValueError('Version is research/proposal only; simulation enrolment is not supported.')
    return entry


def validate_snapshot(snapshot: dict) -> RegisteredContract:
    """Accept original M1 rows too, without rewriting their accepted snapshot."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('version'), str):
        raise ValueError('Invalid accepted contract snapshot.')
    if any(not isinstance(snapshot.get(key), str) or not snapshot[key] for key in ('assigned_gauge', 'psi_region')):
        raise ValueError('Accepted reference assignment missing; review required.')
    try:
        entry = simulation_contract(snapshot['version'])
    except LookupError as exc:
        raise ValueError('Unknown accepted version; review required.') from exc
    terms = {k: v for k, v in snapshot.items() if k not in {'assigned_gauge', 'psi_region', 'contract_sha256'}}
    if fingerprint(terms) != entry.sha256:
        raise ValueError('Accepted contract snapshot differs from its registered version; review required.')
    if snapshot.get('contract_sha256', entry.sha256) != entry.sha256:
        raise ValueError('Accepted contract fingerprint mismatch.')
    return entry
