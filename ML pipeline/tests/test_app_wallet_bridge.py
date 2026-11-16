"""Signed outbound bridge to the app sandbox: contract-exact signing, idempotency, uncertainty, eligibility, no secret leakage."""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from src.daycover import auth, settlement, app_wallet_bridge as br
from src.daycover.api import app
from src.daycover.identity_api import CENTRES
from test_read_models import prepared
from test_settlement import queued, rows, REF
from test_evidence_engine import NOW

SECRET = "unit-test-secret-not-real"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("DAYCOVER_APP_WALLET_BRIDGE", "1")
    monkeypatch.setenv("ENGINE_SHARED_SECRET", SECRET)
    monkeypatch.setenv("DAYCOVER_APP_WALLET_URL", "https://app.example.test")
    monkeypatch.setenv("DAYCOVER_AUTH_MODE", "local")


def principal(repo, pid):
    return auth.Principal(pid, "service", frozenset({"coverage:read", "settlement:submit"}), "test")


class Fake:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, json.loads(body)))
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r


def ok_response(payload, **over):
    return (200, {"ok": True, "instruction_id": payload["instruction_id"], "stall_id": "S00001", "engine_stall_id": payload["stall_id"],
                  "status": "settled", "amount": payload["gross_cents"] / 100, "currency": "SGD", "provider_ref": "DC-PAY-" + payload["instruction_id"][:20],
                  "settled_on": "2026-11-20", **over})


def setup(repo, scenario="success"):
    owner, reviewer, service, p, tid, rid, oid = prepared(repo)
    iid = queued(repo, tid, rid, oid, service, scenario=scenario)
    return dict(owner=owner, reviewer=reviewer, service=service, tid=tid, rid=rid, iid=iid, actor=principal(repo, service), repo=repo)


def test_contract_signature_string_and_header(env):
    payload = {"instruction_id": "INS-TEST-1", "stall_id": "HC001", "gross_cents": 3000, "currency": "SGD", "event_id": "EV-1"}
    assert br.canonical(payload) == "INS-TEST-1|HC001|3000|SGD|EV-1"
    assert br.sign(SECRET, payload) == hmac.new(SECRET.encode(), b"INS-TEST-1|HC001|3000|SGD|EV-1", hashlib.sha256).hexdigest()


def test_disabled_by_default_and_requires_both_settings(ledger_backend, monkeypatch):
    s = setup(ledger_backend)
    for k in ("DAYCOVER_APP_WALLET_BRIDGE", "ENGINE_SHARED_SECRET"):
        monkeypatch.delenv(k, raising=False)
    assert not br.enabled()
    with pytest.raises(br.BridgeDisabled):
        br.deliver("HC076", s["tid"], s["iid"], s["actor"], s["repo"], post=Fake((200, {})), now=NOW)
    monkeypatch.setenv("DAYCOVER_APP_WALLET_BRIDGE", "1")
    assert not br.enabled()                                           # secret still missing


def test_delivery_payload_signature_centre_name_and_no_state_change(ledger_backend, env):
    s = setup(ledger_backend)
    before = settlement.overview("HC076", s["tid"], ledger_backend, now=NOW)["summary"]
    fake = Fake()
    fake.responses = [None]
    payloads = []

    def post(url, headers, body, timeout):
        payloads.append((url, headers, json.loads(body)))
        return ok_response(json.loads(body))

    r = br.deliver("HC076", s["tid"], s["iid"], s["actor"], ledger_backend, post=post, now=NOW)
    url, headers, sent = payloads[0]
    assert url == "https://app.example.test/api/engine/payouts" and headers["X-Engine-Signature"] == br.sign(SECRET, sent)
    assert sent["instruction_id"] == s["iid"] and sent["gross_cents"] == 6000 and sent["currency"] == "SGD"
    assert sent["event_id"].startswith("EV-HAZE-2026-11-15") and sent["peril"] == "haze" and sent["reading"] == "PSI 151"
    assert sent["event_date"] == "2026-11-15" and sent["centre_name"] == CENTRES["HC076"].centre
    assert set(sent) == {"instruction_id", "stall_id", "gross_cents", "currency", "event_id", "peril", "reading", "event_date", "centre_name"}
    assert r["delivered"] and r["latest"]["status"] == "settled" and r["engine_confirmation_changed"] is False and r["real_transfer"] is False
    after = settlement.overview("HC076", s["tid"], ledger_backend, now=NOW)["summary"]
    assert after["confirmed_mock_cents"] == before["confirmed_mock_cents"] == 0       # app answer never confirms engine payouts
    audit = json.dumps(rows(ledger_backend, "pilot_audit"))
    assert SECRET not in audit and headers["X-Engine-Signature"] not in audit
    # already delivered: no second POST
    again = br.deliver("HC076", s["tid"], s["iid"], s["actor"], ledger_backend, post=post, now=NOW)
    assert again["duplicate_prevented_locally"] and len(payloads) == 1


def test_timeout_is_uncertain_retries_same_id_and_attempts_are_bounded(ledger_backend, env):
    s = setup(ledger_backend)
    seen = []

    def post(url, headers, body, timeout):
        seen.append(json.loads(body)["instruction_id"])
        raise TimeoutError("boom")

    for _ in range(br.MAX_ATTEMPTS):
        r = br.deliver("HC076", s["tid"], s["iid"], s["actor"], ledger_backend, post=post, now=NOW)
        assert r["latest"]["status"] == "uncertain" and not r["delivered"]
    assert set(seen) == {s["iid"]}                                        # always the same idempotency key
    with pytest.raises(ValueError, match="attempt limit"):
        br.deliver("HC076", s["tid"], s["iid"], s["actor"], ledger_backend, post=post, now=NOW)
    # a later success is still possible after config fix? attempts exhausted -> operator review; status readable
    st = br.delivery_status("HC076", s["tid"], s["iid"], ledger_backend)
    assert st["attempts"] == br.MAX_ATTEMPTS and not st["delivered"]


@pytest.mark.parametrize("code,expected", [(401, "failed"), (404, "failed"), (400, "failed"), (503, "uncertain"), (500, "uncertain")])
def test_http_error_mapping(ledger_backend, env, code, expected):
    s = setup(ledger_backend)
    r = br.deliver("HC076", s["tid"], s["iid"], s["actor"], ledger_backend, post=Fake((code, {"error": "x"})), now=NOW)
    assert r["latest"]["status"] == expected and not r["delivered"]


def test_rejected_and_mismatching_responses_are_not_delivered(ledger_backend, env):
    s = setup(ledger_backend)
    rej = br.deliver("HC076", s["tid"], s["iid"], s["actor"], ledger_backend,
                     post=lambda u, h, b, t: ok_response(json.loads(b), status="rejected"), now=NOW)
    assert rej["latest"]["status"] == "rejected" and not rej["delivered"]
    bad = br.deliver("HC076", s["tid"], s["iid"], s["actor"], ledger_backend, post=lambda u, h, b, t: ok_response(json.loads(b), amount=1.0), now=NOW)
    assert bad["latest"]["status"] == "response_mismatch" and not bad["delivered"]
    other = br.deliver("HC076", s["tid"], s["iid"], s["actor"], ledger_backend, post=lambda u, h, b, t: ok_response(json.loads(b), instruction_id="OTHER"), now=NOW)
    assert other["latest"]["status"] == "response_mismatch"


def test_ineligible_instruction_is_never_sent(ledger_backend, env):
    s = setup(ledger_backend)
    settlement.review_recipient("HC076", s["rid"], "revoked", s["reviewer"], REF, ledger_backend, now=NOW)
    fake = Fake((200, {}))
    with pytest.raises(ValueError, match="not currently eligible"):
        br.deliver("HC076", s["tid"], s["iid"], s["actor"], ledger_backend, post=fake, now=NOW)
    assert fake.calls == []
    with pytest.raises(LookupError):
        br.deliver("HC076", s["tid"], "unknown-instruction", s["actor"], ledger_backend, post=fake, now=NOW)


def test_amount_bounds_and_stall_map(ledger_backend, env, monkeypatch):
    ins = {"id": "I", "amount_cents": 20001, "peril": "haze", "day": "2026-11-15", "authority": json.dumps({"decision": {"peril": "haze", "evidence": {"psi_today": 151}}})}
    with pytest.raises(ValueError, match="range"):
        br.build_payload(None, "HC076", ins)
    monkeypatch.setenv("DAYCOVER_APP_STALL_MAP", json.dumps({"HC076": "S00076"}))
    assert br.build_payload(None, "HC076", {**ins, "amount_cents": 3000})["stall_id"] == "S00076"


def test_api_scope_disabled_and_status(ledger_backend, env, monkeypatch):
    s = setup(ledger_backend)
    c = TestClient(app)
    cust = {"Authorization": "Bearer " + auth.login("settlement_owner", "local-owner-test-password")["access_token"]}
    svc = {"Authorization": "Bearer " + auth.issue_service(s["service"], ["coverage:read", "settlement:submit"])["access_token"]}
    url = f"/api/v1/settlements/HC076/{s['tid']}/instructions/{s['iid']}"
    assert c.post(url + "/deliver-to-app", headers=cust, json={"simulation_only": True}).status_code == 403
    assert c.post(url + "/deliver-to-app", headers=svc, json={}).status_code == 422
    monkeypatch.delenv("ENGINE_SHARED_SECRET")
    assert c.post(url + "/deliver-to-app", headers=svc, json={"simulation_only": True}).status_code == 503
    st = c.get(url + "/app-delivery", headers=cust)
    assert st.status_code == 200 and st.json()["attempts"] == 0 and st.json()["app_sandbox_only"] is True


def test_only_bridge_and_weather_ingestion_use_http_clients():
    import ast
    from pathlib import Path
    for f in Path("src/daycover").glob("*.py"):
        tree = ast.parse(f.read_text())
        top = {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
              {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        inner = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        if f.name not in ("app_wallet_bridge.py", "weather_ingestion.py"):   # weather = inbound NEA fetch; bridge = the one outbound payout call
            assert not ({"httpx", "requests", "urllib3", "aiohttp"} & (top | inner)), f.name
