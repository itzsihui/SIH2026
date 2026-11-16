"""Phase 13 audit: reproducible advisory recommendations and access/error comparison across digital-history groups.

    .venv/bin/python -m scripts.run_recommendation_audit [--as-of 2025-11-01] [--out DIR]
Groups are defined only from digital observation counts (no cash share, no sensitive attributes). Synthetic data only.
"""
import argparse
import glob
import json
from pathlib import Path

import pandas as pd

from src.daycover.income_baseline import daily_digital, load_receipts
from src.daycover.recommendation import config_hash, load_config, recommend
from src.daycover.weather_impact import merchant_meta

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2025-11-01")
    ap.add_argument("--out", default=str(ROOT / "data/processed/recommendation-audit-v1"))
    a = ap.parse_args(argv)
    out = Path(a.out)
    if (out / "audit.json").exists():
        raise SystemExit("output exists; choose a new --out")
    cfg = load_config()
    d = daily_digital(load_receipts(ROOT / "data/processed/digital-v1.1/digital_receipts.csv"))
    psi = pd.read_csv(ROOT / "data/processed/psi_daily.csv")
    meta = merchant_meta(sorted(glob.glob(str(ROOT / "dataset/DayCover_transactions_part_*.csv")))).set_index("merchant_id")
    lite = d[["merchant_id", "trading_day", "digital_cents"]]
    cfgw = cfg["assumptions"]["history_window_days"]
    recent = lite[(lite.trading_day < a.as_of) & (lite.trading_day >= (pd.Timestamp(a.as_of) - pd.Timedelta(days=cfgw)).date().isoformat())]
    cnt = recent.groupby("merchant_id").size().reindex(meta.index).fillna(0)
    grp = pd.qcut(cnt.rank(method="first"), 3, labels=["low_digital_history", "mid_digital_history", "high_digital_history"])
    rows = []
    for m in meta.index:
        r = recommend(m, meta.loc[m, "psi_region"], a.as_of, lite, psi, True, cfg)
        r0 = recommend(m, meta.loc[m, "psi_region"], a.as_of, lite, psi, False, cfg)
        rows.append({"merchant_id": m, "group": str(grp[m]), "observed_days": int(cnt[m]), "mode": r["recommendation"]["mode"],
                     "band": r["recommendation"]["band"], "reason": r["recommendation"]["reason"],
                     "no_consent_band": r0["recommendation"]["band"], "burden_m1": r.get("affordability", {}).get("M1_FIXED", {}).get("premium_share_of_low_digital_sales")})
    df = pd.DataFrame(rows)
    summ = {g: {"merchants": int(len(x)), "data_informed_share": float((x["mode"] == "data_informed").mean()),
                "band_counts": x["band"].value_counts().to_dict(),
                "fixed_default_reasons": x.loc[x["mode"] != "data_informed", "reason"].value_counts().to_dict(),
                "median_m1_burden": None if x.burden_m1.dropna().empty else float(x.burden_m1.median())}
            for g, x in df.groupby("group")}
    rep = {"as_of": a.as_of, "config_sha256": config_hash(cfg), "model_version": cfg["version"], "groups": summ,
           "no_consent_always_fixed_m1": bool((df.no_consent_band == "M1_FIXED").all()),
           "cash_features": False, "advisory_only": True, "provenance": "calibrated_synthetic_only",
           "note": "Access = receiving a data-informed option; fixed M1 remains available to all and is never a penalty."}
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(rep, indent=1, sort_keys=True))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
