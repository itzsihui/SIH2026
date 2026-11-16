"""Immutable, versioned trigger rules. Rules decide payouts; nothing else does.

Paying perils: haze (24-hr PSI) and rain (daily mm at the stall's assigned gauge).
Shadow perils (logged, never paid): short-storm rain, heat (WBGT rolling hour).
The pilot baseline and supporting calibration are documented in docs/ARCHITECTURE_AND_PROJECT.md section 8.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Sequence

HAZE_DAY_DEFINITION = "daily_max_hourly_24hr_psi_sgt"


@dataclass(frozen=True)
class RuleSet:
    version: str = "2026.11-draft2"
    # haze: maximum hourly 24-hr PSI in the stall's region during one Singapore day
    haze_tier1_psi: int = 101
    haze_tier1_consecutive_days: int = 2
    haze_tier1_payout: float = 30.0
    haze_tier2_psi: int = 151
    haze_tier2_payout: float = 60.0
    haze_cap_days_per_year: int = 5
    haze_cap_amount_per_year: float = 150.0
    # rain (paying): daily total at the assigned gauge
    rain_daily_mm: float = 70.0
    rain_payout: float = 30.0
    rain_cap_days_per_year: int = 1
    rain_comparison_mm: float = 80.0           # logged as shadow alongside the paying line
    # rain (shadow): intense short storm, accumulated over a rolling hour
    rain_short_storm_mm_per_hour: float = 20.0  # demo value, needs calibration
    # heat (shadow): WBGT during lunch window
    heat_single_reading_c: float = 33.0
    heat_rolling_hour_c: tuple = (32.0, 32.5)
    gauge_fallback_km: float = 5.0
    haze_day_definition: str = field(default=HAZE_DAY_DEFINITION, init=False)


DEFAULT_RULES = RuleSet()


def haze_payout(psi_today: Optional[float], psi_yesterday: Optional[float], r: RuleSet = DEFAULT_RULES):
    """Return (tier, amount, reason). tier 0 = no trigger. None PSI -> pending upstream, not zero."""
    if psi_today is None:
        return 0, 0.0, "no PSI reading"
    if psi_today >= r.haze_tier2_psi:
        return 2, r.haze_tier2_payout, f"PSI {psi_today:.0f} >= {r.haze_tier2_psi}"
    if (psi_today >= r.haze_tier1_psi and psi_yesterday is not None and psi_yesterday >= r.haze_tier1_psi):
        return 1, r.haze_tier1_payout, (
            f"PSI >= {r.haze_tier1_psi} on {r.haze_tier1_consecutive_days} consecutive days "
            f"({psi_yesterday:.0f}, {psi_today:.0f})")
    return 0, 0.0, f"PSI {psi_today:.0f} below triggers"


def rain_daily(mm: Optional[float], r: RuleSet = DEFAULT_RULES):
    if mm is None:
        return False, "no gauge data"
    return mm >= r.rain_daily_mm, f"{mm:.1f} mm vs {r.rain_daily_mm:.0f} mm"


def rain_short_storm(max_1h_mm: Optional[float], r: RuleSet = DEFAULT_RULES):
    """Shadow rule. Uses the wettest-hour value from the gauge."""
    if max_1h_mm is None:
        return False, "no hourly data"
    return max_1h_mm >= r.rain_short_storm_mm_per_hour, f"wettest hour {max_1h_mm:.1f} mm vs {r.rain_short_storm_mm_per_hour:.0f} mm"


def heat_rules(lunch_readings: Sequence[float], r: RuleSet = DEFAULT_RULES) -> dict:
    """Shadow rule. lunch_readings: consecutive WBGT readings across one hour (>=1).
    Returns which of the single-reading and rolling-hour rules qualify."""
    if not lunch_readings:
        return {"single": False, "rolling": {}, "mean": None}
    mean = sum(lunch_readings) / len(lunch_readings)
    return {
        "single": max(lunch_readings) >= r.heat_single_reading_c,
        "rolling": {t: mean >= t for t in r.heat_rolling_hour_c},
        "mean": round(mean, 3),
    }
