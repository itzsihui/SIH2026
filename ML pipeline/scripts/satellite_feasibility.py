"""Feasibility check: can a gridded precipitation product (here ERA5 reanalysis (0.25 degree, about 28 km) via Open-Meteo, free, no key)
confirm or rescue the NEA-gauge rain trigger? Compares daily mm at each stall's location with the stall's assigned gauge
on the 701 sampled dates. NOTE: ERA5 is reanalysis, not a direct satellite product. Real satellite (GPM IMERG) needs a
free NASA Earthdata login and is the follow-up. Run: python3 -m scripts.satellite_feasibility"""
import json, time, urllib.request, math
from datetime import date
from src.daycover import data

URL = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date=2017-01-01&end_date=2026-11-06"
       "&daily=precipitation_sum&models=era5&timezone=Asia%2FSingapore")

def fetch(lat, lon):
    for i in range(4):
        try:
            return json.load(urllib.request.urlopen(URL.format(lat=lat, lon=lon), timeout=60))["daily"]
        except Exception as e:
            time.sleep(4 * (i + 1))
    return None

stalls = data.load_stalls()
tab = data.rain_daily_table()
dates = sorted(data.rain_dates())
cache = {}
pairs = []   # (gauge_mm, grid_mm)
for s in stalls:
    key = (round(s.lat * 4) / 4, round(s.lon * 4) / 4)   # ERA5 is a 0.25 degree grid
    if key not in cache:
        cache[key] = fetch(*key); time.sleep(0.4)
    d = cache[key]
    if not d: continue
    idx = {t: v for t, v in zip(d["time"], d["precipitation_sum"])}
    for day in dates:
        r = tab.get((day, s.gauge))
        g = idx.get(day.isoformat())
        if r and r["valid"] and g is not None:
            pairs.append((r["mm"], g))

n = len(pairs)
xs = [p[0] for p in pairs]; ys = [p[1] for p in pairs]
mx, my = sum(xs) / n, sum(ys) / n
corr = sum((x - mx) * (y - my) for x, y in pairs) / math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
out = {"product": "ERA5 reanalysis (0.25 degree) via Open-Meteo (not direct satellite)", "pairs": n, "distinct_grid_points": len(cache), "pearson_r_daily_mm": round(corr, 3)}
for thr in (70, 50, 30):
    g_hit = [p for p in pairs if p[0] >= thr]
    out[f"gauge>={thr}mm"] = {"days": len(g_hit), "grid_also_>=_half_threshold": round(sum(1 for p in g_hit if p[1] >= thr / 2) / max(len(g_hit), 1), 3),
                              "grid_>=_threshold": round(sum(1 for p in g_hit if p[1] >= thr) / max(len(g_hit), 1), 3)}
    gr_hit = [p for p in pairs if p[1] >= thr]
    out[f"grid>={thr}mm"] = {"days": len(gr_hit), "gauge_also_>=_threshold": round(sum(1 for p in gr_hit if p[0] >= thr) / max(len(gr_hit), 1), 3)}
out["mean_gauge_mm"] = round(mx, 2); out["mean_grid_mm"] = round(my, 2)
json.dump(out, open("results/satellite_feasibility.json", "w"), indent=1)
print(json.dumps(out, indent=1))
