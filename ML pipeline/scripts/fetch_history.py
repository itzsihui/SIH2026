"""Download the full public data history used to train and test the DayCover pricing models.

Run on a machine with normal internet (the team's Windows laptops), from the repo root:
    python scripts/fetch_history.py                 # default: indices, datasets, daily, wbgt
    python scripts/fetch_history.py --only wbgt      # one part only
    python scripts/fetch_history.py --with-met       # also air temperature + humidity (slow)
    python scripts/fetch_history.py --plan           # show what would be fetched, download nothing

Standard library only (no pip install needed). Safe to stop and rerun: finished files are skipped.
Optional: set DATA_GOV_SG_API_KEY (free key from data.gov.sg) for higher rate limits.

Output (git-ignored): data/raw/full/
  indices/oni.txt, indices/dmi.txt          NOAA El Nino (ONI) and Indian Ocean Dipole (DMI), monthly
  datasets/psi_hist.csv                     NEA historical 24-hr PSI by region (data.gov.sg)
  datasets/hawker_centres.geojson           NEA hawker centres with coordinates and stall counts
  daily/<station>_<yyyymm>.csv              weather.gov.sg daily records: rain total, wettest 30/60/120 min, temps, wind
  wbgt/<yyyy-mm-dd>.csv                     NEA WBGT, 15-minute readings, all stations (Feb 2025 onward)
  rain5/<yyyy-mm-dd>.csv                    5-minute rain, only on heavy-rain days (--only rain5, after daily)
  met/<kind>/<yyyy-mm-dd>.csv               (--with-met) air temperature and relative humidity readings
  fetch_log.json                            what was fetched, when, and what was missing
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "full"
API = "https://api-open.data.gov.sg"
API_KEY = os.environ.get("DATA_GOV_SG_API_KEY", "")
UA = "sih2026-fin2-daycover-research"

DAILY_START = (2009, 1)        # weather.gov.sg station history used for rain and temperature
DAILY_END = (2026, 10)         # last complete month
WBGT_START = dt.date(2025, 2, 1)
DATASETS = {
    "psi_hist.csv": "d_b4cf557f8750260d229c49fd768e11ed",          # Historical 24-hr PSI
    "hawker_centres.geojson": "d_4a086da0a5553be1d89383cd90d07ecd",  # Hawker Centres (GEOJSON)
}
INDICES = {
    "oni.txt": "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
    "dmi.txt": "https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data",
}
LOG = {"started": dt.datetime.now().isoformat(timespec="seconds"), "parts": {}}


# ----------------------------------------------------------------------------- http
def http_get(url: str, params: dict | None = None, api: bool = False, tries: int = 6) -> bytes | None:
    """GET with retries. Returns None on 404. Waits out 429 rate limits."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": UA}
    if api and API_KEY:
        headers["x-api-key"] = API_KEY
    i, waits, last = 0, 0, ""
    while i < tries:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=40) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = f"HTTP {e.code}"
            if e.code == 429 and waits < 30:     # rate limit: wait it out, don't count as a failure
                waits += 1
                time.sleep(11 + min(waits, 10))   # data.gov.sg asks for a ~10 s cooldown
                continue
            i += 1
            time.sleep(3 * i)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = type(e).__name__
            i += 1
            time.sleep(3 * i)
    raise RuntimeError(f"failed after {tries} tries ({last}): {url}")


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def months(start: tuple[int, int], end: tuple[int, int]):
    y, m = start
    while (y, m) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def days(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


# ----------------------------------------------------------------------------- parts
def fetch_indices(plan: bool) -> None:
    done = 0
    for name, url in INDICES.items():
        path = OUT / "indices" / name
        if plan or path.exists():
            continue
        data = http_get(url)
        if data:
            write_atomic(path, data)
            done += 1
    LOG["parts"]["indices"] = {"files": len(INDICES), "downloaded_now": done}
    print(f"[indices] ONI and DMI: {len(INDICES)} files ({done} downloaded now)")


def fetch_datasets(plan: bool) -> None:
    done = 0
    for name, ds in DATASETS.items():
        path = OUT / "datasets" / name
        if plan or path.exists():
            continue
        for i in range(8):   # data.gov.sg prepares the file, then returns a signed URL
            meta = json.loads(http_get(f"{API}/v1/public/api/datasets/{ds}/poll-download", api=True))
            url = (meta.get("data") or {}).get("url")
            if url:
                write_atomic(path, http_get(url))
                done += 1
                break
            time.sleep(3 + 2 * i)
        else:
            print(f"  ! could not get download link for {name}")
    LOG["parts"]["datasets"] = {"files": len(DATASETS), "downloaded_now": done}
    print(f"[datasets] PSI history and hawker centres: {len(DATASETS)} files ({done} downloaded now)")


def station_ids() -> list[str]:
    ids = set()
    for f, col in [("rainfall_stations.csv", "id"), ("rainfall_daily_stations_2017_2026.csv", "station_id")]:
        p = ROOT / "data" / "raw" / f
        if p.exists():
            with open(p, newline="", encoding="utf-8-sig") as fh:
                ids.update(r[col].strip() for r in csv.DictReader(fh) if r.get(col, "").strip().startswith("S"))
    return sorted(ids, key=lambda s: int("".join(c for c in s if c.isdigit()) or 0))


def fetch_daily(plan: bool, workers: int) -> None:
    folder = OUT / "daily"
    missing_file = folder / "_missing.json"
    missing = set(json.loads(missing_file.read_text())) if missing_file.exists() else set()
    jobs = [(s, y, m) for s in station_ids() for y, m in months(DAILY_START, DAILY_END)]
    todo = [j for j in jobs if f"{j[0]}_{j[1]}{j[2]:02d}" not in missing
            and not (folder / f"{j[0]}_{j[1]}{j[2]:02d}.csv").exists()]
    print(f"[daily] {len(station_ids())} stations x {len(list(months(DAILY_START, DAILY_END)))} months "
          f"= {len(jobs)} files; {len(todo)} still to try")
    if plan or not todo:
        LOG["parts"]["daily"] = {"jobs": len(jobs), "todo": len(todo)}
        return

    def one(job):
        s, y, m = job
        key = f"{s}_{y}{m:02d}"
        data = http_get(f"https://www.weather.gov.sg/files/dailydata/DAILYDATA_{s}_{y}{m:02d}.csv")
        if data and data[:20].lstrip(b"\xef\xbb\xbf").startswith(b"Station"):
            write_atomic(folder / f"{key}.csv", data)
            return key, True
        return key, False

    got = 0
    folder.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(workers) as ex:
        for n, (key, ok) in enumerate(ex.map(one, todo), 1):
            if ok:
                got += 1
            else:
                missing.add(key)
            if n % 500 == 0:
                missing_file.write_text(json.dumps(sorted(missing)))
                print(f"  {n}/{len(todo)} tried, {got} files saved")
    missing_file.write_text(json.dumps(sorted(missing)))
    LOG["parts"]["daily"] = {"jobs": len(jobs), "saved_now": got, "not_available": len(missing)}
    print(f"[daily] saved {got} files; {len(missing)} station-months have no data (normal for newer stations)")


def fetch_realtime(kind: str, endpoint: str, start: dt.date, end: dt.date, plan: bool, workers: int,
                   only_days: list | None = None) -> None:
    """Fetch one data.gov.sg v2 real-time series day by day, following pagination.
    Writes one long CSV per day: datetime, station_id, station_name, lat, lon, value, extra."""
    folder = OUT / kind
    wanted = only_days if only_days is not None else list(days(start, end))
    todo = [d for d in wanted if not (folder / f"{d.isoformat()}.csv").exists()]
    print(f"[{kind}] {len(wanted)} days wanted ({start} to {end}); {len(todo)} still to fetch")
    if plan or not todo:
        LOG["parts"][kind] = {"todo": len(todo)}
        return

    def one(day: dt.date):
        rows, token, stations = [], None, {}
        while True:
            params = {"date": day.isoformat()}
            if endpoint == "weather":
                params["api"] = "wbgt"
            if token:
                params["paginationToken"] = token
            raw = http_get(f"{API}/v2/real-time/api/{endpoint}", params, api=True)
            if raw is None:
                break
            data = json.loads(raw).get("data") or {}
            if endpoint == "weather":                      # WBGT schema
                for rec in data.get("records", []):
                    for r in (rec.get("item") or {}).get("readings", []):
                        st, loc = r.get("station", {}), r.get("location", {})
                        rows.append([rec.get("datetime"), st.get("id"), st.get("name"), loc.get("latitude"),
                                     loc.get("longtitude") or loc.get("longitude"), r.get("wbgt"), r.get("heatStress")])
            else:                                         # rainfall / air-temperature / relative-humidity schema
                for s in data.get("stations", []):
                    stations[s.get("id")] = s
                for rd in data.get("readings", []):
                    for v in rd.get("data", []):
                        s = stations.get(v.get("stationId"), {})
                        loc = s.get("location") or s.get("labelLocation") or {}
                        rows.append([rd.get("timestamp"), v.get("stationId"), s.get("name"),
                                     loc.get("latitude"), loc.get("longitude"), v.get("value"), ""])
            token = data.get("paginationToken")
            if not token:
                break
        lines = ["datetime,station_id,station_name,lat,lon,value,extra"]
        lines += [",".join("" if x is None else str(x).replace(",", " ") for x in r) for r in rows]
        write_atomic(folder / f"{day.isoformat()}.csv", ("\n".join(lines) + "\n").encode())
        return len(rows)

    def safe(day):
        try:
            return day, one(day), ""
        except Exception as e:            # one bad day must not stop the run; it is retried next time
            return day, None, str(e)

    total, done, failed = 0, 0, []
    with ThreadPoolExecutor(workers) as ex:
        for k, (day, n, err) in enumerate(ex.map(safe, todo), 1):
            if n is None:
                failed.append(day.isoformat())
                print(f"  ! skipped {day}: {err[:120]}")
            else:
                total += n
                done += 1
            if k % 25 == 0:
                print(f"  {k}/{len(todo)} days tried, {done} saved, {total} readings")
    LOG["parts"][kind] = {"days_saved_now": done, "readings": total, "failed_days": failed}
    print(f"[{kind}] saved {done} days, {total} readings; {len(failed)} days failed "
          f"{'(rerun the same command to retry them)' if failed else ''}")


def fetch_station_list(plan: bool) -> None:
    """Rain-gauge coordinates as listed by the real-time API on dates across 2016-2026,
    so discontinued and new gauges are both captured. Writes stations/rain_stations.csv."""
    path = OUT / "stations" / "rain_stations.csv"
    probe = [dt.date(y, m, 15) for y in range(2017, 2027) for m in (1, 7)] + [dt.date(2016, 12, 15)]
    if plan or path.exists():
        print(f"[stations] {len(probe)} probe dates ({'exists' if path.exists() else 'plan'})")
        return
    seen = {}
    for d in probe:
        if d >= dt.date.today():
            continue
        raw = http_get(f"{API}/v2/real-time/api/rainfall", {"date": d.isoformat()}, api=True)
        if not raw:
            continue
        for st in (json.loads(raw).get("data") or {}).get("stations", []):
            loc = st.get("location") or st.get("labelLocation") or {}
            sid = st.get("id")
            if sid and loc.get("latitude") is not None:
                first = seen.get(sid, {}).get("first_seen", d.isoformat())
                seen[sid] = {"id": sid, "name": st.get("name"), "latitude": loc.get("latitude"),
                             "longitude": loc.get("longitude"), "first_seen": first, "last_seen": d.isoformat()}
    lines = ["id,name,latitude,longitude,first_seen,last_seen"] + [
        ",".join(str(v[k]).replace(",", " ") for k in ("id", "name", "latitude", "longitude", "first_seen", "last_seen"))
        for v in sorted(seen.values(), key=lambda x: x["id"])]
    write_atomic(path, ("\n".join(lines) + "\n").encode())
    LOG["parts"]["stations"] = {"stations": len(seen)}
    print(f"[stations] {len(seen)} rain gauges with coordinates")


def geocode_pub_locations(plan: bool) -> None:
    """Geocode PUB flood-prone areas (Nov 2025) and hotspots (Feb 2026) with OneMap search.
    Input: data/raw/pub_flood_locations.csv. Each location has hand-chosen anchor names (a short road,
    a junction road or a landmark). Two anchors -> midpoint (segment or junction). No anchor -> excluded.
    Output: pub/pub_locations_geocoded.csv (one point per location, plus what OneMap matched)."""
    src = ROOT / "data" / "raw" / "pub_flood_locations.csv"
    path = OUT / "pub" / "pub_locations_geocoded.csv"
    with open(src, newline="", encoding="utf-8") as fh:
        locs = list(csv.DictReader(fh))
    if plan:
        print(f"[pub] {len(locs)} PUB locations (plan)")
        return

    def one(q):
        raw = http_get("https://www.onemap.gov.sg/api/common/elastic/search",
                       {"searchVal": q, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": 1})
        res = (json.loads(raw).get("results") or []) if raw else []
        exact = [m for m in res if m.get("SEARCHVAL", "").upper() == q.upper()] or res
        time.sleep(0.25)
        return exact[0] if exact else None

    out = [["list", "sn", "location", "anchor1", "match1", "anchor2", "match2", "lat", "lon", "anchor_gap_km", "note"]]
    for r in locs:
        a1, a2 = r.get("anchor1", ""), r.get("anchor2", "")
        m1 = one(a1) if a1 else None
        m2 = one(a2) if a2 else None
        pts = [(float(m["LATITUDE"]), float(m["LONGITUDE"])) for m in (m1, m2) if m]
        lat = sum(p[0] for p in pts) / len(pts) if pts else ""
        lon = sum(p[1] for p in pts) / len(pts) if pts else ""
        gap = ""
        if len(pts) == 2:
            import math
            gap = round(111.2 * math.hypot(pts[0][0] - pts[1][0], (pts[0][1] - pts[1][1]) * math.cos(math.radians(1.35))), 2)
        out.append([r["list"], r["sn"], r["location"], a1, (m1 or {}).get("SEARCHVAL", ""), a2,
                    (m2 or {}).get("SEARCHVAL", ""), lat, lon, gap, r.get("geocode_note", "")])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(out)
    print(f"[pub] geocoded {sum(1 for x in out[1:] if x[7] != '')} of {len(locs)} locations -> {path.name}")


def rain_event_days(min_daily: float, min_60: float, since: dt.date) -> list:
    """Days when ANY station's daily file shows heavy rain. Only these need 5-minute detail,
    to measure rain inside trading hours. Needs the daily part finished first."""
    found = set()
    for f in sorted((OUT / "daily").glob("S*_*.csv")):
        with open(f, newline="", encoding="latin-1") as fh:
            for r in csv.reader(fh):
                if not r or r[0] == "Station" or len(r) < 7:
                    continue
                try:
                    d = dt.date(int(r[1]), int(r[2]), int(r[3]))
                except ValueError:
                    continue
                def num(x):
                    try:
                        return float(x)
                    except ValueError:
                        return None
                tot, h60 = num(r[4]), num(r[6])
                if d >= since and ((tot is not None and tot >= min_daily) or (h60 is not None and h60 >= min_60)):
                    found.add(d)
    return sorted(found)


# ----------------------------------------------------------------------------- main
def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", help="comma list of: indices,datasets,daily,wbgt,stations,pub,rain5,met")
    p.add_argument("--rain5-all-2026", action="store_true", help="rain5: also fetch every day of 2026 (for the 2026 test)")
    p.add_argument("--rain5-every-day-from", help="rain5: fetch EVERY day from this date (e.g. 2017-01-01), not only heavy-rain days")
    p.add_argument("--rain5-min-daily", type=float, default=40.0, help="rain5: event day if any station >= this mm in a day")
    p.add_argument("--rain5-min-60", type=float, default=20.0, help="rain5: or if any station's wettest hour >= this mm")
    p.add_argument("--with-met", action="store_true", help="also fetch air temperature and humidity (slow)")
    p.add_argument("--met-start", default=WBGT_START.isoformat(), help="first day for --with-met (default 2025-02-01)")
    p.add_argument("--workers", type=int, default=4, help="parallel downloads (keep low to respect rate limits)")
    p.add_argument("--plan", action="store_true", help="print what would be fetched, download nothing")
    a = p.parse_args(argv)

    parts = set((a.only or "indices,datasets,daily,stations,wbgt").split(","))
    if a.with_met:
        parts.add("met")
    yesterday = dt.date.today() - dt.timedelta(days=1)
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Saving to {OUT}{'  (plan only)' if a.plan else ''}")
    t0 = time.time()
    try:
        if "indices" in parts:
            fetch_indices(a.plan)
        if "datasets" in parts:
            fetch_datasets(a.plan)
        if "daily" in parts:
            fetch_daily(a.plan, max(2, a.workers * 2))
        if "wbgt" in parts:
            fetch_realtime("wbgt", "weather", WBGT_START, yesterday, a.plan, a.workers)
        if "pub" in parts:
            geocode_pub_locations(a.plan)
        if "stations" in parts:
            fetch_station_list(a.plan)
        if "rain5" in parts:
            ev = rain_event_days(a.rain5_min_daily, a.rain5_min_60, dt.date(2016, 12, 1))
            if a.rain5_all_2026:
                ev = sorted(set(ev) | set(days(dt.date(2026, 1, 1), yesterday)))
            if a.rain5_every_day_from:
                ev = sorted(set(ev) | set(days(dt.date.fromisoformat(a.rain5_every_day_from), yesterday)))
            print(f"[rain5] {len(ev)} heavy-rain days found in the daily files")
            fetch_realtime("rain5", "rainfall", dt.date(2016, 12, 1), yesterday, a.plan, a.workers, only_days=ev)
        if "met" in parts:
            start = dt.date.fromisoformat(a.met_start)
            fetch_realtime("met/air-temperature", "air-temperature", start, yesterday, a.plan, a.workers)
            fetch_realtime("met/relative-humidity", "relative-humidity", start, yesterday, a.plan, a.workers)
    except KeyboardInterrupt:
        print("\nStopped. Rerun the same command to continue where it left off.")
    finally:
        LOG["finished"] = dt.datetime.now().isoformat(timespec="seconds")
        LOG["minutes"] = round((time.time() - t0) / 60, 1)
        if not a.plan:
            (OUT / "fetch_log.json").write_text(json.dumps(LOG, indent=2))
        print(f"Done in {LOG['minutes']} min.")


if __name__ == "__main__":
    sys.exit(main())
