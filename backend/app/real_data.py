import httpx
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any
import time

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
COOLR = "https://gis.earthdata.nasa.gov/gis05/rest/services/Landslides/COOLR_Events_Points/FeatureServer/0/query"
GLC_CSV = "https://data.nasa.gov/docs/legacy/Global_Landslide_Catalog_Export/Global_Landslide_Catalog_Export_rows.csv"
_COOLR_RETRY_AFTER = 0.0
_GLC_DF = None
_OSM_CACHE = {}

async def fetch_open_meteo(lat: float, lon: float) -> dict[str, Any]:
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "precipitation,rain,soil_moisture_0_to_7cm,soil_moisture_7_to_28cm,temperature_2m",
        "forecast_days": 4, "past_days": 3,
        "timezone": "UTC"
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(OPEN_METEO, params=params)
        r.raise_for_status()
        d = r.json()
    times = d.get("hourly", {}).get("time", [])
    rain = d.get("hourly", {}).get("rain", d.get("hourly", {}).get("precipitation", []))
    precip = d.get("hourly", {}).get("precipitation", rain)
    soil0 = d.get("hourly", {}).get("soil_moisture_0_to_7cm", [])
    soil1 = d.get("hourly", {}).get("soil_moisture_7_to_28cm", [])
    temp = d.get("hourly", {}).get("temperature_2m", [])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
                                                                           
    idx = 0
    for i, t in enumerate(times):
        try:
            ts = datetime.fromisoformat(str(t).replace("Z", ""))
            if ts <= now:
                idx = i
            else:
                break
        except Exception:
            pass
    last24 = [float(x or 0) for x in precip[max(0, idx-23):idx+1]]
    last72 = [float(x or 0) for x in precip[max(0, idx-71):idx+1]]
    a = float(soil0[idx] if idx < len(soil0) and soil0[idx] is not None else 0.0)
    b = float(soil1[idx] if idx < len(soil1) and soil1[idx] is not None else a)
                                                                                               
    soil_pct = max(0.0, min(100.0, ((a + b) / 2.0) * 100.0))
    forecast_precip = [float(x or 0) for x in precip[idx+1:idx+25]]
    return {
        "source": "Open-Meteo / ECMWF and other national weather models",
        "latitude": d.get("latitude", lat), "longitude": d.get("longitude", lon),
        "elevation_m": d.get("elevation"),
        "rainfall_24h_mm": round(sum(last24), 1),
        "rainfall_72h_mm": round(sum(last72), 1),
        "forecast_next_24h_mm": round(sum(forecast_precip), 1),
        "soil_moisture_pct": round(soil_pct, 1),
        "temperature_c": round(float(temp[idx]), 1) if idx < len(temp) and temp[idx] is not None else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "LIVE"
    }

async def fetch_coolr_count(lat: float, lon: float, radius_deg: float = 1.0) -> dict[str, Any]:
    """Return nearby real landslide events. COOLR is primary; NASA GLC CSV is fallback."""
    global _COOLR_RETRY_AFTER, _GLC_DF
    geometry = {"xmin": lon-radius_deg, "ymin": lat-radius_deg, "xmax": lon+radius_deg, "ymax": lat+radius_deg,
                "spatialReference": {"wkid": 4326}}
    params = {"where": "1=1", "geometry": __import__("json").dumps(geometry),
              "geometryType": "esriGeometryEnvelope", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "returnGeometry": "true",
              "f": "json", "resultRecordCount": 2000}
    coolr_error = None
    if time.time() >= _COOLR_RETRY_AFTER:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(COOLR, params=params)
                r.raise_for_status()
                data = r.json()
            if "error" in data:
                raise RuntimeError(str(data["error"]))
            features = data.get("features", [])
            _COOLR_RETRY_AFTER = 0.0
            return {"count": len(features), "source": "NASA COOLR", "mode": "LIVE",
                    "events": [{"lat": f.get("geometry", {}).get("y"),
                                "lng": f.get("geometry", {}).get("x"),
                                "attributes": f.get("attributes", {})} for f in features[:100]]}
        except Exception as exc:
            coolr_error = exc
            _COOLR_RETRY_AFTER = time.time() + 600
    else:
        coolr_error = RuntimeError("NASA COOLR temporarily bypassed after a previous unavailable response")

                                                                                     
    cache = Path(__file__).resolve().parent.parent / "data" / "cache" / "glc.csv"
    try:
        if _GLC_DF is None:
            if not cache.exists():
                async with httpx.AsyncClient(timeout=120, follow_redirects=True,
                    headers={"User-Agent": "SIH26001-Landslide-Monitor/1.0 (educational project)"}) as client:
                    r = await client.get(GLC_CSV)
                    r.raise_for_status()
                    cache.write_bytes(r.content)
            _GLC_DF = pd.read_csv(cache, low_memory=False)
        df = _GLC_DF
        cols = {str(c).strip().lower(): c for c in df.columns}
        def pick(*names):
            for n in names:
                if n in cols:
                    return cols[n]
            return None
        latc, lonc = pick("latitude", "lat"), pick("longitude", "lon", "lng")
        if not latc or not lonc:
            raise RuntimeError(f"GLC schema missing coordinates: {list(df.columns)}")
        lat_values = pd.to_numeric(df[latc], errors="coerce")
        lon_values = pd.to_numeric(df[lonc], errors="coerce")
        mask = lat_values.between(lat-radius_deg, lat+radius_deg) & lon_values.between(lon-radius_deg, lon+radius_deg)
        sub = df[mask].head(100)
        events = [{"lat": float(row[latc]), "lng": float(row[lonc]), "attributes": row.to_dict()}
                  for _, row in sub.iterrows()]
        return {"count": int(mask.sum()), "source": "NASA Global Landslide Catalog CSV (COOLR fallback)",
                "mode": "FALLBACK", "coolr_error": str(coolr_error), "events": events}
    except Exception as fallback_error:
        raise RuntimeError(f"COOLR unavailable ({coolr_error}); NASA GLC fallback unavailable ({fallback_error})") from fallback_error

async def fetch_osm_layers(locations: list[dict]) -> dict[str, list]:
    if not locations:
        return {"roads": [], "villages": [], "infrastructure": []}
    cache_key = tuple(sorted((x["id"], round(x["lat"], 3), round(x["lng"], 3)) for x in locations))
    cached = _OSM_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < 600:
        return cached[1]
    south = max(-90.0, min(x["lat"] for x in locations) - 0.15)
    north = min(90.0, max(x["lat"] for x in locations) + 0.15)
    west = max(-180.0, min(x["lng"] for x in locations) - 0.15)
    east = min(180.0, max(x["lng"] for x in locations) + 0.15)
    q = f"""[out:json][timeout:30];(way[highway]({south},{west},{north},{east});node[place~'village|town|hamlet']({south},{west},{north},{east});node[amenity~'hospital|school|fire_station']({south},{west},{north},{east});node[power='substation']({south},{west},{north},{east}););out center tags;"""
    headers = {"User-Agent": "SIH26001-Landslide-Monitor/1.0 (educational project)", "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    last_error = None
    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers=headers) as client:
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                r = await client.post(endpoint, content=q.encode("utf-8"))
                r.raise_for_status()
                data = r.json()
                break
            except Exception as exc:
                last_error = exc
        else:
            raise RuntimeError(f"All OpenStreetMap Overpass endpoints failed: {last_error}") from last_error
    roads, villages, infra = [], [], []
    for e in data.get("elements", []):
        tags=e.get("tags", {})
        if e.get("type")=="way":
            c=e.get("center", {})
            if "lat" in c and "lon" in c:
                roads.append({"id":f"OSM-R-{e['id']}","name":tags.get("name", tags.get("ref","Unnamed road")),"type":tags.get("highway","road"),"status":"MONITORED","lat":c["lat"],"lng":c["lon"],"source":"OpenStreetMap"})
        elif tags.get("place") in {"village","town","hamlet"}:
            villages.append({"id":f"OSM-V-{e['id']}","name":tags.get("name","Unnamed settlement"),"district":tags.get("addr:district",""),"lat":e.get("lat"),"lng":e.get("lon"),"population":tags.get("population"),"risk":"MONITORED","source":"OpenStreetMap"})
        elif tags.get("amenity") in {"hospital","school","fire_station"} or tags.get("power")=="substation":
            infra.append({"id":f"OSM-I-{e['id']}","name":tags.get("name", tags.get("amenity", tags.get("power","facility"))),"type":tags.get("amenity",tags.get("power","facility")),"lat":e.get("lat"),"lng":e.get("lon"),"priority":"MONITORED","source":"OpenStreetMap"})
    result = {"roads":roads[:250],"villages":villages[:250],"infrastructure":infra[:250]}
    _OSM_CACHE[cache_key] = (time.time(), result)
    return result
