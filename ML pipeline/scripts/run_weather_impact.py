"""Phase 12 CLI: weather-impact audit + advisory model comparison on the Phase 10 digital dataset (train-only fits).

    .venv/bin/python -m scripts.run_weather_impact [--out DIR]
"""
import argparse
import glob
from pathlib import Path

from src.daycover.weather_impact import run

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipts", default=str(ROOT / "data/processed/digital-v1.1/digital_receipts.csv"))
    ap.add_argument("--source", nargs="*", default=sorted(glob.glob(str(ROOT / "dataset/DayCover_transactions_part_*.csv"))))
    ap.add_argument("--psi", default=str(ROOT / "data/processed/psi_daily.csv"))
    ap.add_argument("--rain", default=str(ROOT / "data/raw/rainfall_daily_stations_2017_2026.csv"))
    ap.add_argument("--out", default=str(ROOT / "data/processed/weather-impact-v1"))
    a = ap.parse_args(argv)
    if (Path(a.out) / "weather_impact_report.json").exists():
        raise SystemExit("output exists; choose a new --out (versions are never overwritten)")
    r = run(a.receipts, a.source, a.psi, a.rain, a.out)
    print(r["comparison"]["candidate_adoption"])


if __name__ == "__main__":
    main()
