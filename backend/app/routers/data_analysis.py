from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
import asyncio
from app.real_data import fetch_open_meteo, fetch_coolr_count
from app.geo_real import fetch_dem_features, fetch_sentinel_ndvi
from app.schemas import StateAnalysisResponse

router = APIRouter(prefix="/api/v1/data-analysis", tags=["Pillar A: Data Analysis"])
STATE_COORDINATES = {
    "Sikkim": {"lat": 27.3389, "lon": 88.6065},
    "Arunachal Pradesh": {"lat": 27.5860, "lon": 91.8590},
    "Meghalaya": {"lat": 25.5788, "lon": 91.8933},
    "Assam": {"lat": 26.2006, "lon": 92.9376},
    "Nagaland": {"lat": 26.1584, "lon": 94.5624},
    "Manipur": {"lat": 24.6637, "lon": 93.9063},
    "Mizoram": {"lat": 23.1645, "lon": 92.9376},
    "Tripura": {"lat": 23.9408, "lon": 91.9882},
}

@router.get("/state/{state_name}", response_model=StateAnalysisResponse)
async def get_state_analysis(state_name: str):
    state_key = next((k for k in STATE_COORDINATES if k.lower() == state_name.lower()), None)
    if not state_key:
        raise HTTPException(404, detail=f"Supported states: {list(STATE_COORDINATES.keys())}")
    geo = STATE_COORDINATES[state_key]
    w, dem, nd, hist = await asyncio.gather(
        fetch_open_meteo(geo["lat"], geo["lon"]),
        asyncio.to_thread(fetch_dem_features, geo["lat"], geo["lon"]),
        asyncio.to_thread(fetch_sentinel_ndvi, geo["lat"], geo["lon"]),
        fetch_coolr_count(geo["lat"], geo["lon"], 0.75),
    )
    if "slope_deg" not in dem or "ndvi" not in nd:
        raise HTTPException(503, detail=f"Real terrain/satellite data unavailable: {dem.get('error')} | {nd.get('error')}")
    rain = w["rainfall_24h_mm"]
    soil = w["soil_moisture_pct"]
                                                                                      
    if soil >= 80 and rain >= 50 and dem["slope_deg"] >= 30:
        risk = "Critical - High Landslide Risk"
    elif soil >= 65 or rain >= 30 or dem["slope_deg"] >= 25:
        risk = "Moderate"
    else:
        risk = "Low"
    trend = ["Current 24h rainfall: %.1f mm" % rain, "Nearby historical events: %d" % hist["count"], "NDVI: %.2f" % nd["ndvi"]]
    return {
        "state": state_key,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "weather_data": {"temp_c": w.get("temperature_c") or 0.0, "rainfall_24h_mm": rain, "condition": "Rain" if rain > 0 else "Dry/Light Rain"},
        "soil_moisture_percentage": soil,
        "satellite_analysis": {"vegetation_index": nd["ndvi"], "landslide_susceptibility": risk},
        "terrain_profile": {"elevation_m": dem["elevation_m"], "slope_deg": dem["slope_deg"]},
        "historical_risk_trend": trend,
        "calculated_risk_level": risk,
    }
