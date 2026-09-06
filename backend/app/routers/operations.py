from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
import asyncio
from app.real_data import fetch_open_meteo, fetch_coolr_count
from app.geo_real import fetch_dem_features, fetch_sentinel_ndvi
from app.main_data import LOCATIONS
from app.ml_model import get_model, predict

router = APIRouter(prefix="/api/operations", tags=["Operations"])

async def live_features(loc):
    w, dem, nd, hist = await asyncio.gather(
        fetch_open_meteo(loc["lat"], loc["lng"]),
        asyncio.to_thread(fetch_dem_features, loc["lat"], loc["lng"]),
        asyncio.to_thread(fetch_sentinel_ndvi, loc["lat"], loc["lng"]),
        fetch_coolr_count(loc["lat"], loc["lng"], 0.75),
    )
    if "slope_deg" not in dem or "ndvi" not in nd:
        raise RuntimeError(f"terrain/satellite unavailable: {dem.get('error')} | {nd.get('error')}")
    values={"rainfall_24h_mm":w["rainfall_24h_mm"],"rainfall_72h_mm":w["rainfall_72h_mm"],"soil_moisture_pct":w["soil_moisture_pct"],"slope_deg":dem["slope_deg"],"elevation_m":dem["elevation_m"],"ndvi":nd["ndvi"],"historical_events":hist["count"]}
    return w,dem,nd,hist,values

@router.get("/forecast")
async def forecast():
    rows=[]
    for loc in LOCATIONS:
        try:
            w,_,_,_,v=await live_features(loc)
            rain=w["rainfall_24h_mm"]; next24=w["forecast_next_24h_mm"]
            score=min(100,round(rain*.55+next24*.30+v["soil_moisture_pct"]*.15,1))
            rows.append({"location_id":loc["id"],"location_name":loc["name"],"rainfall_24h_mm":rain,"next_24h_mm":next24,"trend":"RISING" if next24>rain else "STABLE","weather_risk_percent":score,"forecast_window":"Next 24 hours","source":w["source"],"soil_moisture_pct":v["soil_moisture_pct"]})
        except Exception as e:
            rows.append({"location_id":loc["id"],"location_name":loc["name"],"rainfall_24h_mm":None,"next_24h_mm":None,"trend":"DATA UNAVAILABLE","weather_risk_percent":None,"forecast_window":"Next 24 hours","source":str(e)})
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"forecast":rows}

@router.get("/priorities")
async def priorities():
    try: model=get_model()
    except Exception as e: raise HTTPException(503,str(e))
    out=[]
    for loc in LOCATIONS:
        try:
            w,dem,nd,h,v=await live_features(loc)
            probability,level=predict(model,v)
            score=round(probability*100,1)
            action="EVACUATION / ROAD CLOSURE" if level=="CRITICAL" else "FIELD INSPECTION" if level=="HIGH" else "MONITOR"
            out.append({"location_id":loc["id"],"location_name":loc["name"],"priority_score":score,"risk_level":level,"recommended_action":action,"source":"AI + Open-Meteo + Copernicus DEM + Sentinel-2 + NASA COOLR"})
        except Exception as e:
            out.append({"location_id":loc["id"],"location_name":loc["name"],"priority_score":None,"recommended_action":"DATA CHECK","source":str(e)})
    return sorted(out,key=lambda x:x["priority_score"] if x["priority_score"] is not None else -1,reverse=True)
