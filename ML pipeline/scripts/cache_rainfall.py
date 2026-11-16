"""Robust, resumable station-level rainfall cache pipeline for data.gov.sg real-time API.

Design rules (Audit 4 compliant):
- Writes ONE file per date: data/raw/rain_cache/YYYY-MM-DD.csv (atomic write via .tmp).
- data/raw/rain_cache/ is in .gitignore; git branch operations cannot touch it.
- Never marks a date as done or saves partial data if an API error occurs.
- On HTTP 429 (Too Many Requests), sleeps 11 seconds to respect the server cooldown.
- Tracks real progress from actual files on disk (cannot report 709 if only 314 exist).
- Merges into data/raw/rainfall_daily_stations_2017_2026.csv only after ALL 709 dates are present.
- Asserts 709 unique dates and prints month-by-year validation matrix.
"""
from __future__ import annotations
import sys, time, json, random, math, threading, datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pandas as pd
import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import sg_data

DATA_DIR = ROOT / "data" / "raw"
CACHE_DIR = DATA_DIR / "rain_cache"
CACHE_FILE = DATA_DIR / "rainfall_daily_stations_2017_2026.csv"
PROGRESS_FILE = DATA_DIR / "rainfall_cache_progress.json"
DATES_FILE = DATA_DIR / "rainfall_stratified_dates_709.json"

SCHEMA_COLS = [
    "date", "station_id", "station_name",
    "daily_rainfall_mm", "trading_hours_rainfall_mm", "max_1h_rainfall_mm",
    "reading_count", "coverage_pct", "is_valid_day"
]

def load_or_generate_target_dates(target_count: int = 709, seed: int = 42) -> list[str]:
    """Load the deterministic 709 stratified dates list, or generate if missing."""
    if DATES_FILE.exists():
        with open(DATES_FILE) as f:
            dates = json.load(f)
            if len(dates) == target_count:
                return sorted(dates)
                
    random.seed(seed)
    start_date = dt.date(2017, 1, 1)
    end_date = dt.date(2026, 11, 7)
    
    months = {}
    curr = start_date
    while curr <= end_date:
        ym = (curr.year, curr.month)
        if ym not in months:
            months[ym] = []
        months[ym].append(curr.isoformat())
        curr += dt.timedelta(days=1)
        
    total_calendar_days = sum(len(days) for days in months.values())
    
    sampled_dates = []
    for ym, days in sorted(months.items()):
        prop = len(days) / total_calendar_days
        n_sample = max(1, round(target_count * prop))
        n_sample = min(n_sample, len(days))
        chosen = sorted(random.sample(days, n_sample))
        sampled_dates.extend(chosen)
        
    sampled_dates = sorted(list(set(sampled_dates)))
    with open(DATES_FILE, "w") as f:
        json.dump(sampled_dates, f, indent=2)
    return sampled_dates

THREAD_LOCAL = threading.local()

def get_session(worker_id: int) -> requests.Session:
    if not hasattr(THREAD_LOCAL, "session"):
        s = requests.Session()
        s.headers.update({"User-Agent": f"sih2026-fin2-w{worker_id}"})
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=5,
            pool_maxsize=5,
            max_retries=0
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        THREAD_LOCAL.session = s
    return THREAD_LOCAL.session

def fetch_single_date(d_str: str, worker_id: int = 0) -> list[dict]:
    """Fetch all 5-minute readings for a calendar date, handling pagination and rate limits.
    Returns: list of station row dictionaries, or raises Exception on persistent failure.
    """
    url_base = "https://api-open.data.gov.sg/v2/real-time/api/rainfall"
    session = get_session(worker_id)
    
    stations = {}
    readings = []
    token = None
    rate_limit_hits = 0
    general_retries = 0
    
    while True:
        params = {"date": d_str}
        if token:
            params["paginationToken"] = token
            
        try:
            resp = session.get(url_base, params=params, timeout=25)
            if resp.status_code == 429:
                rate_limit_hits += 1
                if rate_limit_hits > 15:
                    raise RuntimeError(f"Excessive 429 rate limits ({rate_limit_hits}) for {d_str}")
                # Data.gov.sg asks for 10s cooldown
                time.sleep(11.0)
                continue
                
            if resp.status_code != 200:
                general_retries += 1
                if general_retries > 5:
                    raise RuntimeError(f"HTTP {resp.status_code} for {d_str} after {general_retries} retries: {resp.text[:200]}")
                time.sleep(2.0 * general_retries)
                continue
                
            j = resp.json()
            data = j.get("data")
            if data is None:
                general_retries += 1
                if general_retries > 5:
                    raise RuntimeError(f"Null data field for {d_str} after {general_retries} retries: {j}")
                time.sleep(2.0 * general_retries)
                continue
                
            for s in data.get("stations", []):
                stations[s["id"]] = s
            readings += data.get("readings", [])
            token = data.get("paginationToken")
            if not token:
                break
            time.sleep(0.15)  # polite pacing between pages
            
        except requests.exceptions.RequestException as e:
            general_retries += 1
            if general_retries > 5:
                raise RuntimeError(f"Network error for {d_str} after {general_retries} retries: {e}")
            time.sleep(2.0 * general_retries)
            
    if not stations:
        raise RuntimeError(f"No stations returned by API for {d_str}")
        
    st_readings = {sid: [] for sid in stations}
    for item in readings:
        ts = item.get("timestamp", "")
        for entry in item.get("data", []):
            sid = entry.get("stationId")
            val = float(entry.get("value", 0.0))
            if sid in st_readings:
                st_readings[sid].append((ts, val))

    rows = []
    for sid, ts_vals in st_readings.items():
        if not ts_vals:
            continue
        ts_vals.sort(key=lambda x: x[0])
        reading_count = len(ts_vals)
        coverage_pct = round(reading_count / 288.0 * 100.0, 2)
        is_valid = bool(reading_count >= 259)
        
        vals_all = [x[1] for x in ts_vals]
        daily_tot = round(float(sum(vals_all)), 2)
        
        trading_vals = [x[1] for x in ts_vals if "08:00:00" <= x[0][11:19] <= "20:00:00"]
        trading_tot = round(float(sum(trading_vals)), 2)
        
        arr = np.array(vals_all)
        if len(arr) >= 12:
            rolling_1h = np.convolve(arr, np.ones(12), mode="valid")
            max_1h = round(float(np.max(rolling_1h)), 2)
        else:
            max_1h = daily_tot
            
        st_name = stations[sid].get("name", sid) if sid in stations else sid
        rows.append({
            "date": d_str,
            "station_id": sid,
            "station_name": st_name,
            "daily_rainfall_mm": daily_tot,
            "trading_hours_rainfall_mm": trading_tot,
            "max_1h_rainfall_mm": max_1h,
            "reading_count": reading_count,
            "coverage_pct": coverage_pct,
            "is_valid_day": is_valid
        })
        
    return rows

def is_date_cached(d_str: str) -> bool:
    """Check whether a date is already completely cached on disk."""
    fpath = CACHE_DIR / f"{d_str}.csv"
    if not fpath.exists():
        return False
    try:
        df = pd.read_csv(fpath)
        return len(df) > 0 and set(SCHEMA_COLS).issubset(set(df.columns))
    except Exception:
        return False

def save_date_cache(d_str: str, rows: list[dict]):
    """Atomically write a date's station rows to disk."""
    fpath = CACHE_DIR / f"{d_str}.csv"
    tmp_path = CACHE_DIR / f"{d_str}.csv.tmp"
    df = pd.DataFrame(rows)[SCHEMA_COLS]
    df.to_csv(tmp_path, index=False)
    tmp_path.rename(fpath)

PROGRESS_LOCK = threading.Lock()

def update_progress(all_target_dates: list[str], last_date: str, t_start: float, n_target: int, n_cached_init: int):
    cached_files = list(CACHE_DIR.glob("*.csv"))
    n_done = len(cached_files)
    elapsed = time.time() - t_start
    n_new = max(0, n_done - n_cached_init)
    rate = elapsed / n_new if n_new > 0 else 0.0
    remaining_dates = max(0, n_target - n_done)
    eta_sec = rate * remaining_dates
    
    prog = {
        "total_target_dates": n_target,
        "completed_dates": n_done,
        "percent_complete": round(n_done / n_target * 100, 2),
        "current_date": last_date,
        "elapsed_seconds": round(elapsed, 1),
        "estimated_remaining_seconds": round(eta_sec, 1),
        "last_updated": dt.datetime.now().isoformat()
    }
    with open(PROGRESS_FILE, "w") as f:
        json.dump(prog, f, indent=2)
    return n_done, eta_sec

def run_cache():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    all_dates = load_or_generate_target_dates(target_count=709, seed=42)
    n_target = len(all_dates)
    print(f"=== RAINFALL CACHE INITIALIZATION (Audit 4 Compliance) ===", flush=True)
    print(f"Total target dates: {n_target} (2017-01-01 to 2026-11-07)", flush=True)
    
    # Check already cached dates on disk
    cached_dates = {p.stem for p in CACHE_DIR.glob("*.csv") if is_date_cached(p.stem)}
    n_cached_init = len(cached_dates)
    missing_dates = [d for d in all_dates if d not in cached_dates]
    
    print(f"Already cached on disk: {n_cached_init} dates.", flush=True)
    print(f"Missing dates to fetch: {len(missing_dates)} dates.", flush=True)
    
    if not missing_dates:
        print("All 709 dates are already cached!", flush=True)
    else:
        # Sort missing dates chronologically
        to_fetch = sorted(missing_dates)
        t_start = time.time()
        
        def worker_task(d, wid):
            t0 = time.time()
            max_attempts = 4
            for attempt in range(1, max_attempts + 1):
                try:
                    rows = fetch_single_date(d, worker_id=wid)
                    save_date_cache(d, rows)
                    dur = time.time() - t0
                    valid_cnt = sum(1 for r in rows if r["is_valid_day"])
                    drop_cnt = len(rows) - valid_cnt
                    with PROGRESS_LOCK:
                        n_done, eta_sec = update_progress(all_dates, d, t_start, n_target, n_cached_init)
                        print(f"[{n_done}/{n_target}] {d}: {len(rows)} stns ({valid_cnt} v, {drop_cnt} d, {dur:.1f}s) | ETA: {eta_sec/60:.1f}m", flush=True)
                    time.sleep(0.2)
                    return d
                except Exception as e:
                    print(f"Attempt {attempt}/{max_attempts} failed for {d}: {e}", flush=True)
                    if attempt < max_attempts:
                        time.sleep(5.0 * attempt)
                    else:
                        raise e

        # 2 worker threads with polite pacing avoids 429 throttling
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {executor.submit(worker_task, d, i % 2): d for i, d in enumerate(to_fetch)}
            for future in as_completed(futures):
                d = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"CRITICAL ERROR on {d}: {e}", flush=True)

    # Validate that ALL 709 dates exist
    final_cached = {p.stem for p in CACHE_DIR.glob("*.csv") if is_date_cached(p.stem)}
    missing_final = set(all_dates) - final_cached
    if missing_final:
        print(f"ERROR: {len(missing_final)} dates still missing: {sorted(list(missing_final))[:10]}...", flush=True)
        sys.exit(1)
        
    print(f"\nAll {len(all_dates)} dates successfully present in {CACHE_DIR}!", flush=True)
    print("Building merged CSV: data/raw/rainfall_daily_stations_2017_2026.csv...", flush=True)
    
    dfs = []
    for d in all_dates:
        fpath = CACHE_DIR / f"{d}.csv"
        dfs.append(pd.read_csv(fpath))
    merged_df = pd.concat(dfs, ignore_index=True)
    merged_df = merged_df.drop_duplicates(subset=["date", "station_id"]).sort_values(["date", "station_id"])
    
    tmp_merged = DATA_DIR / "rainfall_daily_stations_2017_2026.csv.tmp"
    merged_df.to_csv(tmp_merged, index=False)
    tmp_merged.rename(CACHE_FILE)
    print(f"Merged CSV written to {CACHE_FILE}: {len(merged_df)} total station rows across {merged_df['date'].nunique()} dates.", flush=True)
    
    # Coverage validation table
    merged_df["dt"] = pd.to_datetime(merged_df["date"])
    merged_df["year"] = merged_df["dt"].dt.year
    merged_df["month"] = merged_df["dt"].dt.month
    
    date_matrix = merged_df.groupby(["year", "month"])["date"].nunique().unstack(fill_value=0)
    print("\n=== COVERAGE TABLE (Dates per Year x Month) ===")
    print(date_matrix.to_string())
    print("\nTotal dates by month:")
    print(merged_df.groupby("month")["date"].nunique())
    print("\nTotal dates by year:")
    print(merged_df.groupby("year")["date"].nunique())
    
    valid_st_days = merged_df["is_valid_day"].sum()
    total_st_days = len(merged_df)
    drop_st_days = total_st_days - valid_st_days
    mean_rain = merged_df.loc[merged_df["is_valid_day"], "daily_rainfall_mm"].mean()
    dry_pct = (merged_df.loc[merged_df["is_valid_day"], "daily_rainfall_mm"] == 0.0).mean() * 100
    r50_pct = (merged_df.loc[merged_df["is_valid_day"], "daily_rainfall_mm"] >= 50.0).mean() * 100
    
    print("\n=== CLIMATOLOGICAL SUMMARY ===")
    print(f"Total station-days: {total_st_days}")
    print(f"Valid station-days (>=90%): {valid_st_days} ({valid_st_days/total_st_days*100:.2f}%)")
    print(f"Dropped station-days (<90%): {drop_st_days} ({drop_st_days/total_st_days*100:.2f}%)")
    print(f"Mean daily rainfall (valid): {mean_rain:.2f} mm/day")
    print(f"Dry days (0.0 mm): {dry_pct:.2f}%")
    print(f"Heavy rain days (>=50 mm): {r50_pct:.2f}%")

if __name__ == "__main__":
    run_cache()
