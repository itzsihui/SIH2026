"""Every user group named in the brief, priced with the same engine. Weather is REAL; counts and loss sizes that
have no public source are SYNTHETIC planning scenarios and are tagged as such in SEGMENTS.
For each segment: price 2026 using data before 2026, settle on real 2026 (Jan-Oct); then price 2027."""
import argparse, json
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]; S = 40000
# perils: (index, payout S$ per paid day, max paid days)
SEGMENTS = {
 "Market (produce) stalls": dict(n=8300, n_basis="reported: 2026 rental-support announcement", payer="stallholder, at Stallholder renewal",
    perils=[("rain70", 20, 2), ("haze151", 30, 5)],
    basis="synthetic: gross profit S$200/day (vs S$359 cooked food); drop 15% rain, 25% severe haze; payout = 60% of loss"),
 "Neighbourhood shops and home-based food businesses": dict(n=5000, n_basis="SCENARIO: no public count; pilot-sized book", payer="business owner, SmartBiz360 rider",
    perils=[("rain70", 20, 2), ("haze151", 30, 5)], basis="synthetic: same loss profile as market stalls"),
 "Delivery riders": dict(n=15300, n_basis="MOM 2024 via NTUC (verified)", payer="platform or NDCA group policy",
    perils=[("heat33", 12, 10), ("haze151", 20, 5)], basis="heat: 60% of S$21 median daily loss (NUS HeatSafe); haze S$20: assumption"),
 "Taxi and private-hire drivers": dict(n=52600, n_basis="MOM 2024 via NTUC (verified): 20,800 + 31,800", payer="platform or NTA / NPHVA group policy",
    perils=[("haze151", 15, 5)], basis="synthetic: haze cuts trips ~15% of ~S$150/day net; no rain cover (rain raises fares); no heat cover (air-conditioned)"),
 "Construction workers (employer-paid heat-rest cover)": dict(n=300000, n_basis="SCENARIO: order of magnitude of the construction workforce; verify with MOM", payer="employer",
    perils=[("heat33", 6, 10), ("haze151", 20, 5)], basis="synthetic: MOM rest breaks cost the employer ~45 min of pay (~S$6) per High-heat day; haze stop-work S$20"),
 "Outdoor cleaners (employer-paid)": dict(n=20000, n_basis="SCENARIO: no public count of outdoor cleaners", payer="employer or town council contract",
    perils=[("heat33", 6, 10), ("haze151", 20, 5)], basis="synthetic: same as construction"),
 "Lower-income households in flood-prone or hotspot areas": dict(n=10000, n_basis="SCENARIO: no public count; PUB lists 55 locations", payer="household, with Enhanced Home Insurance, or a town-council scheme",
    perils=[("rain100", 100, 1)], basis="synthetic: S$100 emergency cash on a 100 mm day; Income's home policy already pays fixed S$300-500 stress and emergency benefits"),
}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--processed", default=str(ROOT / "data/processed")); a = ap.parse_args()
    P = Path(a.processed); out = P / "model"; rng = np.random.default_rng(5)
    cd = pd.read_csv(P / "centre_day.csv.gz", parse_dates=["date"], usecols=["centre_id", "date", "rain"]); cd["y"] = cd.date.dt.year
    cnt = lambda mm: cd[cd.rain >= mm].groupby(["y", "centre_id"]).size().unstack(fill_value=0).reindex(index=range(2010, 2027), fill_value=0)
    rain = {"rain70": cnt(70), "rain100": cnt(100)}
    psi = pd.read_csv(P / "psi_daily.csv", parse_dates=["date"]); psi = psi[psi.date <= "2026-10-31"]; R = ["north", "south", "east", "west", "central"]
    haze = pd.DataFrame({r: (psi[r] >= 151).groupby(psi.date.dt.year).sum() for r in R}).reindex(range(2014, 2027), fill_value=0)
    hw = json.load(open(out / "heat_workers.json")); heat_hist = pd.Series(hw["reconstructed_high_days"]); heat_hist.index = heat_hist.index.astype(int)
    w = pd.read_csv(P / "wbgt_15min.csv.gz", usecols=["station_id", "ts", "value"], parse_dates=["ts"]); w = w[w.ts <= "2026-10-31 23:59"]
    wd = w.groupby(["station_id", w.ts.dt.normalize()]).value.agg(["max", "count"]).reset_index(); wd = wd[wd["count"] >= 80]; wd["y"] = wd.ts.dt.year
    o = wd.groupby(["station_id", "y"]).agg(d=("max", lambda v: (v >= 33).sum()), n=("max", "size")).reset_index()
    o25 = o[(o.y == 2025) & (o.n >= 200)]; fz = (o25.d / o25.n).values; fz = fz / fz.mean(); heat26 = o[(o.y == 2026) & (o.n >= 250)].d.values

    def days(index, cap, upto, yrs):
        """S x locations matrix of capped paid days, resampling real years < upto (yrs = shared year draws)."""
        if index.startswith("rain"):
            t = rain[index].loc[2010:upto - 1]; return np.minimum(t.values[yrs["rain"] % len(t)], cap)
        if index == "haze151":
            t = haze.loc[2014:upto - 1]; return np.minimum(t.values[yrs["haze"] % len(t)], cap)
        h = heat_hist.loc[2010:min(upto - 1, 2025)].values; return np.minimum(rng.poisson(np.outer(h[yrs["heat"] % len(h)], fz)), cap)

    def actual26(index, cap):
        if index.startswith("rain"): return np.minimum(rain[index].loc[2026].values, cap).mean()
        if index == "haze151": return np.minimum(haze.loc[2026].values, cap).mean()
        return np.minimum(heat26, cap).mean()

    def price(seg, upto):
        yrs = {k: rng.integers(0, 10**6, S) for k in ("rain", "haze", "heat")}
        per = sum(pay * days(ix, cap, upto, yrs).mean(1) for ix, pay, cap in seg["perils"])
        split = {ix: pay * days(ix, cap, upto, yrs).mean() for ix, pay, cap in seg["perils"]}
        EL = per.mean(); lay = np.clip(per - 1.5 * EL, 0, 3 * EL); rp = 1.6 * lay.mean()
        prem = EL * (1 + (rp - lay.mean()) / EL + 0.25 * per.std() / EL) / 0.75; net = prem * .8 - per - rp + lay
        return dict(prem=prem, EL=EL, rp=rp, split=split, exp_profit=net.mean(), p_loss=(net < 0).mean(), net=net)

    rows = []; tot = dict(prem26=0, cl26=0, res26=0, prem27=0, prof27=0, people=0)
    for name, seg in SEGMENTS.items():
        p26 = price(seg, 2026); f = 10 / 12; cl = sum(pay * actual26(ix, cap) for ix, pay, cap in seg["perils"])
        rec = float(np.clip(cl / f - 1.5 * p26["EL"], 0, 3 * p26["EL"])) * f; res = p26["prem"] * f * .8 - cl - p26["rp"] * f + rec
        p27 = price(seg, 2027); n = seg["n"]
        rows.append(dict(segment=name, people=n, count_basis=seg["n_basis"], payer=seg["payer"], cover=", ".join(f"{ix} S${pay}/day max {cap}" for ix, pay, cap in seg["perils"]),
            loss_basis=seg["basis"], weekly_premium_2027=round(p27["prem"] / 52, 2), annual_premium_2027=round(p27["prem"], 2),
            premium_split_2027={k: round(v / p27["EL"], 2) for k, v in p27["split"].items()},
            payout_per_person_2026=round(cl, 2), premium_per_person_2026_jan_oct=round(p26["prem"] * f, 2),
            portfolio_2026=dict(premium=round(p26["prem"] * f * n), paid_out=round(cl * n), reins_recovery=round(rec * n), income_result=round(res * n)),
            portfolio_2027=dict(premium=round(p27["prem"] * n), expected_claims=round(p27["EL"] * n), expected_profit=round(p27["exp_profit"] * n), prob_loss_year=round(float(p27["p_loss"]), 3))))
        tot["prem26"] += p26["prem"] * f * n; tot["cl26"] += cl * n; tot["res26"] += res * n; tot["prem27"] += p27["prem"] * n; tot["prof27"] += p27["exp_profit"] * n; tot["people"] += n
    for r in rows:
        print(f"\n{r['segment']}  [{r['people']:,}; {r['count_basis']}]\n  cover: {r['cover']} | 2027: S${r['weekly_premium_2027']}/wk, split {r['premium_split_2027']}"
              f"\n  2026 blind test per person: premium S${r['premium_per_person_2026_jan_oct']}, payout S${r['payout_per_person_2026']} | portfolio {r['portfolio_2026']}\n  2027 portfolio {r['portfolio_2027']}")
    print("\nTOTAL new segments:", {k: round(v) for k, v in tot.items()})
    json.dump(dict(segments=rows, total_new_segments={k: round(v) for k, v in tot.items()}), open(out / "all_segments.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
