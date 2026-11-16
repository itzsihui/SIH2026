"""Haze trigger model: paid haze units per region per year under the frozen rules.

Haze is one shock that hits every centre at once, and only 11 full years exist (2015-2025), two of them severe
(2015, 2019). A per-day regression would overstate what the data can tell us. So:
  annual price  : expected capped units per region = credibility blend of the region's own mean and the island
                  mean, validated leave-one-year-out against simpler baselines.
  mid-year view : Poisson GLM of annual units on the May-Jul ONI (known by August) - used only for reinsurance,
                  pausing new haze sales and early-warning alerts, never for the annual price.
"""
from __future__ import annotations
import numpy as np, pandas as pd

REGIONS = ["north", "south", "east", "west", "central"]


def haze_units(psi: pd.DataFrame, rules: dict, end: str | None = None) -> pd.DataFrame:
    """Daily paid units per region (before the yearly cap) and capped units per region-year."""
    rows = []
    p = psi if end is None else psi[psi.date <= end]
    for r in REGIONS:
        s = p[["date", r]].rename(columns={r: "psi"}).sort_values("date").copy()
        s["prev"] = s.psi.shift(1)
        t2 = s.psi >= rules["haze_t2_psi"]
        t1 = (s.psi >= rules["haze_t1_psi"]) & (s.prev >= rules["haze_t1_psi"])
        s["units"] = np.where(t2, rules["haze_t2_units"], np.where(t1, rules["haze_t1_units"], 0.0))
        s["region"] = r
        rows.append(s[["date", "region", "psi", "units"]])
    return pd.concat(rows, ignore_index=True)


def cap_year(days: pd.DataFrame, cap_days: int) -> pd.DataFrame:
    d = days[days.units > 0].sort_values("date").assign(year=lambda x: x.date.dt.year)
    d["rank"] = d.groupby(["region", "year"]).cumcount() + 1
    paid = d[d["rank"] <= cap_days]
    return paid.groupby(["region", "year"]).agg(units=("units", "sum"), paid_days=("units", "size"),
                                                t1_days=("units", lambda u: (u == 1).sum()),
                                                t2_days=("units", lambda u: (u > 1).sum())).reset_index()


def region_year_table(days, cap_days, years):
    y = cap_year(days, cap_days)
    full = pd.MultiIndex.from_product([REGIONS, years], names=["region", "year"]).to_frame(index=False)
    return full.merge(y, how="left").fillna({"units": 0.0, "paid_days": 0, "t1_days": 0, "t2_days": 0})


def credibility_mean(tab: pd.DataFrame) -> pd.Series:
    """Buhlmann credibility: weight on a region's own mean = n / (n + k), k = within-variance / between-variance."""
    g = tab.groupby("region").units
    n = g.size().iloc[0]
    within = g.var(ddof=1).mean()
    between = max(g.mean().var(ddof=1) - within / n, 1e-9)
    z = n / (n + within / between)
    island = tab.units.mean()
    return z * g.mean() + (1 - z) * island, z


def loyo(tab: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for y in sorted(tab.year.unique()):
        tr, te = tab[tab.year != y], tab[tab.year == y]
        island = tr.units.mean()
        own = tr.groupby("region").units.mean()
        cred, z = credibility_mean(tr)
        for name, pred in (("island", te.region.map(lambda r: island)), ("own_region", te.region.map(own)),
                           ("credibility", te.region.map(cred))):
            rows.append({"year": y, "model": name, "abs_err": float((te.units - pred).abs().mean()),
                         "pred": float(pred.mean()), "actual": float(te.units.mean())})
    return pd.DataFrame(rows)
