"""Price every stall for 2026 using ONLY data up to 31 Dec 2025, then replay real 2026 (to 31 Oct).

Premium for stall s at centre c:
    annual premium = (1 + reinsurance load) / (1 - expenses - margin) x  sum over perils p of
                     cover[s,p] x expected paid days[c,p]
    expected paid days[c,p] : location hazard - rain GLM + haze history + 20,000-year simulation with caps
    cover[s,p]              : stall impact   - 60% of (stall's daily profit x stall's sensitivity x typical
                              drop on a p-day), banded; S$20 Lite only if <= 80% of the stall's loss
Payout on a trigger day = cover[s,p], whatever the stall sold that day (so closing never pays more than opening).
"""
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from pricing.config import RULES, TRAIN_YEARS, HAZE_TRAIN_YEARS, TEST_END, PRICING, COVER, IMPACT
from pricing.rain_model import centre_months, Model
from pricing.haze_model import haze_units, region_year_table

rng = np.random.default_rng(2026)
PERILS = ["rain", "haze_t1", "haze_t2"]


def band(x, bands):
    b = [v for v in bands if v <= x]
    return b[-1] if b else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--processed", default=str(ROOT / "data/processed"))
    ap.add_argument("--world", default="central"); ap.add_argument("--sims", type=int, default=20000)
    a = ap.parse_args(); P = Path(a.processed); out = P / "model"
    centres = pd.read_csv(P / "centres.csv"); rmap = pd.read_csv(P / "centre_region_map.csv")
    C = centres.merge(rmap, on="centre_id"); cidx = {c: i for i, c in enumerate(C.centre_id)}
    cd = pd.read_csv(P / "centre_day.csv.gz", parse_dates=["date"], low_memory=False)

    # ---------- location hazard (trained only on data <= 2025)
    tr = cd[cd.date.dt.year.isin(TRAIN_YEARS)]
    oni0 = pd.DataFrame({"year": range(2009, 2027), "oni_prev_ond": 0.0})
    cm = centre_months(tr[["centre_id", "date", "rain"]], centres, oni0, RULES["rain_daily_mm"])
    glm = Model("glm", 1e-3).fit(cm)
    g = pd.MultiIndex.from_product([C.centre_id, range(1, 13)], names=["centre_id", "month"]).to_frame(index=False)
    g["days"] = g.month.map(dict(zip(range(1, 13), [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])))
    g = g.merge(centres[["centre_id", "lat", "lon"]]).assign(oni_prev_ond=0.0); g["mu"] = glm.predict(g)
    mu = g.groupby("centre_id").mu.sum().reindex(C.centre_id).values
    yf = (cm.groupby("year").y.sum() / cm.groupby("year").apply(lambda d: glm.predict(d).sum())).values
    psi = pd.read_csv(P / "psi_daily.csv", parse_dates=["date"])
    hdays = haze_units(psi, RULES)
    htab = region_year_table(hdays, RULES["haze_cap_days"], HAZE_TRAIN_YEARS)
    t1 = htab.pivot(index="year", columns="region", values="t1_days")
    t2 = htab.pivot(index="year", columns="region", values="t2_days")
    S = a.sims
    hy = rng.choice(HAZE_TRAIN_YEARS, S)
    H1 = t1.loc[hy].reindex(columns=C.psi_region).values; H2 = t2.loc[hy].reindex(columns=C.psi_region).values
    Rn = np.minimum(rng.poisson(np.outer(rng.choice(yf, S), mu)), RULES["rain_cap_days"])
    Rn = np.minimum(Rn, np.maximum(RULES["total_cap_days"] - H1 - H2, 0))
    days_sim = {"rain": Rn, "haze_t1": H1, "haze_t2": H2}
    E = {p: v.mean(0) for p, v in days_sim.items()}
    # fairness: location differences in expected rain days capped at 1.5x (revenue-neutral)
    lo = E["rain"].min()
    if E["rain"].max() > PRICING["fair_spread_cap"] * lo:
        capd = np.clip(E["rain"], lo, PRICING["fair_spread_cap"] * lo); E["rain_priced"] = capd * E["rain"].mean() / capd.mean()
    else:
        E["rain_priced"] = E["rain"]

    # ---------- stall impact (onboarding view, 1 Jan 2026)
    W = P / "synthetic" / a.world
    s = pd.read_csv(W / "stalls.csv").merge(pd.read_csv(W / "stall_cover_inputs.csv"), on="stall_id")
    s = s.merge(pd.read_csv(out / f"stall_sensitivity_{a.world}.csv"), on="stall_id", how="left")
    imp = json.load(open(out / f"impact_model_{a.world}.json"))
    drop_typ = {"rain": imp["curves"]["rain"][4], "haze_t1": IMPACT["haze_t1_drop"], "haze_t2": IMPACT["haze_t2_drop"]}
    declared = np.clip(s.qr_share * np.exp(rng.normal(0, 0.15, len(s))), 1 - COVER["max_declared_cash_share"], 1)
    s["est_daily_profit"] = (s.qr_tx_per_trading_day_12wk * s.avg_ticket_sgd / declared * COVER["assumed_margin"]).round(1)
    true_gp = s.customers_per_day * s.avg_ticket_sgd * s.gross_margin
    true_k = s.weather_sensitivity * np.where(s.on_delivery_platform, 0.85, 1.0)
    for p in PERILS:
        k = s.k_rain if p == "rain" else s.k_haze
        loss = s.est_daily_profit * k.clip(0, 3) * drop_typ[p]
        cov = np.array([band(COVER["payout_share_of_loss"] * l, COVER["bands"]) if l == l else 0 for l in loss])
        lite = (cov == 0) & (loss * COVER["lite_max_share_of_loss"] >= COVER["lite_band"])
        cov[lite] = COVER["lite_band"]
        s[f"cover_{p}"] = cov
        s[f"est_loss_{p}"] = loss.round(1)
        s[f"true_loss_{p}"] = (true_gp * true_k * drop_typ[p]).round(1)
    s["eligible"] = s.qr_tx_per_trading_day_12wk.notna() & (s[[f"cover_{p}" for p in PERILS]].sum(1) > 0)
    b = s[s.eligible].copy(); b["ci"] = b.centre_id.map(cidx)

    # ---------- price
    covC = {p: np.bincount(b.ci, weights=b[f"cover_{p}"], minlength=len(C)) for p in PERILS}
    port = sum(days_sim[p] @ covC[p] for p in PERILS)
    EL = port.mean(); attach, limit = PRICING["stoploss_attach_x_expected"] * EL, PRICING["stoploss_limit_x_expected"] * EL
    layer = np.clip(port - attach, 0, limit); load = 1 + (PRICING["stoploss_price_x_expected_layer"] - 1) * layer.mean() / EL
    gross = load / (1 - PRICING["expense_ratio"] - PRICING["margin"])
    exp_rain = E["rain_priced"][b.ci]
    b["expected_payout"] = b.cover_rain * exp_rain + b.cover_haze_t1 * E["haze_t1"][b.ci] + b.cover_haze_t2 * E["haze_t2"][b.ci]
    b["annual_premium"] = (b.expected_payout * gross).round(2)
    b["weekly_premium"] = (b.annual_premium / 52).round(2)
    b["qr_deduction_per_sale"] = (b.weekly_premium / (b.qr_tx_per_trading_day_12wk * 6)).round(3)

    # ---------- replay 2026 with real weather, frozen mapping
    t = cd[(cd.date >= "2026-01-01") & (cd.date <= TEST_END)]
    closed = set(zip(t[t.closure.notna()].centre_id, t[t.closure.notna()].date))
    h = hdays[(hdays.date >= "2026-01-01") & (hdays.date <= TEST_END) & (hdays.units > 0)].sort_values("date")
    h = h.groupby("region").head(RULES["haze_cap_days"])
    ev = []
    for _, c in C.iterrows():
        hz = [(r.date, "haze_t2" if r.units > 1 else "haze_t1", f"PSI {r.psi:.0f}") for r in h[h.region == c.psi_region].itertuples()
              if (c.centre_id, r.date) not in closed]
        hz_dates = {d for d, _, _ in hz}
        rn = t[(t.centre_id == c.centre_id) & (t.rain >= RULES["rain_daily_mm"])].sort_values("date")
        rn = [(r.date, "rain", f"{r.rain:.1f} mm") for r in rn.itertuples()
              if (c.centre_id, r.date) not in closed and r.date not in hz_dates]   # one payout per day, highest peril
        rn = rn[:max(min(RULES["rain_cap_days"], RULES["total_cap_days"] - len(hz)), 0)]
        ev += [(c.centre_id, d, p, txt) for d, p, txt in hz + rn]
    ev = pd.DataFrame(ev, columns=["centre_id", "date", "peril", "reading"])
    panel = pd.read_csv(W / "stall_day_2026.csv.gz", parse_dates=["date"])
    panel = panel[panel.stall_id.isin(b.stall_id)]
    panel["centre_id"] = panel.stall_id.str[:5]
    act = panel.pivot(index="date", columns="stall_id", values="qr_tx").fillna(0)
    active7 = (act.rolling(7, min_periods=1).sum().shift(1).fillna(1) > 0)        # QR sales in the 7 days before
    pe = b[["stall_id", "centre_id", "cover_rain", "cover_haze_t1", "cover_haze_t2", "est_daily_profit"]].merge(ev, on="centre_id")
    pe["cover"] = np.select([pe.peril == "rain", pe.peril == "haze_t1"], [pe.cover_rain, pe.cover_haze_t1], pe.cover_haze_t2)
    pe["active"] = [bool(active7.at[d, sid]) if d in active7.index else True for d, sid in zip(pe.date, pe.stall_id)]
    pe = pe.merge(panel[["stall_id", "date", "weather_drop", "trading"]], on=["stall_id", "date"], how="left")
    tg = (s.set_index("stall_id").customers_per_day * s.set_index("stall_id").avg_ticket_sgd * s.set_index("stall_id").gross_margin)
    pe["true_loss_that_day"] = (pe.stall_id.map(tg) * pe.weather_drop.fillna(0)).round(1)
    pe["payout"] = np.where(pe.active, pe.cover, 0.0)
    pay = pe.groupby("stall_id").payout.sum().reindex(b.stall_id).fillna(0)

    res = {"world": a.world, "impact_typical_drop": drop_typ}
    for share in (1.0, 0.30, 0.15):
        bb = b.sample(frac=share, random_state=7) if share < 1 else b
        pp = pay.loc[bb.stall_id].values
        prem = bb.annual_premium.sum() * 10 / 12; cl = pp.sum(); ex = prem * PRICING["expense_ratio"]
        cbc = {p: np.bincount(bb.ci, weights=bb[f"cover_{p}"], minlength=len(C)) for p in PERILS}
        pt = sum(days_sim[p] @ cbc[p] for p in PERILS); el = pt.mean()
        lay = lambda x: np.clip(x - PRICING["stoploss_attach_x_expected"] * el, 0, PRICING["stoploss_limit_x_expected"] * el)
        rprem = PRICING["stoploss_price_x_expected_layer"] * lay(pt).mean() * 10 / 12
        rec = float(lay(cl * 12 / 10)) * 10 / 12
        res[f"takeup_{int(share*100)}"] = {"insured": len(bb), "paid": int((pp > 0).sum()),
            "payout_median": float(np.median(pp[pp > 0])) if (pp > 0).any() else 0, "payout_p90": float(np.quantile(pp, .9)),
            "premium_jan_oct": round(prem), "claims_jan_oct": round(cl), "loss_ratio": round(cl / prem, 3),
            "result_before_reins": round(prem - cl - ex), "result_after_reins": round(prem - cl - ex - rprem + rec)}
    paid_ev = pe[pe.payout > 0]
    res["sim"] = {"expected_claims_full_book_year": round(EL), "p95": round(float(np.quantile(port, .95))),
                  "share_years_worse_than_2026": round(float((port > pay.sum() * 12 / 10).mean()), 3), "reins_load": round(load, 3)}
    res["book"] = {"stalls": len(s), "eligible": int(s.eligible.sum()),
        "not_offered_rain_cover (shop barely affected by rain)": int((s.eligible & (s.cover_rain == 0)).sum()),
        "cover_rain_mix": b.cover_rain.value_counts().sort_index().to_dict(),
        "cover_haze_t2_mix": b.cover_haze_t2.value_counts().sort_index().to_dict(),
        "weekly_premium_median": float(b.weekly_premium.median()), "weekly_premium_p90": float(b.weekly_premium.quantile(.9)),
        "deduction_per_sale_median": float(b.qr_deduction_per_sale.median())}
    res["moral_hazard_and_basis"] = {
        "paid_stall_events": len(paid_ev),
        "payout_exceeds_true_loss_that_day_share": round(float((paid_ev.payout > paid_ev.true_loss_that_day).mean()), 3),
        "over_true_loss_by_peril": paid_ev.assign(o=paid_ev.payout > paid_ev.true_loss_that_day).groupby("peril").o.mean().round(3).to_dict(),
        "events_blocked_by_inactivity_rule": int((~pe.active).sum()),
        "closing_changes_payout": False}
    b.to_csv(out / f"book_2026_{a.world}.csv", index=False); ev.to_csv(out / "events_2026.csv", index=False)
    pe.to_csv(out / f"stall_events_2026_{a.world}.csv.gz", index=False)
    json.dump(res, open(out / f"test_2026_{a.world}.json", "w"), indent=1, default=str)
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
