"""Real geospatial feature extraction for SlopeNexis.
Uses public Copernicus DEM GLO-90 when available, with Open Topo Data SRTM-90m as a
reliable public fallback. Satellite NDVI comes from Planetary Computer Sentinel-2
L2A with NASA MODIS MOD13Q1 fallback.
"""
from __future__ import annotations

import math
import time
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import requests
import rasterio
from pyproj import Transformer

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
PC_SIGN = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
_OPENTOPO_LOCK = threading.Lock()
_TERRAIN_CACHE: dict[tuple[float, float], dict] = {}
_NDVI_CACHE: dict[tuple[float, float, str], tuple[float, dict]] = {}


def _tile_part(value: float, positive: str, negative: str) -> str:
    n = math.floor(abs(value))
    hemi = positive if value >= 0 else negative
    return f"{hemi}{n:02d}_00"


def _dem_url(lat: float, lon: float) -> str:
    north = _tile_part(lat, "N", "S")
    east = _tile_part(lon, "E", "W")
    key = f"Copernicus_DSM_COG_30_{north}_{east}_DEM/Copernicus_DSM_COG_30_{north}_{east}_DEM.tif"
    return "https://copernicus-dem-90m.s3.eu-central-1.amazonaws.com/" + key


def _fetch_opentopodata_srtm90(lat: float, lon: float) -> dict:
    """Fallback terrain source using the public SRTM 90m elevation API.

    A 3x3 local elevation grid is queried and the central elevation plus a
    finite-difference slope are derived from the real SRTM elevations.
    """
    url = "https://api.opentopodata.org/v1/srtm90m"
    step = 0.001                                                 
    points = [(lat + dy * step, lon + dx * step) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
    locations = "|".join(f"{a:.6f},{b:.6f}" for a, b in points)
                                                                                       
                                                                                        
                                                            
    with _OPENTOPO_LOCK:
        time.sleep(1.05)
        last_error = None
        for attempt in range(3):
            try:
                r = requests.get(url, params={"locations": locations, "interpolation": "bilinear"}, timeout=30)
                if r.status_code == 429:
                    time.sleep(float(r.headers.get("Retry-After", "2")))
                    continue
                r.raise_for_status()
                payload = r.json()
                break
            except Exception as exc:
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"Open Topo Data request failed: {last_error}")
    if payload.get("status") != "OK":
        raise RuntimeError(payload.get("error", "Open Topo Data returned an error"))
    results = payload.get("results", [])
    if len(results) != 9:
        raise RuntimeError(f"Expected 9 SRTM elevations, got {len(results)}")
    values = [x.get("elevation") for x in results]
    if any(v is None or not np.isfinite(v) for v in values):
        raise RuntimeError("SRTM returned missing elevation cells")
    z = np.asarray(values, dtype=float).reshape(3, 3)
    elevation = float(z[1, 1])
    dy_m = step * 111320.0
    dx_m = step * 111320.0 * max(0.1, math.cos(math.radians(lat)))
    gy, gx = np.gradient(z, dy_m, dx_m)
                                                                  
    slope = float(np.degrees(np.arctan(np.sqrt(gx * gx + gy * gy))).mean())
    return {
        "elevation_m": round(elevation, 1),
        "slope_deg": round(float(np.clip(slope, 0, 90)), 2),
        "source": "USGS SRTM 90m via Open Topo Data",
        "source_url": url,
    }


def fetch_dem_features(lat: float, lon: float) -> dict:
    """Return real elevation and slope, preferring Copernicus and falling back to SRTM."""
    key = (round(float(lat), 5), round(float(lon), 5))
    cached = _TERRAIN_CACHE.get(key)
    if cached is not None:
        return dict(cached)
    copernicus_error = None
    try:
        url = _dem_url(lat, lon)
        with rasterio.open(url) as ds:
            transformer = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
            x, y = transformer.transform(lon, lat)
            row, col = ds.index(x, y)
            r0, r1 = max(0, row - 2), min(ds.height, row + 3)
            c0, c1 = max(0, col - 2), min(ds.width, col + 3)
            arr = ds.read(1, window=((r0, r1), (c0, c1)), masked=True).astype(float)
            if arr.size == 0 or np.ma.count(arr) < 9:
                raise ValueError("DEM window has insufficient valid cells")
            z = arr.filled(np.nan)
            center = z[min(2, z.shape[0]-1), min(2, z.shape[1]-1)]
            if not np.isfinite(center):
                center = float(np.nanmedian(z))
            px_x = abs(ds.transform.a)
            px_y = abs(ds.transform.e)
            gy, gx = np.gradient(z, px_y, px_x)
            slope = float(np.degrees(np.arctan(np.sqrt(gx * gx + gy * gy))))
            slope = float(np.nanmedian(slope))
            result = {
                "elevation_m": round(float(center), 1),
                "slope_deg": round(float(np.clip(slope, 0, 90)), 2),
                "source": "Copernicus DEM GLO-90",
                "source_url": url,
            }
            _TERRAIN_CACHE[key] = result
            return dict(result)
    except Exception as exc:
        copernicus_error = str(exc)

    try:
        result = _fetch_opentopodata_srtm90(lat, lon)
        result["fallback_reason"] = copernicus_error
        _TERRAIN_CACHE[key] = result
        return dict(result)
    except Exception as exc:
        return {
            "error": f"Terrain unavailable. Copernicus DEM: {copernicus_error}; SRTM/Open Topo Data: {exc}",
            "source": "Copernicus DEM GLO-90 / USGS SRTM 90m",
        }


def _sign_asset(href: str) -> str:
    r = requests.get(PC_SIGN, params={"href": href}, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data["href"]


def _search_sentinel(lat: float, lon: float, start: str, end: str):
    body = {
        "collections": ["sentinel-2-l2a"],
        "bbox": [lon - 0.03, lat - 0.03, lon + 0.03, lat + 0.03],
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": 10,
        "query": {"eo:cloud_cover": {"lt": 35}},
    }
    r = requests.post(PC_STAC, json=body, timeout=45)
    r.raise_for_status()
    feats = r.json().get("features", [])
    feats.sort(key=lambda x: (float(x.get("properties", {}).get("eo:cloud_cover", 100)), x.get("properties", {}).get("datetime", "")))
    return feats


def _read_point(asset_url: str, lat: float, lon: float) -> float:
    with rasterio.open(asset_url) as ds:
        transformer = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
        x, y = transformer.transform(lon, lat)
        row, col = ds.index(x, y)
        if row < 0 or col < 0 or row >= ds.height or col >= ds.width:
            raise ValueError("point outside Sentinel-2 asset")
        win = rasterio.windows.Window(max(0, col - 1), max(0, row - 1), 3, 3)
        a = ds.read(1, window=win, masked=True).astype(float)
        vals = a.compressed()
        if vals.size == 0:
            raise ValueError("no valid pixel")
        return float(np.median(vals))


def _fetch_modis_ndvi(lat: float, lon: float, target):
    """Historical real NDVI fallback using NASA MODIS MOD13Q1.061 via Planetary Computer."""
    from datetime import date as date_cls, timedelta
    body = {
        "collections": ["modis-13Q1-061"],
        "bbox": [lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05],
        "datetime": f"{(target-timedelta(days=30)).isoformat()}T00:00:00Z/{(target+timedelta(days=30)).isoformat()}T23:59:59Z",
        "limit": 20,
    }
    r = requests.post(PC_STAC, json=body, timeout=45)
    r.raise_for_status()
    feats = r.json().get("features", [])
    def scene_delta(item):
        raw = item.get("properties", {}).get("datetime") or "1900-01-01"
        try:
            scene_date = date_cls.fromisoformat(str(raw)[:10])
        except ValueError:
            scene_date = date_cls(1900, 1, 1)
        return abs((scene_date - target).days)
    feats.sort(key=scene_delta)
    for item in feats:
        assets = item.get("assets", {})
        asset = assets.get("250m_16_days_NDVI") or assets.get("NDVI")
        if not asset:
            continue
        href = asset.get("href") if isinstance(asset, dict) else asset
        signed = _sign_asset(href)
        value = _read_point(signed, lat, lon)
        if not np.isfinite(value) or value <= -2000:
            continue
                                                         
        ndvi = float(np.clip(value * 0.0001 if abs(value) > 2 else value, -1, 1))
        return {"ndvi": round(ndvi, 5), "source": "NASA MODIS MOD13Q1.061 / Microsoft Planetary Computer", "scene_id": item.get("id")}
    return {"error": "No valid MODIS NDVI scene found", "source": "NASA MODIS MOD13Q1.061 / Microsoft Planetary Computer"}


def fetch_sentinel_ndvi(lat: float, lon: float, date: Optional[str] = None) -> dict:
    """Extract point NDVI from the clearest public Sentinel-2 L2A scene near a date."""
    from datetime import date as date_cls, timedelta
    target = date_cls.fromisoformat(date) if date else date_cls.today()
    cache_key = (round(float(lat), 5), round(float(lon), 5), target.isoformat())
    cached = _NDVI_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < 900:
        return dict(cached[1])
                                                                               
    start = target - timedelta(days=20)
    end = target + timedelta(days=20)
    def cache_result(result: dict) -> dict:
        if "ndvi" in result:
            _NDVI_CACHE[cache_key] = (time.time(), dict(result))
        return result
    try:
        feats = _search_sentinel(lat, lon, start.isoformat(), end.isoformat())
        if not feats:
            return cache_result(_fetch_modis_ndvi(lat, lon, target))
        for item in feats:
            assets = item.get("assets", {})
            if "B04" not in assets or "B08" not in assets:
                continue
            red = _sign_asset(assets["B04"]["href"])
            nir = _sign_asset(assets["B08"]["href"])
            rv = _read_point(red, lat, lon)
            nv = _read_point(nir, lat, lon)
                                                               
            if max(abs(rv), abs(nv)) > 2:
                rv, nv = rv / 10000.0, nv / 10000.0
            denom = nv + rv
            if abs(denom) < 1e-9:
                continue
            ndvi = float(np.clip((nv - rv) / denom, -1, 1))
            return cache_result({
                "ndvi": round(ndvi, 5),
                "source": "Sentinel-2 L2A / Microsoft Planetary Computer",
                "scene_id": item.get("id"),
                "scene_date": item.get("properties", {}).get("datetime"),
                "cloud_cover_pct": item.get("properties", {}).get("eo:cloud_cover"),
            })
        return cache_result(_fetch_modis_ndvi(lat, lon, target))
    except Exception as exc:
        try:
            fallback = _fetch_modis_ndvi(lat, lon, target)
            if "ndvi" in fallback:
                fallback["sentinel_error"] = str(exc)
                return cache_result(fallback)
        except Exception as modis_exc:
            return {"error": f"Sentinel-2 and MODIS NDVI unavailable: {exc}; MODIS: {modis_exc}", "source": "Sentinel-2/MODIS"}
        return {"error": f"Sentinel NDVI unavailable: {exc}", "source": "Sentinel-2 L2A / Planetary Computer"}
