"""Walk-forward test using the trigger rules in src/daycover/rules.py (version 2026.11-draft2).

Paying:  haze tier 1  PSI >= 101 on 2 consecutive days  (1 unit)      haze tier 2  PSI >= 151 any day (2 units)
         haze cap: 5 paid days and 5 units (S$150 at S$30/unit) per policy year
         rain: >= 70 mm in a day at the assigned gauge, 1 paid day per year
Shadow (logged, never paid): short storm (wettest hour >= 20 mm), rain >= 80 mm, heat (WBGT lunch window).
Modes:   flat   = repo amounts: S$30 per haze unit, S$30 rain, same for every stall
         stall  = same triggers, amounts scaled per stall by the impact model (haze unit = half the stall's
                  severe-haze cover, rain = the stall's rain cover)
For each year Y: train on data before Y only, price, then settle Y on the real record.
"""
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from pricing.rain_model import centre_months, Model
from daycover.rules import DEFAULT_RULES as R

REG = ["north", "south", "east", "west", "central"]
UNIT_CAP = R.haze_cap_amount_per_year / R.haze_tier1_payout


def haze_table(psi):
    """(region, year) -> paid units under the repo rule and caps."""
    out = {}
    for r in REG:
        s = psi[["date", r]].rename(columns={r: "p"}).sort_values("date"); s["prev"] = s.p.shift(1)
        s["u"] = np.where(s.p >= R.haze_tier2_psi, 2.0, np.where((s.p >= R.haze_tier1_psi) & (s.prev >= R.haze_tier1_psi), 1.0, 0.0))
        for y, g in s[s.u > 0].groupby(s.date.dt.year):
            units, days = 0.0, []
            for d, u in zip(g.date, g.u):
                if len(days) >= R.haze_cap_days_per_year or units >= UNIT_CAP: break
                units += min(u, UNIT_CAP - units); days.append(d)
            out[(r, y)] = (units, days)
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--processed", default=str(ROOT / "data/processed"))
    ap.add_argument("--world", default="central"); ap.add_argument("--first", type=int, default=2019)
    a = ap.parse_args(); P = Path(a.processed); out = P / "model"; rng = np.random.default_rng(7)
    C = pd.read_csv(P / "centres.csv").merge(pd.read_csv(P / "centre_region_map.csv"), on="centre_id")
    cidx = {c: i for i, c in enumerate(C.centre_id)}
    cd = pd.read_csv(P / "centre_day.csv.gz", parse_dates=["date"], low_memory=False); cd["year"] = cd.date.dt.year
    psi = pd.read_csv(P / "psi_daily.csv", parse_dates=["date"]); psi = psi[psi.date <= "2026-10-31"]
    hz = haze_table(psi); hu = lambda r, y: hz.get((r, y), (0.0, []))[0]
    b = pd.read_csv(out / f"book_2026_{a.world}.csv"); b["ci"] = b.centre_id.map(cidx)
    W = P / "synthetic" / a.world
    s = pd.read_csv(W / "stalls.csv").set_index("stall_id"); gp = s.customers_per_day * s.avg_ticket_sgd * s.gross_margin
    p26 = pd.read_csv(W / "stall_day_2026.csv.gz"); p26["loss"] = p26.stall_id.map(gp) * p26.weather_drop * p26.trading
    L26 = p26.groupby("stall_id").loss.sum()
    oni0 = pd.DataFrame({"year": range(2009, 2027), "oni_prev_ond": 0.0})
    cm_all = centre_months(cd[["centre_id", "date", "rain"]], C, oni0, R.rain_daily_mm)
    modes = {"flat": (np.full(len(b), R.haze_tier1_payout), np.full(len(b), R.rain_payout)),
             "stall": (b.cover_haze_t2.values / 2, b.cover_rain.values)}
    res = {}
    for mode, (hunit, rcov) in modes.items():
        keep = (hunit + rcov) > 0
        ci = b.ci.values[keep]; hunit_k, rcov_k = hunit[keep], rcov[keep]
        covH = np.bincount(ci, weights=hunit_k, minlength=len(C)); covR = np.bincount(ci, weights=rcov_k, minlength=len(C))
        rows = []
        for Y in range(a.first, 2027):
            cm = cm_all[cm_all.year < Y]; glm = Model("glm", 1e-3).fit(cm)
            g = pd.MultiIndex.from_product([C.centre_id, range(1, 13)], names=["centre_id", "month"]).to_frame(index=False)
            g["days"] = g.month.map(dict(zip(range(1, 13), [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])))
            g = g.merge(C[["centre_id", "lat", "lon"]]).assign(oni_prev_ond=0.0); g["mu"] = glm.predict(g)
            mu = g.groupby("centre_id").mu.sum().reindex(C.centre_id).values
            pred = cm.assign(pr=glm.predict(cm)).groupby("year").pr.sum()
            yf = (cm.groupby("year").y.sum() / pred).values
            hy = list(range(2014, Y)); Htab = np.array([[hu(r, y) for r in C.psi_region] for y in hy])
            S = 20000; H = Htab[rng.integers(0, len(hy), S)]
            Rn = np.minimum(rng.poisson(np.outer(rng.choice(yf, S), mu)), R.rain_cap_days_per_year)
            port = H @ covH + Rn @ covR; EL = port.mean(); layer = np.clip(port - 1.5 * EL, 0, 3 * EL)
            rp = 1.6 * layer.mean(); load = 1 + (rp - layer.mean()) / EL + 0.25 * port.std() / EL
            Er = Rn.mean(0); Er = np.clip(Er, .85 * Er.mean(), 1.15 * Er.mean()); Er *= Rn.mean(0).mean() / Er.mean()
            prem_s = (hunit_k * H.mean(0)[ci] + rcov_k * Er[ci]) * load / 0.75
            frac = 10 / 12 if Y == 2026 else 1.0
            t = cd[(cd.year == Y) & (cd.rain >= R.rain_daily_mm)]
            t = t[t.closure.isna()] if "closure" in t else t
            nh = np.array([hu(r, Y) for r in C.psi_region]); nr = np.zeros(len(C))
            for i, c in enumerate(C.itertuples()):
                hd = hz.get((c.psi_region, Y), (0, []))[1]
                nr[i] = min(len(t[(t.centre_id == c.centre_id) & ~t.date.isin(hd)]), R.rain_cap_days_per_year)
            pay = hunit_k * nh[ci] + rcov_k * nr[ci]
            prem = prem_s.sum() * frac; cl = pay.sum(); rec = float(np.clip(cl / frac - 1.5 * EL, 0, 3 * EL)) * frac
            rows.append(dict(year=Y, premium=round(prem), claims=round(cl), loss_ratio=round(cl / prem, 2),
                             reins_recovery=round(rec), profit=round(prem - cl - .2 * prem - rp * frac + rec),
                             weekly_premium_median=round(float(np.median(prem_s)) / 52, 2), stalls_paid=int((pay > 0).sum()),
                             payout_median=float(np.median(pay[pay > 0])) if (pay > 0).any() else 0,
                             haze_units=round(float(nh.mean()), 2), rain_days=round(float(nr.mean()), 2)))
            if Y == 2026:
                sid = b.stall_id.values[keep]; L = L26.reindex(sid).values
                hv = dict(stalls=int(keep.sum()), premium_jan_oct_median=round(float(np.median(prem_s)) * frac, 1),
                          payout_median=float(np.median(pay[pay > 0])), payout_per_premium_dollar=round(cl / prem, 2),
                          weather_loss_median=round(float(np.nanmedian(L))), paid_more_than_lost=int((pay > L).sum()),
                          share_of_loss_covered_median=round(float(np.nanmedian(pay / L)), 3))
        r = pd.DataFrame(rows); tot = r[["premium", "claims", "reins_recovery", "profit"]].sum()
        print(f"\n=== mode: {mode} ===\n" + r.to_string(index=False))
        print("TOTAL", tot.to_dict(), "| loss ratio", round(tot.claims / tot.premium, 3), "| margin", round(tot.profit / tot.premium, 3),
              "| profitable years", int((r.profit > 0).sum()), "of", len(r)); print("HAWKER 2026:", hv)
        res[mode] = {"years": rows, "total": tot.to_dict(), "hawker_2026": hv}
    # shadow triggers (real data, never paid)
    g = cd[cd.year.between(2014, 2025)]; per = lambda m: float(m.groupby([g.centre_id, g.year]).sum().mean())
    sh = {"short_storm_wettest_hour_ge_20mm_days_per_centre_year": round(per(g.max60 >= R.rain_short_storm_mm_per_hour), 2),
          "rain_ge_80mm_days_per_centre_year": round(per(g.rain >= R.rain_comparison_mm), 2),
          "rain_ge_70mm_days_per_centre_year": round(per(g.rain >= R.rain_daily_mm), 2)}
    wf, wm = P / "wbgt_15min.csv.gz", P / "centre_wbgt_map.csv"
    if wf.exists():
        w = pd.read_csv(wf, usecols=["station_id", "ts", "value"], parse_dates=["ts"]); w = w[w.ts.dt.year == 2026]
        mins = w.ts.dt.hour * 60 + w.ts.dt.minute; w = w[(mins >= 690) & (mins < 870)].sort_values(["station_id", "ts"])
        w["date"] = w.ts.dt.normalize(); w["roll"] = w.groupby(["station_id", "date"]).value.transform(lambda v: v.rolling(4).mean())
        d = w.groupby(["station_id", "date"]).agg(single=("value", "max"), roll=("roll", "max")).reset_index()
        m = pd.read_csv(wm).merge(d, left_on="wbgt_station", right_on="station_id")
        n = m.centre_id.nunique()
        sh.update({"heat_2026_single_reading_ge_33_days_per_centre": round((m.single >= R.heat_single_reading_c).sum() / n, 1),
                   "heat_2026_rolling_hour_ge_32.5_days_per_centre": round((m.roll >= 32.5).sum() / n, 1),
                   "heat_2026_rolling_hour_ge_32.0_days_per_centre": round((m.roll >= 32.0).sum() / n, 1)})
    print("\nSHADOW TRIGGERS:", sh); res["shadow"] = sh; res["rule_version"] = R.version
    json.dump(res, open(out / f"walk_forward_repo_rules_{a.world}.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
