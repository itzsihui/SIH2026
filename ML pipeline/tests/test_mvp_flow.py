"""MVP flow on sample fixtures: onboarding grant -> transactions -> premium collection -> weather trigger -> claim decision ->
simulated payout -> dashboard. Rules decide; ML only advises; everything is a local mock."""
import json
import os
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from src.daycover import auth, billing, explanations as ex, read_models, settlement, collection_accrual as acc
from src.daycover.api import app
from test_read_models import prepared, view
from test_settlement import queued, rows
from test_evidence_engine import DAY, NOW

FX = json.loads(Path("tests/fixtures/mvp_sample.json").read_text())
START = date(2026, 11, 15)
END = date(2027, 11, 14)


def hdr(t):
    return {"Authorization": "Bearer " + t}


def consent(client, h, stall="HC076"):
    return client.post(f"/api/v1/consents/{stall}", headers=h, json={"purpose": "transaction_retention", "action": "grant",
                                                                    "scope": "transactions:retain", "retention_days": 30, "valid_days": 30})


@pytest.fixture
def stack(ledger_backend, tmp_path, monkeypatch):
    monkeypatch.setenv("DAYCOVER_AUTH_MODE", "local")
    repo = ledger_backend
    owner, reviewer, service, p, tid, rid, oid = prepared(repo)
    c = TestClient(app)
    cust = hdr(auth.login("settlement_owner", "local-owner-test-password")["access_token"])
    svc = hdr(auth.issue_service(service, ["coverage:read", "transactions:read", "transactions:retain", "billing:collect"])["access_token"])
    return dict(repo=repo, owner=owner, reviewer=reviewer, service=service, p=p, tid=tid, rid=rid, oid=oid, c=c, cust=cust, svc=svc)


def test_end_to_end_mvp_flow(stack):
    s = stack
    c, tid = s["c"], s["tid"]
    ingest = f"/api/v1/transactions/HC076/{tid}/ingest"
    body = {"simulation_only": True, "transactions": FX["transactions"]}
    # 1 onboarding/consent: without consent nothing accrues and fixed cover is unaffected
    r = c.post(ingest, headers=s["svc"], json=body).json()
    assert r["consent_granted"] is False and {x["outcome"] for x in r["results"]} == {"ignored"}
    assert c.get(f"/api/v1/collections/HC076/{tid}", headers=s["cust"]).json()["accrued_cents"] == 0
    assert consent(c, s["cust"]).status_code == 200
    # 2 transactions -> accrual (digital only, idempotent, refund reverses)
    r = c.post(ingest, headers=s["svc"], json=body).json()
    by = {(x["provider_event_id"], i): x for i, x in enumerate(r["results"])}
    outcomes = [x["outcome"] for x in r["results"]]
    assert outcomes == ["accrued", "accrued", "accrued", "ignored", "duplicate", "reversed"]
    assert [x["accrued_cents"] for x in r["results"]] == [10, 20, 40, 0, 10, -20] and r["results"][3]["reason"].startswith("cash")
    # 3 premium collection: accrued is not collected; confirmed mock receipts are
    sm = c.get(f"/api/v1/collections/HC076/{tid}", headers=s["cust"]).json()
    assert sm["accrued_cents"] == 50 and sm["confirmed_collected_cents"] == 0 and sm["real_collected_cents"] == 0
    assert sm["contractual_premium_owed_cents"] == 10400 and sm["current_week"]["cap_cents"] == 200
    conf = f"/api/v1/collections/HC076/{tid}/confirm"
    assert c.post(conf, headers=s["cust"], json={"simulation_only": True, "provider_ref": "R1", "cycle_index": 0, "amount_cents": 50}).status_code == 403
    assert c.post(conf, headers=s["svc"], json={"simulation_only": True, "provider_ref": "R2", "cycle_index": 0, "amount_cents": 51}).status_code == 409
    assert c.post(conf, headers=s["svc"], json={"simulation_only": True, "provider_ref": "R1", "cycle_index": 0, "amount_cents": 50}).json()["outcome"] == "confirmed"
    sm = c.get(f"/api/v1/collections/HC076/{tid}", headers=s["cust"]).json()
    assert sm["confirmed_collected_cents"] == 50 and sm["unpaid_balance_cents"] == 10350
    # 4 weather trigger -> deterministic claim decision (frozen M1: PSI 151 -> S$60) is untouched by sales or collection
    v = view(s["repo"], s["owner"], tid)
    haze = next(d for d in v["decisions"] if d["peril"] == "haze")
    assert haze["status"] == "TRIGGERED" and haze["target_entitlement_sgd"] == 60.0
    assert v["coverage"]["remaining"]["combined_cents"] == 12000 and v["policy"]["accepted_version"] == "daycover-pilot-m1-2026.11-v1"
    # 5 ML advisory only: a recommendation changes nothing
    from src.daycover.recommendation import recommend, load_config
    import pandas as pd
    daily = pd.DataFrame({"merchant_id": "M", "trading_day": pd.date_range("2026-09-01", periods=60).date.astype(str), "digital_cents": 9000})
    psi = pd.DataFrame({"date": pd.date_range("2020-01-01", "2022-12-31").date.astype(str), "south": 60.0})
    assert recommend("M", "south", "2026-11-15", daily, psi, True, load_config())["advisory_only"]
    assert view(s["repo"], s["owner"], tid)["state_sha256"] == v["state_sha256"]
    # 6 simulated payout through the mock settlement provider
    iid = queued(s["repo"], tid, s["rid"], s["oid"], s["service"], scenario="reversal")
    settlement.dispatch("HC076", tid, iid, s["service"], s["repo"], now=NOW)
    settlement.reconcile("HC076", tid, iid, s["repo"], now=NOW)
    v2 = view(s["repo"], s["owner"], tid)
    assert v2["settlement"]["summary"]["confirmed_mock_cents"] == 6000 and v2["boundaries"]["real_paid_cents"] == 0
    assert "no real money moved" in ex.explain(v2)["text"]
    # 7 dashboard
    d = c.get("/api/v1/dashboard/portfolio", headers=s["svc"])
    assert d.status_code == 200 and c.get("/api/v1/dashboard/portfolio", headers=s["cust"]).status_code == 403
    d = d.json()
    assert d["policies"]["policies"] == 1 and d["policies"]["by_version"] == {"daycover-pilot-m1-2026.11-v1": 1}
    assert d["decisions"]["net_entitlement_cents"] == 6000 and d["payouts_mock"]["confirmed_mock_cents"] == 6000
    assert d["payouts_mock"]["real_paid_cents"] == 0 and d["premium_mock"]["real_collected_cents"] == 0 and d["rules_decide_ml_advises"]


def test_cash_heavy_hawker_keeps_fixed_cover_and_billing(stack):
    s = stack
    sm = s["c"].get(f"/api/v1/collections/HC076/{s['tid']}", headers=s["cust"]).json()
    assert sm["accrued_cents"] == 0 and "fixed monthly" in sm["alternatives"]
    bill = billing.statement("HC076", s["tid"], s["repo"], as_of=NOW.date())
    assert bill["summary"]["annual_obligation_cents"] == 10400
    assert view(s["repo"], s["owner"], s["tid"])["coverage"]["remaining"]["combined_cents"] == 12000


def test_cross_merchant_and_role_isolation(stack):
    s = stack
    stranger = auth.provision("mvp_stranger", "customer", "local-stranger-password")
    t = hdr(auth.login("mvp_stranger", "local-stranger-password")["access_token"])
    c, tid = s["c"], s["tid"]
    assert c.get(f"/api/v1/collections/HC076/{tid}", headers=t).status_code == 404
    assert c.post(f"/api/v1/transactions/HC076/{tid}/ingest", headers=t, json={"simulation_only": True, "transactions": FX["transactions"][:1]}).status_code in (403, 404)
    assert c.post(f"/api/v1/transactions/HC076/{tid}/ingest", headers=s["cust"], json={"simulation_only": True, "transactions": FX["transactions"][:1]}).status_code == 403
    assert c.post(f"/api/v1/transactions/HC076/{tid}/ingest", headers=s["svc"], json={"transactions": FX["transactions"][:1]}).status_code == 422
    assert c.get("/api/v1/collections/HC076/x-term", headers=s["cust"]).status_code == 404


# ---------------------------------------------------------------- accrual unit rules (no ledger needed)

def mk(repo):
    return acc.AccrualStore(repo)


def sale(i, day, amount=1_000_000, channel="sgqr_nets_sim"):
    return {"provider_event_id": f"E{i}", "kind": "sale", "channel": channel, "timestamp_sgt": f"{day}T12:00:00+08:00", "amount_cents": amount}


def test_weekly_cap_cycle_instalment_and_annual_never_exceeded(ledger_backend):
    s = mk(ledger_backend)
    ing = lambda i, day, annual=10400: s.ingest("T", START, END, annual, sale(i, day), True)
    a = ing(1, "2026-11-16")
    assert a["accrued_cents"] == 200 and a["limited_by"] == "weekly_cap"
    assert ing(2, "2026-11-17")["accrued_cents"] == 0                      # cap reached: stop collecting this week
    assert ing(3, "2026-11-23")["accrued_cents"] == 200                    # new week
    assert ing(4, "2026-12-13")["cycle_index"] == 1                        # day 28 starts the next four-week cycle
    # annual 8700: weekly cap 168 but instalment 669 -> the 4th week of a cycle is limited by the instalment
    s2 = s
    got = [s2.ingest("U", START, END, 8700, sale(i, d), True) for i, d in enumerate(("2026-11-16", "2026-11-23", "2026-11-30", "2026-12-07"))]
    assert [g["accrued_cents"] for g in got] == [168, 168, 168, 165] and got[3]["limited_by"] == "cycle_instalment"
    assert s2.summary("U", START, 8700, date(2026, 12, 20))["cycles"][0]["accrued_cents"] == 669
    sc = acc.schedule(START, 8700)
    assert sc["sum_check"] == 8700 and sc["weekly_cap_cents"] == 168 and len(sc["cycles"]) == 13
    # annual premium bound: nothing accrues beyond the contractual premium
    s3 = s
    total = sum(s3.ingest("V", START, END, 400, sale(i, date.fromordinal(START.toordinal() + 7 * i + 1).isoformat()), True)["accrued_cents"] for i in range(40))
    assert total <= 400


def test_accrual_idempotent_cash_excluded_outside_term_and_refund_bounds(ledger_backend):
    s = mk(ledger_backend)
    t = sale(1, "2026-11-16", 1000)
    assert s.ingest("T", START, END, 10400, t, True)["accrued_cents"] == 20
    assert s.ingest("T", START, END, 10400, t, True)["outcome"] == "duplicate"
    assert s.ingest("T", START, END, 10400, sale(2, "2026-11-16", 1000, "cash_sim"), True)["reason"].startswith("cash")
    assert s.ingest("T", START, END, 10400, sale(3, "2027-12-01", 1000), True)["reason"] == "outside_policy_term"
    big_refund = {**t, "provider_event_id": "RF", "kind": "refund", "original_event_id": "E1", "amount_cents": 99999}
    assert s.ingest("T", START, END, 10400, big_refund, True)["accrued_cents"] == -20
    again = {**big_refund, "provider_event_id": "RF2"}
    assert s.ingest("T", START, END, 10400, again, True)["accrued_cents"] == 0      # cannot reverse more than was accrued
    assert s.ingest("T", START, END, 10400, {**big_refund, "provider_event_id": "RF3", "original_event_id": "nope"}, True)["reason"] == "refund_without_known_original"
    with pytest.raises(ValueError):
        s.ingest("T", START, END, 10400, {**t, "amount_cents": 0}, True)


def test_confirmed_never_exceeds_accrued_and_shortfall_becomes_arrears(ledger_backend):
    s = mk(ledger_backend)
    s.ingest("T", START, END, 10400, sale(1, "2026-11-16"), True)
    s.confirm("T", 0, 150, "P1")
    assert s.confirm("T", 0, 150, "P1")["outcome"] == "duplicate"
    with pytest.raises(ValueError):
        s.confirm("T", 0, 51, "P2")
    s.confirm("T", 0, 150, "P3", reverse=True)
    with pytest.raises(ValueError):
        s.confirm("T", 0, 1, "P4", reverse=True)
    sm = s.summary("T", START, 10400, date(2027, 1, 1))
    assert sm["confirmed_collected_cents"] == 0 and sm["accrued_cents"] == 200 and sm["arrears_cents"] > 0
    assert sm["cycles"][0]["shortfall_cents"] == 800 and sm["real_collected_cents"] == 0 and sm["simulated"]


# ---------------------------------------------------------------- v8 ledger store, suggested cap, restart safety

def test_accrual_store_is_in_canonical_ledger_and_append_only(ledger_backend):
    s = mk(ledger_backend)
    s.ingest("T8", START, END, 10400, sale(1, "2026-11-16", 1000), True)
    with ledger_backend.transaction() as c:
        assert c.execute("SELECT version FROM pilot_schema_migrations WHERE version=8").fetchone()
        assert c.execute("SELECT COUNT(*) AS n FROM collection_accrual_entries").fetchone()["n"] == 1
    with pytest.raises(Exception):
        with ledger_backend.transaction() as c:
            c.execute("UPDATE collection_accrual_entries SET amount_cents=999")
    with pytest.raises(Exception):
        with ledger_backend.transaction() as c:
            c.execute("DELETE FROM collection_accrual_entries")
    again = mk(ledger_backend)                                    # "restart": a new store object sees the same state
    assert again.ingest("T8", START, END, 10400, sale(1, "2026-11-16", 1000), True)["outcome"] == "duplicate"
    assert again.summary("T8", START, 10400, date(2026, 11, 20))["accrued_cents"] == 20


def test_suggested_weekly_cap_is_advisory_bounded_and_digital_only():
    ok = {"avg_day_cents": 20000, "avg_week_cents": 120000, "qr_share": 0.6, "days_observed": 90}
    assert acc.suggest_weekly_cap(ok, 10400, False)["reason"] == "no_consent" and acc.suggest_weekly_cap(ok, 10400, False)["weekly_cap_cents"] == 200
    assert acc.suggest_weekly_cap({**ok, "days_observed": 10}, 10400, True)["reason"] == "insufficient_digital_history"
    r = acc.suggest_weekly_cap(ok, 10400, True)
    assert r["weekly_cap_cents"] == 400 and r["reason"] == "clamped_to_band"          # 1.5% of S$1,200 = S$18 -> clamped to 2x base
    low = acc.suggest_weekly_cap({**ok, "avg_week_cents": 5000}, 10400, True)
    assert low["weekly_cap_cents"] == 200 and low["affects_premium_owed"] is False and low["affects_claims"] is False
    mid = acc.suggest_weekly_cap({**ok, "avg_week_cents": 20000}, 10400, True)
    assert mid["weekly_cap_cents"] == 300 and mid["reason"] == "within_digital_sales_band"
    assert "digital_sales_only" in mid["scope"]


def test_suggested_cap_endpoint_scope_and_consent(stack):
    s = stack
    url = f"/api/v1/collections/HC076/{s['tid']}/suggested-cap"
    body = {"simulation_only": True, "avg_day_cents": 20000, "avg_week_cents": 20000, "qr_share": 0.5, "days_observed": 60}
    r = s["c"].post(url, headers=s["svc"], json=body)
    assert r.status_code == 200 and r.json()["reason"] == "no_consent" and r.json()["weekly_cap_cents"] == 200
    assert s["c"].post(url, headers=s["cust"], json=body).status_code == 403
    assert s["c"].post(url, headers=s["svc"], json={**body, "qr_share": 2}).status_code == 422
    assert s["c"].post(url, headers=s["svc"], json={**body, "cash_share": 0.5}).status_code == 422
