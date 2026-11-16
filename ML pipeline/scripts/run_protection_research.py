"""Phase 14 CLI: protection-quality, stress and capital scenarios for M1 vs research designs (advisory, never executable).

    .venv/bin/python -m scripts.run_protection_research [--out DIR]
"""
import argparse
import glob
from pathlib import Path

from src.daycover.protection_research import run

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data/processed/protection-research-v1"))
    a = ap.parse_args(argv)
    if (Path(a.out) / "protection_research_report.json").exists():
        raise SystemExit("output exists; choose a new --out")
    r = run(ROOT / "data/processed/digital-v1.1/digital_receipts.csv", sorted(glob.glob(str(ROOT / "dataset/DayCover_transactions_part_*.csv"))),
            ROOT / "data/processed/psi_daily.csv", ROOT / "data/raw/rainfall_daily_stations_2017_2026.csv",
            ROOT / "data/raw/rainfall_stations.csv", a.out)
    print(r["protection_quality_m1_haze"]); print(r["gauge_disagreement"]); print(r["design_comparison"]["expected_annual_payout_per_policy_sgd"])


if __name__ == "__main__":
    main()
