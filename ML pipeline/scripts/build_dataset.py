"""Build the DayCover modelling dataset from the raw public data (no synthetic data in this file).

    python scripts/build_dataset.py                      # reads data/raw/full, writes data/processed
    python scripts/build_dataset.py --raw <dir> --out <dir>

Stages (each writes one file; see docs/DATA_CARD.md for every decision):
  station_daily.csv.gz   D1 weather.gov.sg daily records, tidy (station, date, rain, max30/60/120, temps, wind)
  stations.csv           D2 gauge coordinates + yearly data completeness
  psi_daily.csv          D4 daily max of hourly 24-hr PSI per region (all 24 h, SGT calendar day)
  centres.csv            D7 operating hawker centres (2026 snapshot) with cooked-food stall counts
  centre_gauge_map.csv   per policy year: nearest and 2nd-nearest gauge, frozen on 1 Jan using only
                         gauges with >=90% valid days in the previous year (no look-ahead)
  centre_region_map.csv  PSI region per centre (nearest NEA region reference point)
  centre_wbgt_map.csv    nearest WBGT station per centre (stations reporting in Jan 2026)
  centre_day.csv.gz      one row per centre and day: assigned-gauge rain (2nd gauge if the 1st is
                         missing), wettest hour, region PSI, cleaning-closure flag
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REGIONS = {  # reference points used by NEA's regional PSI map (same as the team notebook); approximation
    "north": (1.41803, 103.82), "south": (1.29587, 103.82), "east": (1.35735, 103.94),
    "west": (1.35735, 103.70), "central": (1.35735, 103.82)}
OPERATING = ("Existing", "Existing (new)", "Existing (replacement)", "Interim Centre")
MIN_VALID_SHARE = 0.90       # a gauge is eligible for a policy year if it had >=90% valid days the year before
MAX_GAUGE_KM = 5.0           # beyond this a gauge is not treated as representative


def km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (np.sin((lat2 - lat1) * p / 2) ** 2 +
         np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin((lon2 - lon1) * p / 2) ** 2)
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def station_daily(raw: Path) -> pd.DataFrame:
    cols = {"Daily Rainfall Total": "rain", "Highest 30 Min": "max30", "Highest 60 Min": "max60",
            "Highest 120 Min": "max120", "Mean Temperature": "tmean", "Maximum Temperature": "tmax",
            "Minimum Temperature": "tmin", "Mean Wind Speed": "wmean", "Max Wind Speed": "wmax"}
    frames = []
    for p in glob.glob(str(raw / "daily" / "S*_*.csv")):
        df = pd.read_csv(p, encoding="utf-8-sig", encoding_errors="replace")
        df.columns = [c.strip().lstrip("﻿") for c in df.columns]
        out = pd.DataFrame({"station": os.path.basename(p).split("_")[0], "station_name": df.iloc[:, 0],
                            "date": pd.to_datetime(dict(year=df.Year, month=df.Month, day=df.Day), errors="coerce")})
        for k, v in cols.items():
            c = next((c for c in df.columns if c.lower().startswith(k.lower())), None)   # MSS changed "Min" -> "min" in 2020
            out[v] = pd.to_numeric(df[c], errors="coerce") if c else np.nan   # "—" (no reading) -> NaN
        frames.append(out)
    d = pd.concat(frames, ignore_index=True).dropna(subset=["date"])
    # QC: a wettest-30/60/120-min value cannot exceed the day's total; such rows (20 found) are set to missing
    bad = (d.max60 > d.rain + 0.5) | (d.max30 > d.rain + 0.5) | (d.max120 > d.rain + 0.5)
    d.loc[bad, ["max30", "max60", "max120"]] = np.nan
    d["qc_flag"] = np.where(bad, "subdaily_gt_total", "")
    return d.sort_values(["station", "date"]).drop_duplicates(["station", "date"]).reset_index(drop=True)


def stations(raw: Path, daily: pd.DataFrame) -> pd.DataFrame:
    api = pd.read_csv(raw / "stations" / "rain_stations.csv")
    legacy = pd.read_csv(ROOT / "data" / "raw" / "rainfall_stations.csv").rename(columns={"id": "id"})
    coords = pd.concat([api[["id", "name", "latitude", "longitude"]].assign(coord_source="data.gov.sg API 2016-2026"),
                        legacy[["id", "name", "latitude", "longitude"]].assign(coord_source="repo rainfall_stations.csv")])
    coords = coords.drop_duplicates("id").rename(columns={"id": "station"})
    daily = daily.assign(year=daily.date.dt.year)
    days_in_year = daily.groupby("year").date.nunique()
    valid = daily.dropna(subset=["rain"]).groupby(["station", "year"]).size().unstack(fill_value=0)
    share = valid.div(days_in_year, axis=1).round(3)
    share.columns = [f"valid_{y}" for y in share.columns]
    s = coords.merge(share, left_on="station", right_index=True, how="right")
    s["has_coords"] = s.latitude.notna()
    return s.reset_index(drop=True)


def psi_daily(raw: Path) -> pd.DataFrame:
    h = pd.read_csv(raw / "datasets" / "psi_hist.csv")
    h["ts"] = pd.to_datetime(h["24hr_psi"], format="%d/%m/%Y %H:%M", errors="coerce")
    reg = list(REGIONS)
    h[reg] = h[reg].apply(pd.to_numeric, errors="coerce")
    h["date"] = h.ts.dt.normalize()
    p = h.groupby("date")[reg].max().reset_index()
    tail = ROOT / "data" / "raw" / "psi_daily_max_oct_nov_2026_api.csv"     # real-time API, Oct-Nov 2026
    if tail.exists():
        o = pd.read_csv(tail, parse_dates=["date"])[["date"] + reg]
        p = pd.concat([p[p.date < o.date.min()], o])
    return p.sort_values("date").reset_index(drop=True)


def centres(raw: Path) -> pd.DataFrame:
    g = json.load(open(raw / "datasets" / "hawker_centres.geojson", encoding="utf-8"))
    rows = []
    for f in g["features"]:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        rows.append({"centre": p["NAME"].strip(), "status": p.get("STATUS"), "hup": p.get("DESCRIPTION"),
                     "postal": str(p.get("ADDRESSPOSTALCODE") or ""), "lat": lat, "lon": lon,
                     "stalls": pd.to_numeric(p.get("NUMBER_OF_COOKED_FOOD_STALLS"), errors="coerce")})
    c = pd.DataFrame(rows)
    c = c[c.status.isin(OPERATING) & (c.stalls > 0)].copy()
    c.insert(0, "centre_id", [f"HC{i:03d}" for i in range(1, len(c) + 1)])
    return c.reset_index(drop=True)


def gauge_map(c: pd.DataFrame, s: pd.DataFrame, years) -> pd.DataFrame:
    out = []
    for y in years:
        col = f"valid_{y - 1}"
        elig = s[s.has_coords & (s.get(col, 0) >= MIN_VALID_SHARE)] if col in s else s.iloc[0:0]
        for _, r in c.iterrows():
            d = km(r.lat, r.lon, elig.latitude.values, elig.longitude.values)
            o = np.argsort(d)[:2]
            rec = {"centre_id": r.centre_id, "policy_year": y, "eligible_gauges": len(elig)}
            for k, i in enumerate(o, 1):
                rec[f"gauge{k}"] = elig.station.values[i]
                rec[f"gauge{k}_km"] = round(float(d[i]), 3)
            out.append(rec)
    m = pd.DataFrame(out)
    m["gauge1_within_limit"] = m.gauge1_km <= MAX_GAUGE_KM
    return m


def region_map(c: pd.DataFrame) -> pd.DataFrame:
    names, pts = list(REGIONS), np.array(list(REGIONS.values()))
    d = np.stack([km(c.lat.values, c.lon.values, la, lo) for la, lo in pts], axis=1)
    return pd.DataFrame({"centre_id": c.centre_id, "psi_region": [names[i] for i in d.argmin(1)],
                         "region_ref_km": d.min(1).round(2)})


def wbgt_map(raw: Path, c: pd.DataFrame) -> pd.DataFrame | None:
    files = sorted(glob.glob(str(raw / "wbgt" / "2026-01-*.csv"))) or sorted(glob.glob(str(raw / "wbgt" / "*.csv")))[-31:]
    if not files:
        return None
    w = pd.concat(pd.read_csv(f) for f in files)
    st = w.groupby("station_id")[["lat", "lon", "station_name"]].first().reset_index()
    d = np.stack([km(c.lat.values, c.lon.values, la, lo) for la, lo in zip(st.lat, st.lon)], axis=1)
    return pd.DataFrame({"centre_id": c.centre_id, "wbgt_station": st.station_id.values[d.argmin(1)],
                         "wbgt_km": d.min(1).round(2), "wbgt_stations_used": len(st),
                         "wbgt_reference_month": os.path.basename(files[0])[:7]})


def pub_map(raw: Path, c: pd.DataFrame) -> pd.DataFrame | None:
    """Distance from each centre to the nearest PUB hotspot (Feb 2026) and flood-prone area (Nov 2025).
    A rating flag only; the lists are current, not historical."""
    f = raw / "pub" / "pub_locations_geocoded.csv"
    if not f.exists():
        return None
    g = pd.read_csv(f).dropna(subset=["lat", "lon"])
    out = {"centre_id": c.centre_id}
    for lst in ("hotspot", "flood_prone"):
        q = g[g["list"] == lst]
        d = np.stack([km(c.lat.values, c.lon.values, la, lo) for la, lo in zip(q.lat, q.lon)], axis=1)
        out[f"nearest_{lst}_km"] = d.min(1).round(3)
        out[f"nearest_{lst}"] = q.location.values[d.argmin(1)]
        out[f"{lst}_within_1km"] = (d <= 1.0).sum(1)
    m = pd.DataFrame(out)
    near = np.minimum(m.nearest_hotspot_km, m.nearest_flood_prone_km)
    m["pub_flag"] = np.select([near <= 0.5, near <= 1.0], ["within_500m", "within_1km"], "none")
    return m


def wbgt_daily(raw: Path, c: pd.DataFrame, wm: pd.DataFrame) -> pd.DataFrame | None:
    """Per centre and day: max WBGT and hours at 'High' (>=33 C) between 11:00 and 17:00 at the mapped station."""
    files = sorted(glob.glob(str(raw / "wbgt" / "*.csv")))
    if not files or wm is None:
        return None
    w = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
    w["ts"] = pd.to_datetime(w.datetime, utc=True).dt.tz_convert("Asia/Singapore").dt.tz_localize(None)
    w["value"] = pd.to_numeric(w.value, errors="coerce")
    w = w[(w.ts.dt.hour >= 11) & (w.ts.dt.hour < 17)]
    w["date"] = w.ts.dt.normalize()
    st = w.groupby(["station_id", "date"]).agg(wbgt_max=("value", "max"),
                                               wbgt_high_hours=("value", lambda v: (v >= 33).sum() / 4)).reset_index()
    return wm[["centre_id", "wbgt_station"]].merge(st, left_on="wbgt_station", right_on="station_id").drop(columns="station_id")


def closures(c: pd.DataFrame) -> pd.DataFrame:
    """NEA 2026 cleaning/works closures, matched to centres by nearest coordinates (<=150 m)."""
    k = pd.read_csv(ROOT / "data" / "raw" / "hawker_closures.csv")
    rows = []
    for _, r in k.iterrows():
        d = km(r.latitude_hc, r.longitude_hc, c.lat.values, c.lon.values)
        if d.min() > 0.15:
            continue
        cid = c.centre_id.values[d.argmin()]
        for q in ("q1", "q2", "q3", "q4"):
            a, b = r.get(f"{q}_cleaningstartdate"), r.get(f"{q}_cleaningenddate")
            if isinstance(a, str) and "/" in a and isinstance(b, str) and "/" in b:
                for day in pd.date_range(pd.to_datetime(a, dayfirst=True), pd.to_datetime(b, dayfirst=True)):
                    rows.append({"centre_id": cid, "date": day, "closure": "cleaning"})
        a, b = r.get("other_works_startdate"), r.get("other_works_enddate")
        if isinstance(a, str) and "/" in a and isinstance(b, str) and "/" in b:
            for day in pd.date_range(pd.to_datetime(a, dayfirst=True), pd.to_datetime(b, dayfirst=True)):
                rows.append({"centre_id": cid, "date": day, "closure": "works"})
    return pd.DataFrame(rows).drop_duplicates(["centre_id", "date"])


def centre_day(c, gm, rm, daily, psi, clos) -> pd.DataFrame:
    rain = daily.set_index(["station", "date"])[["rain", "max60"]]
    out = []
    for y, g in gm.groupby("policy_year"):
        dates = pd.date_range(f"{y}-01-01", min(pd.Timestamp(f"{y}-12-31"), daily.date.max()))
        for _, r in g.iterrows():
            idx1 = pd.MultiIndex.from_product([[r.gauge1], dates])
            idx2 = pd.MultiIndex.from_product([[r.gauge2], dates])
            a = rain.reindex(idx1).to_numpy()
            b = rain.reindex(idx2).to_numpy()
            use2 = np.isnan(a[:, 0]) & ~np.isnan(b[:, 0])
            out.append(pd.DataFrame({
                "centre_id": r.centre_id, "date": dates,
                "rain": np.where(use2, b[:, 0], a[:, 0]), "max60": np.where(use2, b[:, 1], a[:, 1]),
                "rain_source": np.where(use2, "gauge2", np.where(np.isnan(a[:, 0]), "missing", "gauge1"))}))
    cd = pd.concat(out, ignore_index=True).merge(rm[["centre_id", "psi_region"]], on="centre_id")
    p = psi.melt(id_vars="date", var_name="psi_region", value_name="psi")
    cd = cd.merge(p, on=["date", "psi_region"], how="left")
    if len(clos):
        cd = cd.merge(clos, on=["centre_id", "date"], how="left")
    return cd


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(ROOT / "data" / "raw" / "full"))
    ap.add_argument("--out", default=str(ROOT / "data" / "processed"))
    ap.add_argument("--first-year", type=int, default=2010)
    ap.add_argument("--last-year", type=int, default=2026)
    a = ap.parse_args(argv)
    raw, out = Path(a.raw), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    daily = station_daily(raw); daily.to_csv(out / "station_daily.csv.gz", index=False)
    s = stations(raw, daily); s.to_csv(out / "stations.csv", index=False)
    psi = psi_daily(raw); psi.to_csv(out / "psi_daily.csv", index=False)
    c = centres(raw); c.to_csv(out / "centres.csv", index=False)
    gm = gauge_map(c, s, range(a.first_year, a.last_year + 1)); gm.to_csv(out / "centre_gauge_map.csv", index=False)
    rm = region_map(c); rm.to_csv(out / "centre_region_map.csv", index=False)
    wm = wbgt_map(raw, c)
    if wm is not None:
        wm.to_csv(out / "centre_wbgt_map.csv", index=False)
    pm = pub_map(raw, c)
    if pm is not None:
        pm.to_csv(out / "centre_pub_map.csv", index=False)
        print("PUB flag:", pm.pub_flag.value_counts().to_dict())
    wd = wbgt_daily(raw, c, wm)
    if wd is not None:
        wd.to_csv(out / "centre_wbgt_daily.csv.gz", index=False)
    cl = closures(c); cl.to_csv(out / "closures_2026.csv", index=False)
    cd = centre_day(c, gm, rm, daily, psi, cl); cd.to_csv(out / "centre_day.csv.gz", index=False)

    print(f"stations: {len(s)} ({s.has_coords.sum()} with coordinates)")
    print(f"centres: {len(c)} operating, {int(c.stalls.sum())} cooked-food stalls")
    print("gauge distance by policy year (km): mean / max / share >5 km")
    print(gm.groupby("policy_year").agg(mean_km=("gauge1_km", "mean"), max_km=("gauge1_km", "max"),
                                        over_limit=("gauge1_within_limit", lambda x: 1 - x.mean()),
                                        gauges=("eligible_gauges", "first")).round(2).to_string())
    print("rain source share:", cd.rain_source.value_counts(normalize=True).round(4).to_dict())
    print("centre-days:", len(cd), "| closures 2026 matched centres:", cl.centre_id.nunique() if len(cl) else 0)


if __name__ == "__main__":
    main()
