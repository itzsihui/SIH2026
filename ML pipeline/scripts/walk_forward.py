"""Walk-forward test: for each year Y, price using ONLY data before Y, then settle Y on the real weather.

Product v2 (changes decided on history and principle, not on 2026 results):
  - haze pays from PSI >= 151 only. The PSI 101-150 tier is dropped: typical loss there is ~8% of sales, and the
    payout exceeded the stall's loss on 44% of such days (fails the insurable-interest test).
  - one payout per day (highest peril); haze cap 5 days, rain cap 2 days, total 6.
  - price = pure premium x (1 + net reinsurance cost + 0.25 x sd/mean of portfolio claims) / (1 - 20% - 5%)
  - location spread of the rain rate capped at +/-15%.
Book: the 2026 stall book (covers from the stall impact model) applied as-if to every year.
"""
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from pricing.config import RULES, PRICING
from pricing.rain_model import centre_months, Model

REG = ["north", "south", "east", "west", "central"]
T2, HCAP, RCAP, TCAP, MM = 151, 5, 2, 6, RULES["rain_daily_mm"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--processed", default=str(ROOT / "data/processed"))
    ap.add_argument("--world", default="central"); ap.add_argument("--first", type=int, default=2019)
    a = ap.parse_args(); P = Path(a.processed); out = P / "model"; rng = np.random.default_rng(7)
    centres = pd.read_csv(P / "centres.csv").merge(pd.read_csv(P / "centre_region_map.csv"), on="centre_id")
    cidx = {c: i for i, c in enumerate(centres.centre_id)}
    cd = pd.read_csv(P / "centre_day.csv.gz", parse_dates=["date"], low_memory=False)
    cd["year"] = cd.date.dt.year
    psi = pd.read_csv(P / "psi_daily.csv", parse_dates=["date"])
    b = pd.read_csv(out / f"book_2026_{a.world}.csv"); b["ci"] = b.centre_id.map(cidx)
    b = b[(b.cover_rain + b.cover_haze_t2) > 0]
    cov_r = np.bincount(b.ci, weights=b.cover_rain, minlength=len(centres))
    cov_h = np.bincount(b.ci, weights=b.cover_haze_t2, minlength=len(centres))
    # haze: paid T2 dates per region-year (first 5)
    hz = {}
    for r in REG:
        d = psi[psi[r] >= T2][["date"]].assign(year=lambda x: x.date.dt.year)
        for y, g in d.groupby("year"):
            hz[(r, y)] = list(g.date.sort_values()[:HCAP])
    hdays = lambda r, y: len(hz.get((r, y), []))
    oni0 = pd.DataFrame({"year": range(2009, 2027), "oni_prev_ond": 0.0})
    cm_all = centre_months(cd[["centre_id", "date", "rain"]], centres, oni0, MM)
    rows, stall_pay = [], {}
    for Y in range(a.first, 2027):
        cm = cm_all[cm_all.year < Y]
        glm = Model("glm", 1e-3).fit(cm)
        g = pd.MultiIndex.from_product([centres.centre_id, range(1, 13)], names=["centre_id", "month"]).to_frame(index=False)
        g["days"] = g.month.map(dict(zip(range(1, 13), [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])))
        g = g.merge(centres[["centre_id", "lat", "lon"]]).assign(oni_prev_ond=0.0); g["mu"] = glm.predict(g)
        mu = g.groupby("centre_id").mu.sum().reindex(centres.centre_id).values
        yf = (cm.groupby("year").y.sum() / cm.groupby("year").apply(lambda d: glm.predict(d).sum())).values
        hyears = list(range(2014, Y))
        Htab = np.array([[hdays(r, y) for r in centres.psi_region] for y in hyears])
        S = 20000
        H = Htab[rng.integers(0, len(hyears), S)]
        R = np.minimum(np.minimum(rng.poisson(np.outer(rng.choice(yf, S), mu)), RCAP), np.maximum(TCAP - H, 0))
        port = R @ cov_r + H @ cov_h
        EL = port.mean(); layer = np.clip(port - 1.5 * EL, 0, 3 * EL)
        reins_prem = 1.6 * layer.mean()
        load = 1 + (reins_prem - layer.mean()) / EL + 0.25 * port.std() / EL
        Er = R.mean(0); Er = np.clip(Er, 0.85 * Er.mean(), 1.15 * Er.mean()); Er *= R.mean(0).mean() / Er.mean()
        Eh = H.mean(0)
        prem_s = (b.cover_rain * Er[b.ci] + b.cover_haze_t2 * Eh[b.ci]) * load / 0.75
        # settle year Y on the real record
        frac = 10 / 12 if Y == 2026 else 1.0
        t = cd[(cd.year == Y) & (cd.rain >= MM)]
        if "closure" in t: t = t[t.closure.isna()]
        nr = np.zeros(len(centres)); nh = np.zeros(len(centres))
        for i, c in enumerate(centres.itertuples()):
            hd = hz.get((c.psi_region, Y), [])
            rd = t[(t.centre_id == c.centre_id) & ~t.date.isin(hd)]
            nh[i] = len(hd); nr[i] = min(len(rd), RCAP, TCAP - len(hd))
        pay_s = b.cover_rain.values * nr[b.ci] + b.cover_haze_t2.values * nh[b.ci]
        stall_pay[Y] = pay_s
        prem = prem_s.sum() * frac; claims = pay_s.sum(); exp_ = 0.20 * prem
        rec = float(np.clip(claims / frac - 1.5 * EL, 0, 3 * EL)) * frac
        rows.append({"year": Y, "premium": round(prem), "claims": round(claims), "loss_ratio": round(claims / prem, 2),
                     "expenses": round(exp_), "reins_premium": round(reins_prem * frac), "reins_recovery": round(rec),
                     "profit_before_reins": round(prem - claims - exp_),
                     "profit_after_reins": round(prem - claims - exp_ - reins_prem * frac + rec),
                     "weekly_premium_median": round(float(prem_s.median() / 52), 2),
                     "stalls_paid": int((pay_s > 0).sum()), "median_payout_paid": float(np.median(pay_s[pay_s > 0])) if (pay_s > 0).any() else 0,
                     "haze_days": float(nh.mean()), "rain_days": round(float(nr.mean()), 2)})
        if Y == 2026:
            b["premium_2026"] = prem_s.values; b["payout_2026"] = pay_s
    r = pd.DataFrame(rows)
    tot = r[["premium", "claims", "expenses", "reins_premium", "reins_recovery", "profit_before_reins", "profit_after_reins"]].sum()
    print(r.to_string(index=False)); print("\nTOTAL", tot.to_dict(), "| loss ratio", round(tot.claims / tot.premium, 3),
          "| profit margin after reins", round(tot.profit_after_reins / tot.premium, 3))
    print("years profitable (after reins):", int((r.profit_after_reins > 0).sum()), "of", len(r))
    # hawker view 2026
    W = P / "synthetic" / a.world
    p = pd.read_csv(W / "stall_day_2026.csv.gz"); s = pd.read_csv(W / "stalls.csv").set_index("stall_id")
    gp = s.customers_per_day * s.avg_ticket_sgd * s.gross_margin
    p["loss"] = p.stall_id.map(gp) * p.weather_drop * p.trading
    L = p.groupby("stall_id").loss.sum().reindex(b.stall_id).values
    hv = {"stalls": len(b), "annual_gross_profit_median": round(float((gp.reindex(b.stall_id) * 300).median())),
          "premium_2026_jan_oct_median": round(float((b.premium_2026 * 10 / 12).median()), 1),
          "premium_share_of_gross_profit": round(float((b.premium_2026 / (gp.reindex(b.stall_id).values * 300)).median()), 4),
          "paid_2026": int((b.payout_2026 > 0).sum()), "payout_median": float(b.payout_2026[b.payout_2026 > 0].median()),
          "payout_p90": float(b.payout_2026.quantile(.9)), "weather_loss_2026_median": round(float(np.median(L))),
          "payout_to_premium_2026": round(float(b.payout_2026.sum() / (b.premium_2026.sum() * 10 / 12)), 2),
          "paid_more_than_lost": int((b.payout_2026.values > L).sum())}
    allpay = np.array([stall_pay[y] for y in stall_pay])
    hv["share_of_years_a_stall_is_paid"] = round(float((allpay > 0).mean()), 3)
    print("\nHAWKER 2026:", hv)
    r.to_csv(out / f"walk_forward_{a.world}.csv", index=False)
    json.dump({"years": rows, "total": tot.to_dict(), "hawker_2026": hv}, open(out / f"walk_forward_{a.world}.json", "w"), indent=1, default=float)
    b.to_csv(out / f"book_v2_{a.world}.csv", index=False)


if __name__ == "__main__":
    main()
