from contextlib import asynccontextmanager
from pathlib import Path
import json
import os
import asyncio
import random
from app.real_data import fetch_open_meteo, fetch_coolr_count
from app.geo_real import fetch_dem_features, fetch_sentinel_ndvi
from app.main_data import LOCATIONS
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routers import data_analysis, reports, auth, gis, operations
from app.ml_model import get_model, predict, model_status
from app.alerts import alerts
from app.services import send_emergency_sms
from app.imd import fetch_imd_weather
from app.i18n import LANGUAGES, all_localized_alerts, localized_alert, normalize_language
from app.schemas import PredictionInput

MODEL = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global MODEL
    await init_db()
    try:
        MODEL = get_model()
    except RuntimeError as exc:
                                                                                      
        print(f"MODEL NOT READY: {exc}")
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Unified Production API for NE India Landslide Risk Monitoring",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

app.include_router(auth.router)
app.include_router(data_analysis.router)
app.include_router(reports.router)
app.include_router(gis.router)
app.include_router(operations.router)

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "NE-Disaster-Backend", "model": model_status()}

@app.get("/api/model/status")
def model_info():
    return model_status()

@app.get("/api/model/metrics")
def model_metrics():
    info=model_status()
    if not info.get("metrics"):
        raise HTTPException(404, "No real-model validation metrics found. Train the real dataset first.")
    return info["metrics"]

@app.get("/api/locations")
def get_locations():
    return LOCATIONS

@app.get("/api/weather/imd/{location_id}")
async def imd_weather(location_id: str):
    loc = next((x for x in LOCATIONS if x["id"] == location_id), None)
    if not loc: raise HTTPException(404, "Location not found")
    data = await fetch_imd_weather(loc["lat"], loc["lng"])
    if not data or data.get("source") == "IMD_UNAVAILABLE":
        return {"configured": False, "source": "Open-Meteo fallback", "message": "Configure IMD_API_URL and IMD_API_KEY for an authorised IMD feed."}
    return {"configured": True, "location_id": location_id, **data}

@app.post("/api/predict")
def predict_risk(payload: PredictionInput):
    if MODEL is None:
        raise HTTPException(503, "Real model is not ready. Build and train the real dataset first.")
    probability, level = predict(MODEL, payload.model_dump())
    return {
        "risk_probability": probability,
        "risk_percent": round(probability * 100, 1),
        "risk_level": level,
        "input": payload.model_dump(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/risk")
async def current_risk():
    if MODEL is None:
        raise HTTPException(503, "Real model is not ready. Run the real-data build/train commands first.")
    result = []
    for loc in LOCATIONS:
        try:
            w, dem, nd = await asyncio.gather(
                fetch_open_meteo(loc["lat"], loc["lng"]),
                asyncio.to_thread(fetch_dem_features, loc["lat"], loc["lng"]),
                asyncio.to_thread(fetch_sentinel_ndvi, loc["lat"], loc["lng"]),
            )
            if "slope_deg" not in dem or "ndvi" not in nd:
                raise RuntimeError(f"Real terrain/satellite feature unavailable: {dem.get('error')} | {nd.get('error')}")
            hist = 0
            h = await fetch_coolr_count(loc["lat"], loc["lng"], 0.75)
            hist = h["count"]
            values = {
                "rainfall_24h_mm": w["rainfall_24h_mm"],
                "rainfall_72h_mm": w["rainfall_72h_mm"],
                "soil_moisture_pct": w["soil_moisture_pct"],
                "slope_deg": dem["slope_deg"],
                "elevation_m": dem["elevation_m"],
                "ndvi": nd["ndvi"],
                "historical_events": hist,
            }
            probability, level = predict(MODEL, values)
            result.append({
                **loc, "elevation_m": values["elevation_m"], "slope_deg": values["slope_deg"],
                "historical_events_live": hist, "ndvi_live": values["ndvi"],
                "sensor": {"rainfall_24h_mm": w["rainfall_24h_mm"], "rainfall_72h_mm": w["rainfall_72h_mm"], "soil_moisture_pct": w["soil_moisture_pct"]},
                "forecast_next_24h_mm": w["forecast_next_24h_mm"],
                "risk_probability": round(probability,4), "risk_percent": round(probability*100,1), "risk_level": level,
                "data_sources": {"weather": w["source"], "historical": "NASA COOLR", "terrain": dem["source"], "satellite": nd["source"]},
                "satellite_scene": nd.get("scene_id"), "satellite_scene_date": nd.get("scene_date"),
                "updated_at": w["updated_at"]
            })
        except Exception as e:
            result.append({**loc, "data_error": str(e), "data_sources": {"status": "REAL_DATA_UNAVAILABLE"}})
    return result

@app.get("/api/real-data/history/{location_id}")
async def real_history(location_id: str):
    loc = next((x for x in LOCATIONS if x["id"] == location_id), None)
    if not loc: raise HTTPException(404, "Location not found")
    return await fetch_coolr_count(loc["lat"], loc["lng"], 1.0)

@app.post("/api/alerts/evaluate-live/{location_id}")
async def evaluate_live_alert(location_id: str, language: str = "en"):
    if MODEL is None:
        raise HTTPException(503, "Real model is not ready.")
    loc = next((x for x in LOCATIONS if x["id"] == location_id), None)
    if not loc: raise HTTPException(404, "Location not found")
    w, dem, nd, h = await asyncio.gather(
        fetch_open_meteo(loc["lat"], loc["lng"]),
        asyncio.to_thread(fetch_dem_features, loc["lat"], loc["lng"]),
        asyncio.to_thread(fetch_sentinel_ndvi, loc["lat"], loc["lng"]),
        fetch_coolr_count(loc["lat"], loc["lng"], 0.75),
    )
    if "slope_deg" not in dem or "ndvi" not in nd:
        raise HTTPException(503, f"Real terrain/satellite data unavailable: {dem.get('error')} | {nd.get('error')}")
    values={"rainfall_24h_mm":w["rainfall_24h_mm"],"rainfall_72h_mm":w["rainfall_72h_mm"],"soil_moisture_pct":w["soil_moisture_pct"],"slope_deg":dem["slope_deg"],"elevation_m":dem["elevation_m"],"ndvi":nd["ndvi"],"historical_events":h["count"]}
    probability, level=predict(MODEL,values)
    reason=f"Live rainfall 24h {values['rainfall_24h_mm']:.1f} mm; 72h {values['rainfall_72h_mm']:.1f} mm; soil moisture {values['soil_moisture_pct']:.1f}%; slope {values['slope_deg']:.1f}°; NDVI {values['ndvi']:.2f}."
    alert=alerts.build_alert(loc,probability,level,reason)
    alert["feature_snapshot"] = {"rainfall_24h_mm": round(values["rainfall_24h_mm"],1), "soil_moisture_pct": round(values["soil_moisture_pct"],1), "slope_deg": round(values["slope_deg"],1)}
    language = normalize_language(language)
    alert["localized_messages"] = all_localized_alerts(alert)
    alerts.add(alert); await alerts.broadcast({"type":"LANDSLIDE_ALERT","alert":alert})
    sms_target=settings.TWILIO_ALERT_TO
    sms_status="NOT_CONFIGURED"
    sms_message=localized_alert(alert, language)
    if sms_target:
        sms_status="SENT" if send_emergency_sms(sms_target, sms_message) else "FAILED"
    return {"alert":alert,"features":values,"data_sources":{"weather":w["source"],"terrain":dem["source"],"satellite":nd["source"],"historical":"NASA COOLR"},"sms_status":sms_status,"sms_language":language,"sms_message":sms_message,"supported_languages":LANGUAGES}

                                                                                   
@app.post("/api/demo-simulate")
async def demo_simulate(req: dict):
    loc_id=req.get("location_id"); loc=next((x for x in LOCATIONS if x["id"]==loc_id),None)
    if not loc: raise HTTPException(404,"Location not found")
    values={"rainfall_24h_mm":random.uniform(90,180),"rainfall_72h_mm":random.uniform(220,450),"soil_moisture_pct":random.uniform(72,98),"slope_deg":loc["slope_deg"],"elevation_m":loc["elevation_m"],"ndvi":loc["ndvi"],"historical_events":loc["historical_events"]}
    if MODEL is None: raise HTTPException(503,"Model unavailable")
    probability,level=predict(MODEL,values); alert=alerts.build_alert(loc,probability,level,"DEMO ONLY: synthetic emergency input"); alert["localized_messages"] = all_localized_alerts(alert); alerts.add(alert); await alerts.broadcast({"type":"LANDSLIDE_ALERT","alert":alert})
    return {"alert":alert,"sensor":values,"demo":True,"supported_languages":LANGUAGES}


@app.get("/api/operations/route")
async def route_between(lat: float, lon: float, dest_lat: float = 26.1445, dest_lon: float = 91.7362):
    """Road-connectivity demo using OSRM; destination defaults to Guwahati emergency coordination point."""
    import httpx
    try:
        url=f"{settings.ROUTING_API_URL}/{lon},{lat};{dest_lon},{dest_lat}"
        async with httpx.AsyncClient(timeout=12) as client:
            r=await client.get(url, params={"overview":"false","steps":"false"})
            r.raise_for_status(); d=r.json()
        route=d.get("routes",[{}])[0]
        return {"source":"OSRM/OpenStreetMap", "distance_km":round(route.get("distance",0)/1000,2), "duration_min":round(route.get("duration",0)/60,1), "origin":{"lat":lat,"lon":lon}, "destination":{"lat":dest_lat,"lon":dest_lon}}
    except Exception as exc:
        raise HTTPException(503, f"Road routing unavailable: {exc}")

@app.get("/api/alerts")
def get_alerts():
    return alerts.recent()

@app.websocket("/ws/alerts")
async def websocket_alerts(ws: WebSocket):
    await ws.accept()
    alerts.clients.add(ws)
    await ws.send_json({"type": "CONNECTED", "message": "Real-time alert channel active"})
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        alerts.clients.discard(ws)
    except Exception:
        alerts.clients.discard(ws)