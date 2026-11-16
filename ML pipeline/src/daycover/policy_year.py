"""Policy-anniversary boundaries for deterministic historical replay.

A policy period starts on its inception anniversary (inclusive) and ends the day
before the next anniversary (inclusive). Feb-29 anniversaries use Feb-28 in
non-leap years, reverting to Feb-29 in leap years. That is a modelling convention;
the insurer must confirm contract wording before production.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Tuple


def anniversary(inception: date, year: int) -> date:
    if year < inception.year:
        raise ValueError("anniversary cannot precede inception year")
    try:
        return inception.replace(year=year)
    except ValueError:
        if inception.month == 2 and inception.day == 29:
            return date(year, 2, 28)
        raise


def policy_year_bounds(inception: date, day: date) -> Tuple[date, date]:
    """Return inclusive (start, end) for the policy year containing day.

    A missing/expired policy is not inferred here; callers must check the
    enrolled term and actual renewal status.
    """
    if day < inception:
        raise ValueError("date precedes policy inception")
    year = day.year
    if day < anniversary(inception, year):
        year -= 1
    start = anniversary(inception, year)
    return start, anniversary(inception, year + 1) - timedelta(days=1)
