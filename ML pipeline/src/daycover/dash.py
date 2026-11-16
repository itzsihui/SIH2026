"""Insurer dashboard endpoints (read-only, Postgres-backed). The LLM only explains flags the rules already produced."""
from __future__ import annotations
import json, os, statistics, urllib.request
from datetime import date
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from . import data, db

router = APIRouter(prefix="/dash", tags=["dashboard"])
ROOT = Path(__file__).resolve().parents[2]
OLLAMA = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct-2507-q4_K_M")
PREMIUM_WEEKLY = 2.0  # assumption, same as backtest


def q(sql: str, params=()):
    try:
        with db.get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception as e:
        raise HTTPException(503, f"database unavailable: {e}")


@router.get("/portfolio")
def portfolio():
    stalls = q("select id, centre_name, lat, lon, assigned_gauge_id as gauge, psi_region as region, plan from stalls order by id")
    gauges = [{"id": g, "lat": c[0], "lon": c[1]} for g, c in data.gauges().items()]
    centroids = [{"region": r, "lat": c[0], "lon": c[1]} for r, c in data.REGION_CENTROIDS.items()]
    return {"stalls": stalls, "gauges": gauges, "region_centres": centroids,
            "note": "PSI regions are drawn as nearest region centres: an approximation of NEA boundaries"}


@router.get("/dates")
def dates():
    rain = [d.isoformat() for d in sorted(data.rain_dates())]
    top = q("""select event_date::text d, count(*) n, sum(amount) amt from trigger_events
               where status='paid' and peril='haze' group by 1 order by amt desc limit 12""")
    return {"rain_sample_dates": rain, "top_haze_days": top}


@router.get("/day")
def day(date_: date = Query(..., alias="date")):
    """Everything the map needs for one date: PSI per region, rain per gauge, events, accumulation."""
    d = date_.isoformat()
    psi = q("""select station_id region, value::float v from readings
               where metric='psi_24hr_daily_max' and (observed_at at time zone 'Asia/Singapore')::date = %s""", (d,))
    rain = q("""select station_id gauge, value::float mm, is_valid from readings
                where metric='rain_daily_mm' and (observed_at at time zone 'Asia/Singapore')::date = %s""", (d,))
    ev = q("""select peril, status, count(*) n, coalesce(sum(amount),0)::float amt from trigger_events
              where event_date = %s group by 1,2 order by 1,2""", (d,))
    paid_by_stall = q("""select stall_id, sum(amount)::float amt from trigger_events
                         where event_date=%s and status='paid' group by 1""", (d,))
    n = q("select count(*) c from stalls")[0]["c"]
    paid_n = len(paid_by_stall); paid_amt = sum(x["amt"] for x in paid_by_stall)
    return {"date": d, "psi": psi, "rain": rain, "events": ev, "paid_stalls": paid_by_stall,
            "accumulation": {"policies": n, "stalls_paid": paid_n, "share": round(paid_n / n, 3) if n else 0,
                             "payout_sgd": paid_amt, "weekly_premium_pool_sgd": round(n * PREMIUM_WEEKLY, 2),
                             "payout_vs_one_week_premium": round(paid_amt / (n * PREMIUM_WEEKLY), 1) if n else 0}}


@router.get("/accumulation/series")
def accumulation_series(start: date, end: date):
    rows = q("""select event_date::text d, count(distinct stall_id) stalls, sum(amount)::float amt
                from trigger_events where status='paid' and event_date between %s and %s group by 1 order by 1""", (start, end))
    cum, out = 0.0, []
    for r in rows:
        cum += r["amt"]; out.append({**r, "cumulative_sgd": cum})
    return {"start": start.isoformat(), "end": end.isoformat(), "series": out,
            "note": "historical replay under the locked rules; not live policy data"}


@router.get("/backtest")
def backtest():
    p = ROOT / "public" / "data" / "backtest_results.json"
    if not p.exists():
        raise HTTPException(404, "run scripts/backtest_simulator.py first")
    return json.loads(p.read_text())


def _anomalies(d: date):
    rain = {r["gauge"]: r["mm"] for r in q("""select station_id gauge, value::float mm from readings where metric='rain_daily_mm'
              and is_valid and (observed_at at time zone 'Asia/Singapore')::date = %s""", (d,))}
    if not rain:
        return None, []
    out = []
    for s in q("select id, centre_name, lat, lon, assigned_gauge_id g from stalls order by id"):
        mine = rain.get(s["g"])
        if mine is None:
            continue
        near = [(g, dist) for g, dist in data.nearest_gauges(s["lat"], s["lon"], 6) if g != s["g"] and dist <= 5 and g in rain]
        if len(near) < 2:
            continue
        med = statistics.median(rain[g] for g, _ in near)
        kind = None
        if mine >= 70 and med < 25:
            kind = "isolated_trigger"          # assigned gauge pays, neighbours dry: possible false trigger
        elif mine < 35 and med >= 70:
            kind = "missed_trigger"            # neighbours heavy, assigned gauge misses: possible missed loss
        if kind:
            out.append({"stall_id": s["id"], "centre": s["centre_name"], "kind": kind, "assigned_gauge": s["g"],
                        "assigned_mm": mine, "neighbour_median_mm": round(med, 1),
                        "neighbours": [{"gauge": g, "km": round(k, 2), "mm": rain[g]} for g, k in near]})
    return rain, out


@router.get("/anomalies")
def anomalies(date_: date = Query(..., alias="date")):
    rain, flags = _anomalies(date_)
    if rain is None:
        return {"date": date_.isoformat(), "available": False, "flags": [],
                "note": "no rain readings for this date (only the 701 sampled dates exist)"}
    return {"date": date_.isoformat(), "available": True, "flags": flags,
            "rule": "isolated_trigger: assigned >=70 mm and median of neighbours within 5 km <25 mm; missed_trigger: assigned <35 mm and neighbour median >=70 mm"}


def _template(d: str, flags: list) -> str:
    if not flags:
        return f"{d}: no basis-risk divergence flagged by the rules."
    a = flags[0]
    return (f"{d}: {len(flags)} stalls show gauge divergence. Example: {a['centre']} is assigned gauge {a['assigned_gauge']} reading "
            f"{a['assigned_mm']:.0f} mm while neighbours within 5 km read a median of {a['neighbour_median_mm']} mm ({a['kind'].replace('_', ' ')}). "
            "Rules, not this text, decide payouts; an underwriter should review the affected policies.")


@router.post("/anomalies/explain")
def explain(date_: date = Query(..., alias="date")):
    rain, flags = _anomalies(date_)
    if rain is None:
        raise HTTPException(404, "no rain readings for this date")
    d = date_.isoformat()
    sample = flags[:8]
    prompt = ("You are a read-only diagnostic assistant for an insurance underwriter. Using ONLY the JSON below, write a short "
              "(max 120 words) basis-risk divergence report: how many stalls are flagged, split by kind, the most extreme example with "
              "its numbers, and one line on what an underwriter should check. Do not invent numbers. Do not say any payout was approved, "
              "denied or changed; payouts are decided by fixed rules.\n" + json.dumps({"date": d, "total_flags": len(flags), "examples": sample}))
    text, source = None, "template"
    try:
        req = urllib.request.Request(f"{OLLAMA}/api/generate", method="POST", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                                                      "options": {"temperature": 0.1, "num_predict": 260}}).encode())
        text = json.load(urllib.request.urlopen(req, timeout=90)).get("response", "").strip() or None
        source = f"ollama:{OLLAMA_MODEL}" if text else "template"
    except Exception:
        text = None
    return {"date": d, "total_flags": len(flags), "report": text or _template(d, flags), "source": source,
            "disclaimer": "Explanation only. Payouts are decided by the deterministic rules."}


@router.get("/status")
def status():
    """Live database facts for the dashboard header (counts come from Postgres, not constants)."""
    c = q("""select (select count(*) from stalls) stalls, (select count(*) from readings) readings,
                    (select count(*) from trigger_events) events, (select count(*) from centre_closures) closures""")[0]
    ev = q("select min(event_date)::text lo, max(event_date)::text hi from trigger_events where status in ('paid','capped','excluded')")[0]
    rd = q("""select max((observed_at at time zone 'Asia/Singapore')::date)::text psi_to from readings where metric='psi_24hr_daily_max'""")[0]
    return {"database": "connected", **c, "events_from": ev["lo"], "events_to": ev["hi"], "psi_data_to": rd["psi_to"]}


@router.get("/closures")
def closures(year: int = 2026, limit: int = 40, from_date: Optional[date] = None):
    """Published NEA closure calendar for one year, merged into consecutive-day windows per centre."""
    rows = q("""select centre_name, closure_type, closure_date, description from centre_closures
                where extract(year from closure_date) = %s order by centre_name, closure_type, closure_date""", (year,))
    out, cur = [], None
    for r in rows:
        if cur and cur["centre"] == r["centre_name"] and cur["type"] == r["closure_type"] and (r["closure_date"] - cur["_last"]).days == 1:
            cur["end"], cur["_last"] = r["closure_date"].isoformat(), r["closure_date"]
            continue
        cur = {"centre": r["centre_name"], "type": r["closure_type"], "start": r["closure_date"].isoformat(),
               "end": r["closure_date"].isoformat(), "description": r["description"], "_last": r["closure_date"]}
        out.append(cur)
    for o in out:
        o.pop("_last")
    if from_date:
        out = [o for o in out if o["end"] >= from_date.isoformat()]
    out.sort(key=lambda o: (o["start"], o["centre"]))
    return {"year": year, "total_windows": len(out), "total_days": len(rows), "windows": out[:limit],
            "note": "Closure days are never paid and never use the yearly limit. Calendar as published by NEA for the stated year."}
