"""Load real historical NEA readings and replayed engine events into the local Postgres (idempotent).

readings: metric psi_24hr_daily_max (station = region), rain_daily_mm / rain_max_1h_mm (station = gauge id).
trigger_events: engine replay 2015-2025, every status (paid/capped/excluded/shadow/pending), rule_version stored.
Run: .venv/bin/python -m scripts.load_history
"""
import hashlib, json
from datetime import date, datetime, timezone, timedelta
from psycopg.types.json import Jsonb
from src.daycover import data, db
from src.daycover.engine import replay
from src.daycover.rules import DEFAULT_RULES as R

SGT = timezone(timedelta(hours=8))


def ts(d: date):
    return datetime(d.year, d.month, d.day, 0, 0, tzinfo=SGT)


def h(*parts):
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()


def main():
    rows = []
    for d, regs in data.psi_daily().items():
        for reg, v in regs.items():
            rows.append((reg, "psi_24hr_daily_max", ts(d), v, True, "NEA_HISTORY_CSV", h(reg, d, v)))
    for (d, g), r in data.rain_daily_table().items():
        rows.append((g, "rain_daily_mm", ts(d), r["mm"], r["valid"], "NEA_HISTORY_CSV", h(g, d, "mm", r["mm"])))
        rows.append((g, "rain_max_1h_mm", ts(d), r["max_1h"], r["valid"], "NEA_HISTORY_CSV", h(g, d, "1h", r["max_1h"])))
    stalls = data.load_stalls("haze+rain")
    start, end = date(2015, 1, 1), date(2025, 12, 31)
    evs = replay(stalls, start, end, R)
    event_rows = [(f"{e.date}-{e.stall_id}-{e.peril}", e.date, e.stall_id, e.peril, e.status,
                   e.amount, e.reason, Jsonb(e.evidence), e.rule_version) for e in evs]
    with db.get_connection() as conn, conn.cursor() as cur:
        cur.executemany("""INSERT INTO readings (station_id, metric, observed_at, value, is_valid, source, payload_hash)
                           VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT ON CONSTRAINT uq_station_metric_time DO NOTHING""", rows)
        # Generated replay events use date-stall-peril IDs; simulated payouts use separate IDs.
        cur.executemany("""INSERT INTO trigger_events (id, event_date, stall_id, peril, status, amount, reason, evidence_json, rule_version)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET
                           status = EXCLUDED.status, amount = EXCLUDED.amount, reason = EXCLUDED.reason,
                           evidence_json = EXCLUDED.evidence_json, rule_version = EXCLUDED.rule_version
                           WHERE NOT EXISTS (SELECT 1 FROM payouts WHERE event_id = trigger_events.id)""", event_rows)
        cur.execute("""DELETE FROM trigger_events e WHERE e.event_date BETWEEN %s AND %s
                       AND e.id = to_char(e.event_date, 'YYYY-MM-DD') || '-' || e.stall_id || '-' || e.peril
                       AND e.id <> ALL(%s)
                       AND NOT EXISTS (SELECT 1 FROM payouts WHERE event_id = e.id)""",
                    (start, end, [row[0] for row in event_rows]))
        cur.execute("select count(*) from readings"); nr = cur.fetchone()["count"]
        cur.execute("select count(*) from trigger_events"); ne = cur.fetchone()["count"]
    print(f"readings now {nr}, trigger_events now {ne} (loaded {len(rows)} reading rows, {len(evs)} replayed events)")


if __name__ == "__main__":
    main()
