"""Per-stall, per-peril premium for 2027 and a 2027-2031 reinsurance projection.
Trained on everything available: rain 2010-2025 (full years), haze seasons 2014-2026.
Product v2: rain >= 70 mm/day (2 days), haze PSI >= 151 (5 days), one payout a day, max 6 days."""
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from pricing.rain_model import centre_months, Model
REG = ["north", "south", "east", "west", "central"]; S = 50000


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--processed", default=str(ROOT / "data/processed")); ap.add_argument("--world", default="central")
    a = ap.parse_args(); P = Path(a.processed); out = P / "model"; rng = np.random.default_rng(11)
    C = pd.read_csv(P / "centres.csv").merge(pd.read_csv(P / "centre_region_map.csv"), on="centre_id"); cidx = {c: i for i, c in enumerate(C.centre_id)}
    cd = pd.read_csv(P / "centre_day.csv.gz", parse_dates=["date"], usecols=["centre_id", "date", "rain"]); cd = cd[cd.date.dt.year.between(2010, 2025)]
    psi = pd.read_csv(P / "psi_daily.csv", parse_dates=["date"])
    b = pd.read_csv(out / f"book_v2_{a.world}.csv"); b["ci"] = b.centre_id.map(cidx); ci = b.ci.values
    covR = np.bincount(ci, weights=b.cover_rain, minlength=len(C)); covH = np.bincount(ci, weights=b.cover_haze_t2, minlength=len(C))
    cm = centre_months(cd, C, pd.DataFrame({"year": range(2009, 2027), "oni_prev_ond": 0.0}), 70.0); glm = Model("glm", 1e-3).fit(cm)
    g = pd.MultiIndex.from_product([C.centre_id, range(1, 13)], names=["centre_id", "month"]).to_frame(index=False)
    g["days"] = g.month.map(dict(zip(range(1, 13), [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])))
    g = g.merge(C[["centre_id", "lat", "lon"]]).assign(oni_prev_ond=0.0); g["mu"] = glm.predict(g)
    mu = g.groupby("centre_id").mu.sum().reindex(C.centre_id).values
    yf = (cm.groupby("year").y.sum() / cm.assign(pr=glm.predict(cm)).groupby("year").pr.sum()).values
    hy = list(range(2014, 2027))
    Htab = np.array([[min(int(((psi[r] >= 151) & (psi.date.dt.year == y)).sum()), 5) for r in C.psi_region] for y in hy])
    print("haze paid days by season (island mean):", dict(zip(hy, Htab.mean(1).round(2))))

    def sim(rain_mult=1.0):
        H = Htab[rng.integers(0, len(hy), S)]
        R = np.minimum(np.minimum(rng.poisson(np.outer(rng.choice(yf, S), mu * rain_mult)), 2), 6 - H)
        return R, H
    R, H = sim(); cr, ch = R @ covR, H @ covH; port = cr + ch; EL = port.mean()
    att, lim = 1.5 * EL, 3 * EL; layer = np.clip(port - att, 0, lim); rp = 1.6 * layer.mean()
    load = 1 + (rp - layer.mean()) / EL + 0.25 * port.std() / EL; gross = load / 0.75
    Er = R.mean(0); Er = np.clip(Er, .85 * Er.mean(), 1.15 * Er.mean()); Er *= R.mean(0).mean() / Er.mean(); Eh = H.mean(0)
    b["prem_rain"] = b.cover_rain * Er[ci] * gross; b["prem_haze"] = b.cover_haze_t2 * Eh[ci] * gross
    b["premium_2027"] = b.prem_rain + b.prem_haze; b["weekly_2027"] = b.premium_2027 / 52
    prem = b.premium_2027.sum(); net = prem * 0.8 - port - rp + layer
    q = lambda x, p: round(float(np.quantile(x, p)))
    res = {"premium_2027": {"total": round(prem), "rain_share": round(float(b.prem_rain.sum() / prem), 3),
            "weekly_p10_median_p90_max": [round(float(b.weekly_2027.quantile(x)), 2) for x in (.1, .5, .9, 1)],
            "stalls_rain_only_or_haze_only": [int((b.cover_haze_t2 == 0).sum()), int((b.cover_rain == 0).sum())],
            "expected_days_rain_haze": [round(float(R.mean()), 2), round(float(H.mean()), 2)],
            "pure_rain_haze": [round(float(cr.mean())), round(float(ch.mean()))], "load_gross_multiplier": round(gross, 3)},
           "claims_distribution_2027": {"expected": round(EL), "p50": q(port, .5), "p90": q(port, .9), "p95": q(port, .95), "p99": q(port, .99)},
           "reinsurance_2027": {"attach": round(att), "limit": round(lim), "premium": round(rp), "prob_triggered": round(float((port > att).mean()), 3),
            "expected_recovery": round(float(layer.mean())), "recovery_when_triggered": round(float(layer[layer > 0].mean())),
            "prob_layer_exhausted": round(float((port > att + lim).mean()), 4)},
           "income_2027": {"expected_profit": round(float(net.mean())), "prob_loss_year": round(float((net < 0).mean()), 3),
            "worst_5pct_result": q(net, .05), "without_reins_worst_5pct": q(prem * .8 - port, .05), "without_reins_expected": round(float((prem * .8 - port).mean()))}}
    ex = b.assign(q=pd.qcut(b.premium_2027, [0, .1, .5, .9, 1], labels=False)).groupby("q").apply(lambda d: d.iloc[len(d) // 2])
    res["example_stalls"] = [dict(stall=r.stall_id, qr_sales_per_day=r.qr_tx_per_trading_day_12wk, est_daily_profit=r.est_daily_profit, k_rain=r.k_rain,
            cover_rain=r.cover_rain, cover_haze=r.cover_haze_t2, rain_prem=round(r.prem_rain, 1), haze_prem=round(r.prem_haze, 1),
            weekly=round(r.weekly_2027, 2)) for r in ex.itertuples()]
    # 5-year projection, premium repriced each year to the scenario's expected claims
    proj = {}
    for name, tr in {"no_trend": 0.0, "rain_+1%/yr": 0.01, "rain_+2%/yr": 0.02}.items():
        cum = np.zeros(S); rows = []
        for i, y in enumerate(range(2027, 2032)):
            R, H = sim((1 + tr) ** (i + 1)); pt = R @ covR + H @ covH; el = pt.mean(); ly = np.clip(pt - 1.5 * el, 0, 3 * el); rpy = 1.6 * ly.mean()
            pr = el * (1 + (rpy - ly.mean()) / el + 0.25 * pt.std() / el) / 0.75; n = pr * .8 - pt - rpy + ly
            cum += rng.permutation(n)
            rows.append(dict(year=y, premium=round(pr), expected_claims=round(el), reins_premium=round(rpy), expected_recovery=round(float(ly.mean())),
                             prob_reins_triggered=round(float((ly > 0).mean()), 3), expected_profit=round(float(n.mean()))))
        proj[name] = {"years": rows, "cum_expected_profit": round(float(cum.mean())), "prob_5yr_loss": round(float((cum < 0).mean()), 3), "cum_p5": q(cum, .05)}
    res["projection_2027_2031"] = proj
    print(json.dumps(res, indent=1, default=float))
    json.dump(res, open(out / f"price_2027_projection_{a.world}.json", "w"), indent=1, default=float)
    b.to_csv(out / f"premiums_2027_{a.world}.csv", index=False)


if __name__ == "__main__":
    main()
