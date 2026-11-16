"""PostgreSQL + PostGIS database connection layer for DayCover+ 3.0.
Provides thread-safe access to stalls, policies, telemetry readings, and claims.
"""
from __future__ import annotations
import os
import hashlib
import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger("daycover.db")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://daycover:daycover_pass@localhost:5433/daycover")


def get_connection():
    """Returns a new psycopg connection with dict_row row factory."""
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def is_connected() -> bool:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return True
    except Exception as e:
        logger.warning(f"Database connection check failed: {e}")
        return False


def get_all_stalls() -> List[Dict[str, Any]]:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, centre_name, stall_number, lat, lon, 
                           assigned_gauge_id, psi_region, plan,
                           ST_AsText(geom) as geom_wkt
                    FROM stalls 
                    ORDER BY id ASC;
                """)
                return cur.fetchall()
    except Exception as e:
        logger.error(f"Error fetching stalls from DB: {e}")
        return []


def get_stall_by_id(stall_id: str) -> Optional[Dict[str, Any]]:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, centre_name, stall_number, lat, lon, 
                           assigned_gauge_id, psi_region, plan,
                           ST_AsText(geom) as geom_wkt
                    FROM stalls 
                    WHERE id = %s;
                """, (stall_id,))
                return cur.fetchone()
    except Exception as e:
        logger.error(f"Error fetching stall {stall_id}: {e}")
        return None


def get_policy_by_stall(stall_id: str) -> Optional[Dict[str, Any]]:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, stall_id, status, start_date, end_date, 
                           weekly_premium_sgd, annual_rain_events_paid,
                           annual_haze_days_paid, annual_haze_paid_sgd,
                           max_rain_events, max_haze_days, max_haze_amount_sgd,
                           funding_mode
                    FROM policies 
                    WHERE stall_id = %s;
                """, (stall_id,))
                return cur.fetchone()
    except Exception as e:
        logger.error(f"Error fetching policy for stall {stall_id}: {e}")
        return None


def is_centre_closed_on_date(centre_name: str, check_date: date) -> Tuple[bool, Optional[str]]:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT closure_type, description
                    FROM centre_closures
                    WHERE centre_name = %s AND closure_date = %s;
                """, (centre_name, check_date))
                row = cur.fetchone()
                if row:
                    return True, row["description"]
                return False, None
    except Exception as e:
        logger.error(f"Error checking closure for {centre_name} on {check_date}: {e}")
        return False, None


def record_trigger_event(
    event_id: str,
    event_date: date,
    stall_id: str,
    peril: str,
    status: str,
    amount: float,
    reason: str,
    evidence: dict,
    rule_version: str
) -> bool:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO trigger_events 
                    (id, event_date, stall_id, peril, status, amount, reason, evidence_json, rule_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        amount = EXCLUDED.amount,
                        reason = EXCLUDED.reason,
                        evidence_json = EXCLUDED.evidence_json;
                """, (
                    event_id, event_date, stall_id, peril, status, amount, reason,
                    json.dumps(evidence), rule_version
                ))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error recording trigger event: {e}")
        return False


def record_payout(
    payout_id: str,
    event_id: str,
    stall_id: str,
    amount: float,
    idempotency_key: str,
    reference_number: str,
    payment_rail: str = "PAYNOW_FAST"
) -> bool:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO payouts 
                    (id, event_id, stall_id, amount, payment_rail, idempotency_key, reference_number, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'SETTLED')
                    ON CONFLICT (idempotency_key) DO NOTHING;
                """, (
                    payout_id, event_id, stall_id, amount, payment_rail,
                    idempotency_key, reference_number
                ))
                # Update policy usage counters
                cur.execute("""
                    UPDATE policies
                    SET annual_rain_events_paid = annual_rain_events_paid + CASE WHEN %s = 'rain' THEN 1 ELSE 0 END,
                        annual_haze_days_paid = annual_haze_days_paid + CASE WHEN %s = 'haze' THEN 1 ELSE 0 END,
                        annual_haze_paid_sgd = annual_haze_paid_sgd + CASE WHEN %s = 'haze' THEN %s ELSE 0.0 END
                    WHERE stall_id = %s;
                """, (
                    "rain" if "rain" in event_id.lower() else "haze",
                    "haze" if "haze" in event_id.lower() else "rain",
                    "haze" if "haze" in event_id.lower() else "rain",
                    amount,
                    stall_id
                ))
                # Audit log
                cur.execute("""
                    INSERT INTO audit_log (actor, action, entity_type, entity_id, details)
                    VALUES ('PARAMETRIC_ENGINE', 'PAYOUT_DISBURSED', 'PAYOUT', %s, %s);
                """, (payout_id, json.dumps({
                    "amount": amount,
                    "rail": payment_rail,
                    "ref": reference_number,
                    "stall_id": stall_id
                })))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error recording payout: {e}")
        return False


def get_payouts_by_stall(stall_id: str) -> List[Dict[str, Any]]:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT p.id, p.event_id, p.amount, p.payment_rail, 
                           p.idempotency_key, p.reference_number, p.status, p.disbursed_at,
                           e.peril, e.reason, e.evidence_json
                    FROM payouts p
                    LEFT JOIN trigger_events e ON p.event_id = e.id
                    WHERE p.stall_id = %s
                    ORDER BY p.disbursed_at DESC;
                """, (stall_id,))
                return cur.fetchall()
    except Exception as e:
        logger.error(f"Error fetching payouts for stall {stall_id}: {e}")
        return []


def insert_reading(
    station_id: str,
    metric: str,
    observed_at: datetime,
    value: float,
    source: str = "NEA_SINGAPORE",
    is_valid: bool = True
) -> bool:
    payload = f"{source}:{station_id}:{metric}:{observed_at.isoformat()}:{value}"
    payload_hash = hashlib.sha256(payload.encode()).hexdigest()
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO readings 
                    (station_id, metric, observed_at, value, is_valid, source, payload_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (station_id, metric, observed_at) DO NOTHING;
                """, (station_id, metric, observed_at, value, is_valid, source, payload_hash))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error inserting reading: {e}")
        return False
