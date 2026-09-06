from __future__ import annotations
import argparse, json, math, random, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
import requests
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "real_training_dataset.csv"
REPORT = DATA / "real_dataset_report.json"
CACHE = DATA / "cache"
CACHE.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT))
from app.geo_real import fetch_dem_features, fetch_sentinel_ndvi

NASA_QUERY = "https://gis.earthdata.nasa.gov/gis05/rest/services/Landslides/COOLR_Events_Points/FeatureServer/0/query"
NASA_MAP_QUERY = "https://gis.earthdata.nasa.gov/gis05/rest/services/Landslides/COOLR_Events_Points/MapServer/0/query"
GLC_CSV = "https://data.nasa.gov/docs/legacy/Global_Landslide_Catalog_Export/Global_Landslide_Catalog_Export_rows.csv"
NER_BBOX = (21.5, 29.8, 88.0, 97.7)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "SIH26001-SlopeNexis/2.0 educational research"})


def _in_ner(lat, lon):
    return NER_BBOX[0] <= lat <= NER_BBOX[1] and NER_BBOX[2] <= lon <= NER_BBOX[3]


def _parse_date(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        if isinstance(value, (int, float)):
            unit = "ms" if abs(float(value)) > 10_000_000_000 else "s"
            x = pd.to_datetime(value, unit=unit, errors="coerce")
        else:
            x = pd.to_datetime(str(value), errors="coerce")
        if pd.isna(x):
            return None
        return x.date().isoformat()
    except Exception:
        return None


def _normalise_features(features):
    rows = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        a = feature.get("attributes") or {}
        lat = geometry.get("y") or a.get("latitude") or a.get("lat")
        lon = geometry.get("x") or a.get("longitude") or a.get("lon")
        if lat is None or lon is None:
            continue
        try:
            lat, lon = float(lat), float(lon)
        except Exception:
            continue
        if not _in_ner(lat, lon):
            continue
        raw_date = a.get("event_date") or a.get("eventdate") or a.get("date")
        d = _parse_date(raw_date)
        if not d:
            import re
            title = str(a.get("event_title") or a.get("title") or "")
            m = re.search(r"(20\d{2}-\d{2}-\d{2})", title)
            d = m.group(1) if m else None
        if not d:
            continue
        rows.append({
            "lat": lat, "lon": lon, "event_date": d,
            "title": str(a.get("event_title") or a.get("title") or ""),
            "citation": str(a.get("citation") or ""),
        })
    unique, seen = [], set()
    for e in sorted(rows, key=lambda x: x["event_date"]):
        key = (round(e["lat"], 4), round(e["lon"], 4), e["event_date"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def _query_arcgis(url):
    all_features = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "geometry": f"{NER_BBOX[2]},{NER_BBOX[0]},{NER_BBOX[3]},{NER_BBOX[1]}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "true",
            "resultRecordCount": 2000,
            "resultOffset": offset,
            "f": "json",
        }
        r = SESSION.get(url, params=params, timeout=90)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(str(data["error"]))
        features = data.get("features", [])
        all_features.extend(features)
        exceeded = bool(data.get("exceededTransferLimit"))
        if not exceeded or len(features) == 0:
            break
        offset += len(features)
        if offset > 100000:
            break
        time.sleep(0.2)
    return _normalise_features(all_features)


def _download_glc_csv():
    print("NASA COOLR unavailable; using NASA Global Landslide Catalog CSV fallback...")
    r = SESSION.get(GLC_CSV, timeout=180)
    r.raise_for_status()
    df = pd.read_csv(BytesIO(r.content), low_memory=False)
    cols = {str(c).strip().lower(): c for c in df.columns}

    def col(*names):
        for n in names:
            if n in cols:
                return cols[n]
        for k, original in cols.items():
            if any(n in k for n in names):
                return original
        return None

    latc, lonc = col("latitude", "lat"), col("longitude", "lon", "lng")
    datec = col("event_date", "eventdate", "date")
    titlec = col("event_title", "title", "location_description")
    citec = col("source_name", "citation", "source")
    if not latc or not lonc or not datec:
        raise RuntimeError(f"NASA GLC CSV schema not recognised. Columns: {list(df.columns)}")
    rows = []
    for _, r0 in df.iterrows():
        try:
            lat, lon = float(r0[latc]), float(r0[lonc])
        except Exception:
            continue
        if not _in_ner(lat, lon):
            continue
        d = _parse_date(r0[datec])
        if not d:
            continue
        rows.append({"lat": lat, "lon": lon, "event_date": d,
                     "title": str(r0[titlec]) if titlec else "",
                     "citation": str(r0[citec]) if citec else "NASA Global Landslide Catalog"})
    return _normalise_features([{"geometry": {"x": x["lon"], "y": x["lat"]}, "attributes": x} for x in rows])


def fetch_events(start_year, end_year):
    raw = []
    for label, url in (("NASA COOLR FeatureServer", NASA_QUERY), ("NASA COOLR MapServer", NASA_MAP_QUERY)):
        try:
            print(f"Trying {label}...")
            raw = _query_arcgis(url)
            if raw:
                print(f"{label} returned {len(raw)} dated NER events")
                break
        except Exception as exc:
            print(f"{label} unavailable: {exc}")
    if not raw:
        raw = _download_glc_csv()
        print(f"NASA GLC fallback returned {len(raw)} dated NER events")
    start = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    events = [e for e in raw if start <= date.fromisoformat(e["event_date"]) <= end]
    print(f"Historical inventory window: {start_year}-{end_year}")
    print(f"Events in NER and window: {len(events)}")
    if not events:
        raise RuntimeError("No dated NER landslide events were found in the requested period.")
    return events


def _request_json(url, params, attempts=4):
    last = None
    for attempt in range(attempts):
        try:
            r = SESSION.get(url, params=params, timeout=60)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(20, 2 ** attempt))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(str(last))


def weather(lat, lon, event_date):
    d = date.fromisoformat(event_date)
    start = d - timedelta(days=30)
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": d.isoformat(),
        "hourly": "precipitation,soil_moisture_0_to_7cm,soil_moisture_7_to_28cm,temperature_2m,relative_humidity_2m",
        "models": "era5_land",
        "timezone": "UTC",
        "cell_selection": "land",
    }
    j = _request_json("https://archive-api.open-meteo.com/v1/archive", params)
    h = j.get("hourly", {})
    rain = h.get("precipitation", [])
    sm0 = h.get("soil_moisture_0_to_7cm", [])
    sm1 = h.get("soil_moisture_7_to_28cm", [])
    temp = h.get("temperature_2m", [])
    rh = h.get("relative_humidity_2m", [])
    if not rain:
        raise ValueError("no historical precipitation")
    r24 = [float(x or 0) for x in rain[-24:]]
    r72 = [float(x or 0) for x in rain[-72:]]
    r7 = [float(x or 0) for x in rain[-168:]]
    r30 = [float(x or 0) for x in rain[-720:]]
    n = min(24, len(sm0), len(sm1))
    soil = 100 * sum(((sm0[-n+i] or 0) + (sm1[-n+i] or 0)) / 2 for i in range(n)) / max(1, n)
    recent_temp = [float(x) for x in temp[-24:] if x is not None]
    recent_rh = [float(x) for x in rh[-24:] if x is not None]
    return {
        "rainfall_24h_mm": round(sum(r24), 3),
        "rainfall_72h_mm": round(sum(r72), 3),
        "rainfall_7d_mm": round(sum(r7), 3),
        "rainfall_30d_mm": round(sum(r30), 3),
        "soil_moisture_pct": round(float(soil), 3),
        "temperature_24h_mean_c": round(sum(recent_temp) / len(recent_temp), 3) if recent_temp else None,
        "relative_humidity_24h_mean_pct": round(sum(recent_rh) / len(recent_rh), 3) if recent_rh else None,
    }


def historical_events(point, all_events, event_date, radius_km=50):
    lat = float(point["lat"])
    lon = float(point["lon"])
    cutoff = date.fromisoformat(event_date)
    count = 0
    for e in all_events:
        ed = date.fromisoformat(e["event_date"])
        if ed >= cutoff:
            continue
        dy = (e["lat"] - lat) * 111.0
        dx = (e["lon"] - lon) * 111.0 * math.cos(math.radians(lat))
        if math.hypot(dx, dy) <= radius_km:
            count += 1
    return count


def build_one(item, label, all_events, inventory_source):
    w = weather(item["lat"], item["lon"], item["event_date"])
    dem = fetch_dem_features(item["lat"], item["lon"])
    if "slope_deg" not in dem:
        raise ValueError(dem.get("error", "DEM failed"))
    nd = fetch_sentinel_ndvi(item["lat"], item["lon"], item["event_date"])
    if "ndvi" not in nd:
        raise ValueError(nd.get("error", "NDVI failed"))
    return {
        **w,
        "slope_deg": dem["slope_deg"],
        "elevation_m": dem["elevation_m"],
        "ndvi": nd["ndvi"],
        "historical_events": historical_events(item, all_events, item["event_date"]),
        "landslide_occurred": label,
        "sample_type": "observed_landslide" if label == 1 else "background_non_event",
        "latitude": item["lat"],
        "longitude": item["lon"],
        "event_date": item["event_date"],
        "event_year": int(item["event_date"][:4]),
        "inventory_source": inventory_source,
        "terrain_source": dem["source"],
        "satellite_source": nd["source"],
        "weather_source": "Open-Meteo ERA5-Land historical reanalysis",
    }


def _distance_km(a_lat, a_lon, b_lat, b_lon):
    dy = (a_lat - b_lat) * 111.0
    dx = (a_lon - b_lon) * 111.0 * math.cos(math.radians((a_lat + b_lat) / 2))
    return math.hypot(dx, dy)


def make_negatives(events, start_year, end_year, negatives_per_event, seed=26001):
    rng = random.Random(seed)
    n = max(1, len(events) * negatives_per_event)
    years = list(range(start_year, end_year + 1))
    event_dates = [e["event_date"] for e in events]
    out = []
    attempts = 0
    while len(out) < n and attempts < n * 100:
        attempts += 1
        lat = rng.uniform(NER_BBOX[0] + 0.15, NER_BBOX[1] - 0.15)
        lon = rng.uniform(NER_BBOX[2] + 0.15, NER_BBOX[3] - 0.15)
        year = years[(len(out) + rng.randrange(len(years))) % len(years)]
        if year in {int(x[:4]) for x in event_dates} and rng.random() < 0.25:
            d = date.fromisoformat(rng.choice(event_dates))
            if d.year != year:
                d = date(year, rng.randint(1, 12), 1)
        else:
            day_of_year = rng.randint(1, 365 if year % 4 else 366)
            d = date(year, 1, 1) + timedelta(days=day_of_year - 1)
        too_close = False
        for e in events:
            if abs((d - date.fromisoformat(e["event_date"])).days) <= 7 and _distance_km(lat, lon, e["lat"], e["lon"]) < 25:
                too_close = True
                break
        if too_close:
            continue
        out.append({"lat": lat, "lon": lon, "event_date": d.isoformat()})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2016)
    ap.add_argument("--end-year", type=int, default=2025)
    ap.add_argument("--max-events", type=int, default=0)
    ap.add_argument("--negatives-per-event", type=int, default=5)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    if args.end_year - args.start_year + 1 < 10:
        raise SystemExit("Use at least a 10-year window, for example 2016-2025.")
    events = fetch_events(args.start_year, args.end_year)
    if args.max_events > 0:
        events = events[:args.max_events]
    negatives = make_negatives(events, args.start_year, args.end_year, args.negatives_per_event)
    jobs = [(e, 1) for e in events] + [(n, 0) for n in negatives]
    print(f"Observed landslide samples: {len(events)}")
    print(f"Background samples requested: {len(negatives)}")
    print(f"Total feature extraction jobs: {len(jobs)}")
    rows = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(build_one, item, label, events, "NASA COOLR/GLC"): (item, label) for item, label in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            item, label = futs[f]
            try:
                rows.append(f.result())
                print(f"[{i}/{len(jobs)}] OK label={label} {item['lat']:.3f},{item['lon']:.3f} {item['event_date']}")
            except Exception as exc:
                print(f"[{i}/{len(jobs)}] SKIP label={label}: {exc}")
    df = pd.DataFrame(rows)
    required = ["rainfall_24h_mm", "rainfall_72h_mm", "soil_moisture_pct", "slope_deg", "elevation_m", "ndvi", "historical_events", "landslide_occurred"]
    df = df.dropna(subset=required)
    if len(df) < 200 or df.landslide_occurred.nunique() < 2:
        raise SystemExit(f"Only {len(df)} valid samples were built. Need at least 200 valid samples with both classes.")
    df = df.sort_values(["event_date", "landslide_occurred", "latitude", "longitude"]).reset_index(drop=True)
    df.to_csv(OUT, index=False)
    report = {
        "dataset": OUT.name,
        "period": f"{args.start_year}-{args.end_year}",
        "years": list(range(args.start_year, args.end_year + 1)),
        "region": "Northeast India",
        "bbox": NER_BBOX,
        "rows": int(len(df)),
        "observed_landslide_rows": int((df.landslide_occurred == 1).sum()),
        "background_rows": int((df.landslide_occurred == 0).sum()),
        "event_years_present": sorted(df.loc[df.landslide_occurred == 1, "event_year"].unique().tolist()),
        "feature_columns": required[:-1] + ["rainfall_7d_mm", "rainfall_30d_mm", "temperature_24h_mean_c", "relative_humidity_24h_mean_pct"],
        "inventory": "NASA COOLR with NASA Global Landslide Catalog fallback",
        "weather": "Open-Meteo ERA5-Land historical reanalysis",
        "terrain": "Copernicus DEM GLO-90 with SRTM fallback",
        "vegetation": "Sentinel-2 L2A with NASA MODIS MOD13Q1 fallback",
        "background_label_note": "Label 0 is a geographically and temporally screened background sample, not proof that no unreported landslide occurred.",
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved {len(df)} real historical samples -> {OUT}")
    print(f"Saved dataset report -> {REPORT}")
    print(df.groupby(["event_year", "landslide_occurred"]).size().to_string())


if __name__ == "__main__":
    main()
