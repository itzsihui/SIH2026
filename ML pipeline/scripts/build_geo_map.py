"""Generate the standalone interactive Leaflet GEO Map for DayCover+ hawker centres, rainfall stations, and PUB flood-prone overlays.

Usage:
    python scripts/build_geo_map.py
Output:
    demo/map.html
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HC_MAP_CSV = ROOT / "results" / "rain_hawker_station_map.csv"
CLOSURES_CSV = ROOT / "data" / "raw" / "hawker_closures.csv"
OUT_HTML = ROOT / "demo" / "map.html"

# Official PUB Flood-Prone Areas and Flash Flood Hotspots
PUB_FLOOD_ZONES = [
    {"name": "Jalan Besar Area", "lat": 1.3090, "lon": 103.8560, "type": "Flood-Prone Area", "desc": "Low-lying basin near Rochor Canal"},
    {"name": "Farrer Park (Derbyshire / Cambridge Rd)", "lat": 1.3165, "lon": 103.8505, "type": "Flood-Prone Area", "desc": "Historical flood basin"},
    {"name": "Commonwealth Ave / Commonwealth Dr", "lat": 1.2995, "lon": 103.8015, "type": "Flood-Prone Area", "desc": "Drainage junction"},
    {"name": "Dunearn Rd (Binjai Park to Hillcrest)", "lat": 1.3320, "lon": 103.7980, "type": "Flash Flood Hotspot", "desc": "Bukit Timah Canal corridor"},
    {"name": "Bukit Timah Rd (Wilby Rd to Blackmore)", "lat": 1.3280, "lon": 103.8040, "type": "Flash Flood Hotspot", "desc": "Low-lying arterial road"},
    {"name": "Bedok South Rd / Siglap Canal", "lat": 1.3200, "lon": 103.9350, "type": "Flood-Prone Area", "desc": "Siglap canal catchment"},
    {"name": "Ang Mo Kio Ave 3 / Ave 8 Junction", "lat": 1.3695, "lon": 103.8485, "type": "Flash Flood Hotspot", "desc": "Major traffic intersection"},
    {"name": "Toa Payoh Lor 1 & Lor 2 Junction", "lat": 1.3355, "lon": 103.8480, "type": "Flash Flood Hotspot", "desc": "Central basin road"},
    {"name": "Craig Rd / Tanjong Pagar Rd", "lat": 1.2785, "lon": 103.8430, "type": "Flash Flood Hotspot", "desc": "CBD historic low point"},
    {"name": "Geylang East / Aljunied Ave 2", "lat": 1.3210, "lon": 103.8870, "type": "Flood-Prone Area", "desc": "Geylang river catchment basin"},
    {"name": "Indus Rd / Ganges Ave", "lat": 1.2890, "lon": 103.8290, "type": "Flood-Prone Area", "desc": "Havelock low area"},
    {"name": "Alexandra Rd / Lower Delta Rd", "lat": 1.2850, "lon": 103.8240, "type": "Flood-Prone Area", "desc": "Canal confluence"},
    {"name": "Lorong Buangkok Area", "lat": 1.3830, "lon": 103.8790, "type": "Flood-Prone Area", "desc": "Sungei Punggol low basin"},
    {"name": "Upper Changi Rd / Tanah Merah Kechil", "lat": 1.3270, "lon": 103.9450, "type": "Flood-Prone Area", "desc": "Changi drainage corridor"}
]

def get_region(lat: float, lon: float) -> str:
    if lat < 1.285 and lon < 103.86:
        return "South"
    elif lon < 103.75:
        return "West"
    elif lon > 103.87:
        return "East"
    elif lat > 1.36:
        return "North"
    else:
        return "Central"

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def build_map():
    map_df = pd.read_csv(HC_MAP_CSV)
    closures_df = pd.read_csv(CLOSURES_CSV)
    closures_map = dict(zip(closures_df["name"], closures_df.get("no_of_market_stalls", [0]*len(closures_df))))

    hawker_data = []
    stations_data = {}

    for _, r in map_df.iterrows():
        h_lat, h_lon = float(r["hawker_lat"]), float(r["hawker_lon"])
        s_lat, s_lon = float(r["station_lat"]), float(r["station_lon"])
        s_id = str(r["station_id"])
        
        # Check nearest flood zone
        nearest_flood = None
        min_flood_dist = float("inf")
        for fz in PUB_FLOOD_ZONES:
            fd = haversine(h_lat, h_lon, fz["lat"], fz["lon"])
            if fd < min_flood_dist:
                min_flood_dist = fd
                nearest_flood = fz

        flood_risk = "High (< 0.8 km)" if min_flood_dist <= 0.8 else ("Moderate (< 1.5 km)" if min_flood_dist <= 1.5 else "Low")
        region = get_region(h_lat, h_lon)

        hawker_data.append({
            "name": r["hawker_name"],
            "lat": h_lat,
            "lon": h_lon,
            "food_stalls": int(r.get("food_stalls", 0)),
            "market_stalls": int(closures_map.get(r["hawker_name"], 0)),
            "region": region,
            "station_id": s_id,
            "station_name": r["station_name"],
            "station_lat": s_lat,
            "station_lon": s_lon,
            "station_dist_km": float(r["distance_km"]),
            "flood_risk": flood_risk,
            "nearest_flood_zone": nearest_flood["name"],
            "flood_dist_km": round(min_flood_dist, 2)
        })

        if s_id not in stations_data:
            stations_data[s_id] = {
                "id": s_id,
                "name": r["station_name"],
                "lat": s_lat,
                "lon": s_lon,
                "connected_hawkers": 1
            }
        else:
            stations_data[s_id]["connected_hawkers"] += 1

    stations_list = list(stations_data.values())

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>DayCover+ Geospatial Intelligence | Hawker Centres & Weather Telemetry Map</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
    body {{ display: flex; flex-direction: column; height: 100vh; background: #0f172a; color: #f8fafc; }}
    header {{ background: #0b1e36; padding: 0.8rem 1.5rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #ff5a00; z-index: 1000; }}
    .brand {{ display: flex; align-items: center; gap: 0.75rem; }}
    .badge {{ background: #ff5a00; color: #fff; font-size: 0.7rem; font-weight: 700; padding: 0.2rem 0.5rem; border-radius: 4px; }}
    .header-links a {{ color: #cbd5e1; text-decoration: none; font-size: 0.85rem; font-weight: 600; margin-left: 1rem; transition: 0.2s; }}
    .header-links a:hover {{ color: #ff5a00; }}
    #map-container {{ flex: 1; position: relative; }}
    #map {{ width: 100%; height: 100%; }}
    
    .panel {{ position: absolute; top: 1rem; left: 1rem; z-index: 1000; background: rgba(15, 23, 42, 0.92); backdrop-filter: blur(8px); border: 1px solid #334155; border-radius: 8px; padding: 1rem; max-width: 320px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
    .panel h2 {{ font-size: 1rem; color: #ff5a00; margin-bottom: 0.5rem; }}
    .panel p {{ font-size: 0.75rem; color: #94a3b8; line-height: 1.4; margin-bottom: 0.75rem; }}
    .kpi-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; margin-bottom: 0.75rem; }}
    .kpi {{ background: #1e293b; padding: 0.4rem 0.6rem; border-radius: 4px; border: 1px solid #334155; }}
    .kpi-num {{ font-size: 1.1rem; font-weight: 800; color: #f8fafc; }}
    .kpi-lbl {{ font-size: 0.65rem; color: #64748b; text-transform: uppercase; font-weight: 700; }}
    
    .search-input {{ width: 100%; padding: 0.45rem 0.75rem; background: #1e293b; border: 1px solid #475569; border-radius: 4px; color: #fff; font-size: 0.8rem; outline: none; margin-bottom: 0.5rem; }}
    .search-input:focus {{ border-color: #ff5a00; }}

    .legend {{ position: absolute; bottom: 1.5rem; right: 1rem; z-index: 1000; background: rgba(15, 23, 42, 0.92); border: 1px solid #334155; border-radius: 8px; padding: 0.75rem 1rem; font-size: 0.75rem; }}
    .legend-item {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.35rem; }}
    .legend-dot {{ width: 12px; height: 12px; border-radius: 50%; display: inline-block; }}
    
    .leaflet-popup-content-wrapper {{ background: #0f172a; color: #f8fafc; border: 1px solid #334155; border-radius: 8px; }}
    .leaflet-popup-tip {{ background: #0f172a; }}
    .popup-card h4 {{ color: #ff5a00; font-size: 0.95rem; margin-bottom: 0.3rem; border-bottom: 1px solid #334155; padding-bottom: 0.3rem; }}
    .popup-row {{ display: flex; justify-content: space-between; font-size: 0.75rem; margin: 0.25rem 0; }}
    .popup-row span {{ color: #94a3b8; }}
    .popup-row strong {{ color: #f8fafc; }}

    /* Dark Mode styling for Leaflet Zoom & Layer Controls */
    .leaflet-bar {{ border: 1px solid #334155 !important; border-radius: 6px !important; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.5) !important; }}
    .leaflet-bar a {{ background-color: rgba(15, 23, 42, 0.94) !important; color: #f8fafc !important; border-bottom: 1px solid #334155 !important; }}
    .leaflet-bar a:hover {{ background-color: #1e293b !important; color: #ff5a00 !important; }}
    .leaflet-control-layers {{ background: rgba(15, 23, 42, 0.94) !important; color: #f8fafc !important; border: 1px solid #334155 !important; border-radius: 8px !important; box-shadow: 0 4px 20px rgba(0,0,0,0.5) !important; font-size: 0.75rem !important; padding: 0.5rem 0.75rem !important; }}
    .leaflet-control-layers-expanded {{ background: rgba(15, 23, 42, 0.94) !important; }}
    .leaflet-control-layers-toggle {{ filter: invert(0.9) hue-rotate(180deg); }}
    .leaflet-control-layers label {{ margin-bottom: 0.25rem !important; cursor: pointer; color: #cbd5e1; }}
    .leaflet-control-layers-separator {{ border-top: 1px solid #334155 !important; margin: 0.4rem 0 !important; }}
  </style>
</head>
<body>

  <header>
    <div class="brand">
      <div class="badge">Income DayCover+</div>
      <h1 style="font-size:1.1rem; font-weight:700;">Hawker Geo-Intelligence & Telemetry Map</h1>
    </div>
    <div class="header-links">
      <a href="index.html">&larr; Back to Demo Board</a>
    </div>
  </header>

  <div id="map-container">
    <div id="map"></div>

    <div class="panel">
      <h2>Singapore Hawker Shield</h2>
      <p>Hyper-local parametric mapping of 123 government hawker centres to 39 NEA rain gauges and PUB flood-prone zones.</p>
      
      <div class="kpi-row">
        <div class="kpi">
          <div class="kpi-num">123</div>
          <div class="kpi-lbl">Hawker Centres</div>
        </div>
        <div class="kpi">
          <div class="kpi-num">1.10 km</div>
          <div class="kpi-lbl">Avg Gauge Dist</div>
        </div>
        <div class="kpi">
          <div class="kpi-num">6,681</div>
          <div class="kpi-lbl">Covered Stalls</div>
        </div>
        <div class="kpi">
          <div class="kpi-num">14</div>
          <div class="kpi-lbl">PUB Flood Zones</div>
        </div>
      </div>

      <input type="text" id="hawker-search" class="search-input" placeholder="Search centre (e.g. Adam, Amoy, Maxwell)..." oninput="filterHawkers(this.value)">
      <div id="search-results" style="max-height:120px; overflow-y:auto; font-size:0.75rem;"></div>
    </div>

    <div class="legend">
      <div style="font-weight:700; color:#ff5a00; margin-bottom:0.4rem;">Map Layers</div>
      <div class="legend-item"><span class="legend-dot" style="background:#ff5a00;"></span> Hawker Centre (123)</div>
      <div class="legend-item"><span class="legend-dot" style="background:#3b82f6;"></span> NEA Rain Station (39)</div>
      <div class="legend-item"><span class="legend-dot" style="background:#ef4444; border:1px solid #fff;"></span> PUB Flood-Prone Zone (14)</div>
      <div class="legend-item"><span style="display:inline-block; width:14px; height:2px; background:#64748b;"></span> Station Nearest Link</div>
    </div>
  </div>

  <script>
    const HAWKERS = {json.dumps(hawker_data)};
    const STATIONS = {json.dumps(stations_list)};
    const FLOOD_ZONES = {json.dumps(PUB_FLOOD_ZONES)};

    // Initialize Map
    const map = L.map('map', {{
      center: [1.3521, 103.8198],
      zoom: 12,
      minZoom: 11,
      maxZoom: 18,
      zoomControl: false
    }});

    // Reposition zoom buttons so they don't get covered by the top-left KPI panel
    L.control.zoom({{ position: 'bottomleft' }}).addTo(map);

    const hawkerLayer = L.layerGroup().addTo(map);
    const stationLayer = L.layerGroup().addTo(map);
    const floodLayer = L.layerGroup().addTo(map);
    const linkLayer = L.layerGroup().addTo(map);

    // Keyless, Block-Free Tile Layers (Esri ArcGIS Global CDN - Zero 403 Blocks, Zero Watermarks)
    const esriCanvas = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
      attribution: 'Tiles &copy; Esri &bull; Singapore Sovereign Open Data (NEA / PUB)',
      maxNativeZoom: 16,
      maxZoom: 19
    }});

    const esriStreet = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
      attribution: 'Tiles &copy; Esri, DeLorme, NAVTEQ &bull; Singapore Sovereign Open Data (NEA / PUB)',
      maxNativeZoom: 18,
      maxZoom: 19
    }});

    const esriSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
      attribution: 'Tiles &copy; Esri, Earthstar Geographics &bull; Singapore Sovereign Open Data (NEA / PUB)',
      maxNativeZoom: 18,
      maxZoom: 19
    }});

    // Default to Esri Light Gray Canvas (matches original clean UI, zero 403 blocks)
    esriCanvas.addTo(map);

    const baseMaps = {{
      "Light Gray Canvas": esriCanvas,
      "Detailed Street Map": esriStreet,
      "Satellite Imagery": esriSat
    }};

    const overlayMaps = {{
      "Hawker Centres (123)": hawkerLayer,
      "NEA Rain Gauges (39)": stationLayer,
      "PUB Flood Zones (14)": floodLayer,
      "Nearest Gauge Links": linkLayer
    }};

    L.control.layers(baseMaps, overlayMaps, {{ position: 'topright', collapsed: true }}).addTo(map);

    // Render PUB Flood Zones
    FLOOD_ZONES.forEach(fz => {{
      const circle = L.circle([fz.lat, fz.lon], {{
        color: '#ef4444',
        fillColor: '#ef4444',
        fillOpacity: 0.25,
        radius: 650,
        weight: 2,
        dashArray: '4, 4'
      }}).addTo(floodLayer);

      circle.bindPopup(`
        <div class="popup-card">
          <h4>🚨 PUB ${{fz.type}}</h4>
          <div class="popup-row"><span>Location:</span><strong>${{fz.name}}</strong></div>
          <div class="popup-row"><span>Characteristics:</span><strong>${{fz.desc}}</strong></div>
        </div>
      `);
    }});

    // Render Stations
    const stationMarkers = {{}};
    STATIONS.forEach(s => {{
      const icon = L.divIcon({{
        className: 'station-icon',
        html: '<div style="background:#2563eb; width:14px; height:14px; border-radius:3px; border:2px solid #fff; box-shadow:0 0 6px rgba(0,0,0,0.5);"></div>',
        iconSize: [14, 14]
      }});
      const marker = L.marker([s.lat, s.lon], {{ icon }}).addTo(stationLayer);
      marker.bindPopup(`
        <div class="popup-card">
          <h4>🌧️ NEA Telemetry Station</h4>
          <div class="popup-row"><span>Station ID:</span><strong>${{s.id}}</strong></div>
          <div class="popup-row"><span>Station Name:</span><strong>${{s.name}}</strong></div>
          <div class="popup-row"><span>Covered Hawkers:</span><strong>${{s.connected_hawkers}} centres</strong></div>
          <div class="popup-row"><span>Telemetry Interval:</span><strong>5-minute rainfall</strong></div>
        </div>
      `);
      stationMarkers[s.id] = marker;
    }});

    // Render Hawkers & Links
    const hawkerMarkers = [];
    HAWKERS.forEach(h => {{
      const icon = L.divIcon({{
        className: 'hawker-icon',
        html: '<div style="background:#ff5a00; width:14px; height:14px; border-radius:50%; border:2px solid #fff; box-shadow:0 0 8px rgba(255,90,0,0.8);"></div>',
        iconSize: [14, 14]
      }});

      const marker = L.marker([h.lat, h.lon], {{ icon }}).addTo(hawkerLayer);
      marker.bindPopup(`
        <div class="popup-card">
          <h4>🍲 ${{h.name}}</h4>
          <div class="popup-row"><span>Cooked Food Stalls:</span><strong>${{h.food_stalls}} stalls</strong></div>
          <div class="popup-row"><span>PSI Region:</span><strong>${{h.region}}</strong></div>
          <div class="popup-row"><span>Nearest Gauge:</span><strong>${{h.station_name}} (${{h.station_id}})</strong></div>
          <div class="popup-row"><span>Gauge Distance:</span><strong style="color:#ff5a00;">${{h.station_dist_km}} km</strong></div>
          <div class="popup-row"><span>PUB Flood Risk:</span><strong style="color:${{h.flood_risk.startsWith('High') ? '#ef4444' : '#10b981'}}">${{h.flood_risk}}</strong></div>
        </div>
      `);

      // Connection line to nearest station
      L.polyline([[h.lat, h.lon], [h.station_lat, h.station_lon]], {{
        color: '#64748b',
        weight: 1.2,
        opacity: 0.6,
        dashArray: '3, 4'
      }}).addTo(linkLayer);

      hawkerMarkers.push({{ name: h.name.toLowerCase(), marker, lat: h.lat, lon: h.lon }});
    }});

    // Filter & Search
    function filterHawkers(term) {{{{
      const resultsDiv = document.getElementById('search-results');
      resultsDiv.innerHTML = '';
      if (!term.trim()) return;
      
      const q = term.toLowerCase();
      const matches = hawkerMarkers.filter(m => m.name.includes(q)).slice(0, 5);
      matches.forEach(m => {{{{
        const item = document.createElement('div');
        item.style = 'padding: 0.3rem 0.4rem; cursor: pointer; border-bottom: 1px solid #334155; color: #cbd5e1;';
        item.textContent = m.marker.getPopup().getContent().match(/<h4>🍲 (.*?)<\\/h4>/)[1];
        item.onclick = () => {{{{
          map.setView([m.lat, m.lon], 16);
          m.marker.openPopup();
        }}}};
        resultsDiv.appendChild(item);
      }}}});
    }}}}
  </script>
</body>
</html>
"""
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"Built interactive Leaflet GEO Map at: {OUT_HTML}")

if __name__ == "__main__":
    build_map()
