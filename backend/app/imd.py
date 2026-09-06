import httpx
from datetime import datetime, timezone
from app.config import settings

async def fetch_imd_weather(lat: float, lon: float):
    """Optional IMD adapter. Configure IMD_API_URL/IMD_API_KEY when an authorised IMD feed is available."""
    if not settings.IMD_API_URL:
        return None
    headers = {}
    if settings.IMD_API_KEY:
        headers["Authorization"] = f"Bearer {settings.IMD_API_KEY}"
        headers["X-API-Key"] = settings.IMD_API_KEY
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(settings.IMD_API_URL, params={"lat": lat, "lon": lon}, headers=headers)
            r.raise_for_status()
            data = r.json()
        rain = data.get("rainfall_24h_mm", data.get("rain_24h_mm", data.get("rainfall", 0)))
        temp = data.get("temp_c", data.get("temperature", data.get("temp", 0)))
        return {"source":"IMD", "rainfall_24h_mm":float(rain or 0), "temp_c":float(temp or 0), "raw":data, "updated_at":datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        return {"source":"IMD_UNAVAILABLE", "error":str(exc)}
