"""Evaluate stalls on a date and replay history. Pure functions over the data layer; every event carries evidence + rule version."""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from datetime import date, timedelta
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional

from . import data
from .rules import DEFAULT_RULES, RuleSet, haze_payout, rain_daily, rain_short_storm


@dataclass
class Event:
    date: str
    stall_id: str
    peril: str            # haze | rain | rain_80_cmp | rain_short_storm
    status: str           # paid | shadow | excluded | capped | pending
    amount: float
    reason: str
    evidence: dict = field(default_factory=dict)
    rule_version: str = ""

    def to_dict(self):
        return asdict(self)


@lru_cache(maxsize=256)
def _gauges_in_range(lat: float, lon: float, radius_km: float):
    return tuple(g for g, km in data.nearest_gauges(lat, lon, len(data.gauges())) if km <= radius_km)


def rain_observation(stall: data.Stall, d: date, r: RuleSet = DEFAULT_RULES):
    """Return (gauge, valid reading, fallback used) under the policy's gauge selection rule."""
    tab = data.rain_daily_table()
    assigned = tab.get((d, stall.gauge))
    if assigned and assigned["valid"]:
        return stall.gauge, assigned, False
    for g in _gauges_in_range(stall.lat, stall.lon, r.gauge_fallback_km):
        row = tab.get((d, g))
        if row and row["valid"]:
            return g, row, True
    return None


def evaluate(stall: data.Stall, d: date, r: RuleSet = DEFAULT_RULES, ytd: Optional[Dict[str, Any]] = None,
             *, psi_history: Optional[Dict[date, Dict[str, float]]] = None) -> List[Event]:
    ytd = ytd if ytd is not None else {"haze": 0, "haze_paid": 0.0, "rain": 0}
    if "haze_paid" not in ytd:
        ytd["haze_paid"] = 0.0
    ev: List[Event] = []
    v = r.version
    closed = d in stall.closures
    wants_haze, wants_rain = "haze" in stall.plan, "rain" in stall.plan

    # --- haze (paying) ---
    psi = data.psi_daily() if psi_history is None else psi_history
    today = psi.get(d, {}).get(stall.region)
    yest = psi.get(d - timedelta(days=1), {}).get(stall.region)
    tier, amt, why = haze_payout(today, yest, r)
    if tier and wants_haze:
        evid = {"psi_today": today, "psi_yesterday": yest, "region": stall.region, "tier": tier}
        if closed:
            ev.append(Event(d.isoformat(), stall.id, "haze", "excluded", 0.0, "scheduled closure", evid, v))
        elif ytd["haze"] >= r.haze_cap_days_per_year:
            ev.append(Event(d.isoformat(), stall.id, "haze", "capped", 0.0, f"{r.haze_cap_days_per_year}-day annual cap reached", evid, v))
        elif ytd["haze_paid"] >= r.haze_cap_amount_per_year:
            ev.append(Event(d.isoformat(), stall.id, "haze", "capped", 0.0, f"S${r.haze_cap_amount_per_year:.2f} annual monetary cap reached", evid, v))
        else:
            remaining_cap = r.haze_cap_amount_per_year - ytd["haze_paid"]
            payable = min(amt, remaining_cap)
            if payable <= 0.0:
                ev.append(Event(d.isoformat(), stall.id, "haze", "capped", 0.0, f"S${r.haze_cap_amount_per_year:.2f} annual monetary cap reached", evid, v))
            else:
                ytd["haze"] += 1
                ytd["haze_paid"] += payable
                ev_reason = why if payable == amt else f"{why} (capped at S${r.haze_cap_amount_per_year:.2f} annual limit)"
                ev.append(Event(d.isoformat(), stall.id, "haze", "paid", payable, ev_reason, evid, v))

    # --- rain ---
    if d not in data.rain_dates():
        return ev
    got = rain_observation(stall, d, r)
    if got is None:
        if wants_rain:
            ev.append(Event(d.isoformat(), stall.id, "rain", "pending", 0.0, "no valid assigned/fallback gauge", {"gauge": stall.gauge}, v))
        return ev
    g, row, fb = got
    evid = {"gauge": g, "assigned": stall.gauge, "fallback": fb, "daily_mm": row["mm"], "max_1h_mm": row["max_1h"]}
    hit, why = rain_daily(row["mm"], r)
    if hit and wants_rain:
        if closed:
            ev.append(Event(d.isoformat(), stall.id, "rain", "excluded", 0.0, "scheduled closure", evid, v))
        elif ytd["rain"] >= r.rain_cap_days_per_year:
            ev.append(Event(d.isoformat(), stall.id, "rain", "capped", 0.0, "rain cap reached", evid, v))
        else:
            ytd["rain"] += 1
            ev.append(Event(d.isoformat(), stall.id, "rain", "paid", r.rain_payout, why, evid, v))
    if row["mm"] >= r.rain_comparison_mm:
        ev.append(Event(d.isoformat(), stall.id, "rain_80_cmp", "shadow", 0.0, f"{row['mm']:.1f} mm >= {r.rain_comparison_mm:.0f} mm", evid, v))
    s_hit, s_why = rain_short_storm(row["max_1h"], r)
    if s_hit:
        ev.append(Event(d.isoformat(), stall.id, "rain_short_storm", "shadow", 0.0, s_why, evid, v))
    return ev


def replay(stalls: Iterable[data.Stall], start: date, end: date, r: RuleSet = DEFAULT_RULES,
           only_dates: Optional[set] = None, *, psi_history: Optional[Dict[date, Dict[str, float]]] = None) -> List[Event]:
    """Walk days start..end. Annual caps reset each calendar year (simplification of 'policy year')."""
    stalls = list(stalls)
    out: List[Event] = []
    ytd = {s.id: {"haze": 0, "haze_paid": 0.0, "rain": 0, "year": None} for s in stalls}
    d = start
    while d <= end:
        if only_dates is None or d in only_dates:
            for s in stalls:
                c = ytd[s.id]
                if c["year"] != d.year:
                    c.update(haze=0, haze_paid=0.0, rain=0, year=d.year)
                out += evaluate(s, d, r, c, psi_history=psi_history)
        d += timedelta(days=1)
    return out


def summarise(events: List[Event], n_stalls: int, years: float) -> dict:
    paid = [e for e in events if e.status == "paid"]
    by = lambda p: [e for e in paid if e.peril == p]
    return {
        "rule_version": events[0].rule_version if events else DEFAULT_RULES.version,
        "stalls": n_stalls,
        "paid_events": len(paid),
        "paid_total_sgd": sum(e.amount for e in paid),
        "haze_paid_events": len(by("haze")), "rain_paid_events": len(by("rain")),
        "avg_paid_per_stall_per_year_sgd": round(sum(e.amount for e in paid) / max(n_stalls, 1) / max(years, 1e-9), 2),
        "shadow_events": len([e for e in events if e.status == "shadow"]),
        "pending": len([e for e in events if e.status == "pending"]),
        "excluded": len([e for e in events if e.status == "excluded"]),
        "capped": len([e for e in events if e.status == "capped"]),
    }
