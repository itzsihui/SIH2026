"""Small, dependency-light client for Singapore open data used by the FIN-2 back-test.
Sources: data.gov.sg (NEA/MSS/PUB/SFA). No API key needed for light use; be polite (rate limits apply).
"""
from __future__ import annotations
import csv, json, time, urllib.request, datetime as dt, socket
from pathlib import Path

# Force IPv4 lookup on systems where IPv6 routes time out
_ORIG_GAI = socket.getaddrinfo
def _ipv4_gai(*args, **kwargs):
    res = _ORIG_GAI(*args, **kwargs)
    v4 = [r for r in res if r[0] == socket.AF_INET]
    return v4 if v4 else res
socket.getaddrinfo = _ipv4_gai

UA = {"User-Agent": "sih2026-fin2-backtest/0.1"}
REALTIME = "https://api-open.data.gov.sg/v2/real-time/api"
DATASTORE = "https://data.gov.sg/api/action/datastore_search"

DATASETS = {  # dataset ids verified 7 Nov 2026
    "psi_24hr_history": "d_b4cf557f8750260d229c49fd768e11ed",       # hourly 24-hr PSI by region, Apr 2014 -> ~1 Oct 2026
    "daily_weather_records": "d_03bb2eb67ad645d0188342fa74ad7066",   # Admiralty only, 2009-2017, rainfall/temp
    "hawker_centres": "d_68a42f09f350881996d83f9cd73ab02f",          # name, address, stall counts (107 rows)
    "hawker_closures": "d_bda4baa634dd1cc7a6c7cad5f19e2d68",         # cleaning closures + lat/long (123 rows)
    "hawker_stalls_annual": "d_894e84243d69d55c13b357dbad4e6350",
}

def _get(url: str, tries: int = 6):
    last = None
    for k in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40))
        except Exception as e:  # network or rate limit
            last = e
            time.sleep(2 + 2 * k)
    raise RuntimeError(f"failed {url}: {last}")

def datastore_all(dataset_id: str, page: int = 5000):
    """Download every row of a CSV-type dataset through the datastore API."""
    first = _get(f"{DATASTORE}?resource_id={dataset_id}&limit=1")["result"]
    fields = [f["id"] for f in first["fields"]]
    total, rows, off = first.get("total", 0), [], 0
    while off < total:
        batch = _get(f"{DATASTORE}?resource_id={dataset_id}&limit={page}&offset={off}")["result"]["records"]
        if not batch:
            break
        rows += batch
        off += len(batch)
    return fields, rows

def save_csv(path: Path, fields, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})

def psi_day(date: str):
    """Max 24-hr PSI per region for one calendar day via the real-time API (date=YYYY-MM-DD)."""
    j = _get(f"{REALTIME}/psi?date={date}")
    best = {r: 0 for r in ("north", "south", "east", "west", "central")}
    n = 0
    for it in j["data"]["items"]:
        r = it["readings"].get("psi_twenty_four_hourly")
        if r:
            n += 1
            for k in best:
                best[k] = max(best[k], r.get(k) or 0)
    return {"date": date, **best, "n_hours": n}

def psi_range(start: dt.date, end: dt.date, pause: float = 0.4):
    out, d = [], start
    while d <= end:
        out.append(psi_day(d.isoformat()))
        time.sleep(pause)
        d += dt.timedelta(1)
    return out

def rainfall_day(date: str):
    """5-minute rainfall readings (mm) for all stations on one day; follows pagination."""
    stations, readings, token = {}, [], None
    while True:
        url = f"{REALTIME}/rainfall?date={date}" + (f"&paginationToken={token}" if token else "")
        j = _get(url)["data"]
        for s in j["stations"]:
            stations[s["id"]] = s
        readings += j["readings"]
        token = j.get("paginationToken")
        if not token:
            return stations, readings

def wbgt_day(date: str):
    """WBGT readings (about every 15 min) per station; only available from Feb 2025; follows pagination."""
    records, token = [], None
    while True:
        url = f"{REALTIME}/weather?api=wbgt&date={date}" + (f"&paginationToken={token}" if token else "")
        j = _get(url)["data"]
        records += j.get("records", [])
        token = j.get("paginationToken")
        if not token:
            return records
