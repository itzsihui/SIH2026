"""Loads the verified open-data files and answers: which gauge / PSI region / closure applies to a stall."""
from __future__ import annotations
import csv, math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"

# approximate NEA PSI region centroids (lat, lon); nearest-centroid is an approximation, flagged in the docs
REGION_CENTROIDS = {"north": (1.42, 103.82), "south": (1.28, 103.83), "east": (1.35, 103.95),
                    "west": (1.35, 103.70), "central": (1.35, 103.82)}


def km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def psi_region(lat: float, lon: float) -> str:
    return min(REGION_CENTROIDS, key=lambda k: km((lat, lon), REGION_CENTROIDS[k]))


@dataclass
class Stall:
    id: str
    centre: str
    lat: float
    lon: float
    region: str = ""
    gauge: str = ""
    plan: str = "haze+rain"          # haze | rain | haze+rain
    closures: Set[date] = field(default_factory=set)


def _d(s: str) -> Optional[date]:
    s = (s or "").strip()
    for f in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def _span(a: Optional[date], b: Optional[date]) -> Set[date]:
    if not a or not b or b < a:
        return set()
    return {a + timedelta(days=i) for i in range((b - a).days + 1)}


@lru_cache(maxsize=1)
def psi_daily() -> Dict[date, Dict[str, float]]:
    out = {}
    with open(RAW / "psi_daily_max_combined_2014_2026.csv") as f:
        for r in csv.DictReader(f):
            out[date.fromisoformat(r["date"])] = {k: float(v) for k, v in r.items() if k != "date" and v not in ("", None)}
    return out


@lru_cache(maxsize=1)
def gauges() -> Dict[str, Tuple[float, float]]:
    with open(RAW / "rainfall_stations.csv") as f:
        return {r["id"]: (float(r["latitude"]), float(r["longitude"])) for r in csv.DictReader(f)}


@lru_cache(maxsize=1)
def rain_daily_table() -> Dict[Tuple[date, str], dict]:
    """(date, gauge) -> {mm, max_1h, valid}. Only the sampled dates exist; absence = unknown, never zero."""
    out = {}
    with open(RAW / "rainfall_daily_stations_2017_2026.csv") as f:
        for r in csv.DictReader(f):
            out[(date.fromisoformat(r["date"]), r["station_id"])] = {
                "mm": float(r["daily_rainfall_mm"]), "max_1h": float(r["max_1h_rainfall_mm"]),
                "valid": r["is_valid_day"] == "True"}
    return out


@lru_cache(maxsize=1)
def rain_dates() -> Set[date]:
    return {d for d, _ in rain_daily_table()}


def nearest_gauges(lat: float, lon: float, n: int = 5) -> List[Tuple[str, float]]:
    return sorted(((g, km((lat, lon), c)) for g, c in gauges().items()), key=lambda x: x[1])[:n]


def load_stalls(plan: str = "haze+rain") -> List[Stall]:
    """One representative stall per NEA hawker centre (123 in the closures dataset)."""
    stalls = []
    with open(RAW / "hawker_closures.csv") as f:
        for i, r in enumerate(csv.DictReader(f), 1):
            try:
                lat, lon = float(r["latitude_hc"]), float(r["longitude_hc"])
            except ValueError:
                continue
            cl: Set[date] = set()
            for q in ("q1", "q2", "q3", "q4"):
                cl |= _span(_d(r[f"{q}_cleaningstartdate"]), _d(r[f"{q}_cleaningenddate"]))
            cl |= _span(_d(r["other_works_startdate"]), _d(r["other_works_enddate"]))
            s = Stall(id=f"HC{i:03d}", centre=r["name"], lat=lat, lon=lon, plan=plan, closures=cl)
            s.region = psi_region(lat, lon)
            s.gauge = nearest_gauges(lat, lon, 1)[0][0]
            stalls.append(s)
    return stalls
