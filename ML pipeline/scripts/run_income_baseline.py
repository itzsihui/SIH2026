"""Phase 11 CLI: fit the digital-sales baseline on the Phase 10 train split and write a report + scenario panels.

    .venv/bin/python -m scripts.run_income_baseline [--receipts PATH] [--out DIR]
Outputs go to an ignored folder; the dataset and source CSVs are only read.
"""
import argparse
from pathlib import Path

from src.daycover.income_baseline import run

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipts", default=str(ROOT / "data/processed/digital-v1.1/digital_receipts.csv"))
    ap.add_argument("--out", default=str(ROOT / "data/processed/income-baseline-v1"))
    a = ap.parse_args(argv)
    if (Path(a.out) / "baseline_report.json").exists():
        raise SystemExit("output exists; choose a new --out (versions are never overwritten)")
    r = run(a.receipts, a.out)
    for k, v in r["evaluation"].items():
        print(k, {m: {x: round(y, 3) for x, y in s.items() if isinstance(y, float)} for m, s in v.items()})


if __name__ == "__main__":
    main()
