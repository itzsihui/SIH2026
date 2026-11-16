"""Generate migrations/02_seed_data.sql from data/raw CSVs."""
from datetime import date
from pathlib import Path
import csv
import hashlib

from src.daycover import data

ROOT = Path(__file__).resolve().parents[1]
OUT_SQL = ROOT / "migrations" / "02_seed_data.sql"

def escape_sql(val: str) -> str:
    return val.replace("'", "''")

def main():
    lines = [
        "-- DayCover+ 3.0 Seed Data",
        "-- Auto-generated from verified Singapore NEA open dataset",
        "",
        "BEGIN;",
        ""
    ]

    stalls = data.load_stalls()
    print(f"Loaded {len(stalls)} stalls from dataset.")

    # 1. Insert stalls
    lines.append("-- 1. Insert 123 Hawker Centres & Assigned Sovereign Gauges")
    for s in stalls:
        name = escape_sql(s.centre)
        lines.append(
            f"INSERT INTO stalls (id, centre_name, stall_number, lat, lon, geom, assigned_gauge_id, psi_region, plan) "
            f"VALUES ('{s.id}', '{name}', '#01-01', {s.lat}, {s.lon}, ST_SetSRID(ST_MakePoint({s.lon}, {s.lat}), 4326), '{s.gauge}', '{s.region}', 'haze+rain') "
            f"ON CONFLICT (id) DO NOTHING;"
        )

    lines.append("")
    # 2. Insert active policies for each stall
    lines.append("-- 2. Insert Active Policies (Enforcing V1.0 Caps: Max 1 Rain Event, Max 5 Haze Days, Hard S$150 Cap)")
    for s in stalls:
        pol_id = f"POL-2026-{s.id}"
        lines.append(
            f"INSERT INTO policies (id, stall_id, status, start_date, end_date, weekly_premium_sgd, annual_rain_events_paid, annual_haze_days_paid, annual_haze_paid_sgd, max_rain_events, max_haze_days, max_haze_amount_sgd, funding_mode) "
            f"VALUES ('{pol_id}', '{s.id}', 'ACTIVE', '2026-01-01', '2026-12-31', 2.00, 0, 0, 0.00, 1, 5, 150.00, 'SUBSCRIPTION') "
            f"ON CONFLICT (id) DO NOTHING;"
        )

    lines.append("")
    # 3. Insert centre closures from hawker_closures.csv
    lines.append("-- 3. Insert Scheduled Cleaning Closures (Automated Claim Suppression)")
    with open(data.RAW / "hawker_closures.csv") as f:
        reader = csv.DictReader(f)
        for r in reader:
            name = escape_sql(r["name"])
            for q in ("q1", "q2", "q3", "q4"):
                s_d = data._d(r[f"{q}_cleaningstartdate"])
                e_d = data._d(r[f"{q}_cleaningenddate"])
                if s_d and e_d:
                    cur = s_d
                    while cur <= e_d:
                        lines.append(
                            f"INSERT INTO centre_closures (centre_name, closure_date, closure_type, description) "
                            f"VALUES ('{name}', '{cur.isoformat()}', '{q}', 'NEA Scheduled {q.upper()} Spring Cleaning Washdown') "
                            f"ON CONFLICT (centre_name, closure_date) DO NOTHING;"
                        )
                        cur += data.timedelta(days=1)
            # other works / R&R
            s_d = data._d(r["other_works_startdate"])
            e_d = data._d(r["other_works_enddate"])
            if s_d and e_d:
                cur = s_d
                while cur <= e_d:
                    lines.append(
                        f"INSERT INTO centre_closures (centre_name, closure_date, closure_type, description) "
                        f"VALUES ('{name}', '{cur.isoformat()}', 'r_and_r', 'NEA Scheduled Repairs and Redecoration (R&R)') "
                        f"ON CONFLICT (centre_name, closure_date) DO NOTHING;"
                    )
                    cur += data.timedelta(days=1)

    lines.append("")
    # 4. Insert sample sovereign readings from 2026
    lines.append("-- 4. Insert Verified Sovereign Telemetry Baseline (with Cryptographic SHA-256 Hashes)")
    psi_dict = data.psi_daily()
    sample_psi_dates = [d for d in psi_dict.keys() if d.year >= 2024][-30:]
    for d in sample_psi_dates:
        for reg, val in psi_dict[d].items():
            payload = f"NEA_PSI:{reg}:{d.isoformat()}:{val}"
            p_hash = hashlib.sha256(payload.encode()).hexdigest()
            lines.append(
                f"INSERT INTO readings (station_id, metric, observed_at, value, is_valid, source, payload_hash) "
                f"VALUES ('REGION_{reg.upper()}', 'psi_24hr', '{d.isoformat()} 18:00:00+08', {val}, TRUE, 'NEA_SINGAPORE', '{p_hash}') "
                f"ON CONFLICT (station_id, metric, observed_at) DO NOTHING;"
            )

    lines.append("")
    # Audit log entry for initial seed
    lines.append("-- 5. Seed Audit Log Event")
    lines.append(
        "INSERT INTO audit_log (actor, action, entity_type, entity_id, details) "
        "VALUES ('SYSTEM_MIGRATION', 'SEED_V1_SCHEMA', 'DATABASE', 'SCHEMA_V1', '{\"version\": \"1.0.0\", \"stalls\": 123, \"status\": \"INITIALIZED\"}'::jsonb);"
    )

    lines.append("")
    lines.append("COMMIT;")

    OUT_SQL.write_text("\n".join(lines))
    print(f"Generated {OUT_SQL} with {len(lines)} lines.")

if __name__ == "__main__":
    main()
