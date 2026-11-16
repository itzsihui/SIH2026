"""README Plan 4 ("Constrained Hawker Plan") as a separate, deterministic, versioned research contract.

This is NOT the frozen M1 contract and is not wired to the persistent ledger/billing: M1 remains the only enrolable
simulation contract. The evaluator exists so the README's rules are executable and testable side by side with M1, and so a
future approved version can be adopted deliberately. Rules decide; missing evidence is pending, never zero.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .policy_year import policy_year_bounds

PLAN4_PATH = Path(__file__).resolve().parents[2] / "contracts" / "daycover-plan4-150-research-v1.json"
TERMS = json.loads(PLAN4_PATH.read_text())
CENTS = lambda sgd: int(round(sgd * 100))


@dataclass
class YearState:
    """Benefit usage inside ONE policy year (anniversary-based, never calendar year)."""
    start: date
    end: date
    moderate_days: int = 0
    severe_days: int = 0
    rain_days: int = 0
    haze_cents: int = 0
    rain_cents: int = 0
    paid_by_day: dict = field(default_factory=dict)

    @property
    def total_cents(self) -> int:
        return self.haze_cents + self.rain_cents


class Plan4Engine:
    def __init__(self, inception: date, terms: dict = TERMS):
        self.t, self.inception, self.years = terms, inception, {}

    def state_for(self, day: date) -> YearState:
        s, e = policy_year_bounds(self.inception, day)  # raises before inception: no cover, no payment
        return self.years.setdefault(s, YearState(s, e))

    def evaluate_day(self, day: date, rain_mm, psi_today, psi_yesterday, closed: bool = False) -> list[dict]:
        """Return decisions for rain then haze (README priority), applying all limits atomically for the day."""
        t, st = self.t, self.state_for(day)
        out = []
        day_room = CENTS(t["daily_combined_cap"]) - st.paid_by_day.get(str(day), 0)
        annual_room = CENTS(t["annual_combined_cap"]) - st.total_cents
        # ---- rain (first priority; reserved S$30 bucket)
        r = t["rain"]
        if closed:
            out.append(self._d(day, "rain", "excluded", 0, "scheduled closure; no cap consumed"))
        elif rain_mm is None:
            out.append(self._d(day, "rain", "pending", 0, "no complete valid gauge total; awaiting data"))
        elif rain_mm < r["daily_mm"]:
            out.append(self._d(day, "rain", "no_trigger", 0, f"{rain_mm} mm below {r['daily_mm']} mm"))
        elif st.rain_days >= r["max_paid_days"]:
            out.append(self._d(day, "rain", "capped", 0, "rain benefit already used this policy year"))
        else:
            pay = min(CENTS(r["benefit"]), CENTS(r["rain_reserved_money_cap"]) - st.rain_cents, day_room, annual_room)
            if pay > 0:
                st.rain_days += 1
                st.rain_cents += pay
                st.paid_by_day[str(day)] = st.paid_by_day.get(str(day), 0) + pay
                day_room -= pay
                annual_room -= pay
            out.append(self._d(day, "rain", "paid" if pay > 0 else "capped", max(pay, 0), "rain threshold met"))
        # ---- haze (never touches the reserved rain bucket)
        h = t["haze"]
        if closed:
            out.append(self._d(day, "haze", "excluded", 0, "scheduled closure; no cap consumed"))
            return out
        severe = psi_today is not None and psi_today >= h["severe_psi"]
        moderate_possible = psi_today is not None and h["moderate_psi"] <= psi_today < h["severe_psi"]
        if psi_today is None or (moderate_possible and psi_yesterday is None):
            out.append(self._d(day, "haze", "pending", 0, "missing PSI evidence; awaiting data"))
            return out
        if not severe and not (moderate_possible and psi_yesterday >= h["moderate_psi"]):
            out.append(self._d(day, "haze", "no_trigger", 0, f"PSI {psi_today} below triggers"))
            return out
        tier = "severe" if severe else "moderate"
        used = st.severe_days if severe else st.moderate_days
        limit = h["severe_max_days"] if severe else h["moderate_max_days"]
        want = CENTS(h["severe_benefit"] if severe else h["moderate_benefit"])
        haze_room = CENTS(h["haze_annual_money_cap"]) - st.haze_cents
        if used >= limit or haze_room <= 0:
            out.append(self._d(day, "haze", "capped", 0, f"{tier} haze allowance used this policy year", tier=tier))
            return out
        pay = min(want, haze_room, day_room, annual_room)
        if pay <= 0:
            out.append(self._d(day, "haze", "capped", 0, "daily or annual combined limit reached", tier=tier))
            return out
        if severe:
            st.severe_days += 1   # assumption (open decision): a partially paid severe day still uses an allowance day
        else:
            st.moderate_days += 1
        st.haze_cents += pay
        st.paid_by_day[str(day)] = st.paid_by_day.get(str(day), 0) + pay
        why = f"{tier} haze threshold met" + (" (curtailed by a limit)" if pay < want else "")
        out.append(self._d(day, "haze", "paid", pay, why, tier=tier))
        return out

    def _d(self, day, peril, status, cents, reason, **extra):
        st = self.state_for(day)
        return {"day": str(day), "peril": peril, "status": status, "amount_cents": cents, "reason": reason,
                "version": self.t["version"], "policy_year": [str(st.start), str(st.end)],
                "remaining_combined_cents": CENTS(self.t["annual_combined_cap"]) - st.total_cents, **extra}


def replay(inception: date, days: list[dict], terms: dict = TERMS) -> list[dict]:
    """Deterministic ordered replay. days: [{day, rain_mm, psi, psi_yesterday?, closed?}] (psi_yesterday defaults to the prior item)."""
    eng, out, prev = Plan4Engine(inception, terms), [], {}
    for d in sorted(days, key=lambda x: x["day"]):
        day = date.fromisoformat(d["day"]) if isinstance(d["day"], str) else d["day"]
        yest = d.get("psi_yesterday", prev.get("psi") if prev and (day - prev["date"]).days == 1 else None)
        out.extend(eng.evaluate_day(day, d.get("rain_mm"), d.get("psi"), yest, d.get("closed", False)))
        prev = {"date": day, "psi": d.get("psi")}
    return out
