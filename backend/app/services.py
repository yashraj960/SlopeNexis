import httpx
from twilio.rest import Client
from app.config import settings

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

async def fetch_live_weather(lat: float, lon: float) -> dict:
    """Return live weather from Open-Meteo; never substitute fabricated weather."""
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "precipitation,temperature_2m",
        "forecast_days": 2, "past_days": 1,
        "timezone": "auto"
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(OPEN_METEO, params=params)
        r.raise_for_status()
        data = r.json()
    hourly = data.get("hourly", {})
    precip = [float(x or 0) for x in hourly.get("precipitation", [])]
    temp = hourly.get("temperature_2m", [])
    if not precip:
        raise RuntimeError("Open-Meteo returned no precipitation samples")
    idx = max(0, len(precip) - 2)
    last24 = sum(precip[max(0, idx-23):idx+1])
    next24 = sum(precip[idx+1:idx+25])
    t = temp[idx] if idx < len(temp) else None
    condition = "Heavy Rain" if last24 >= 50 else "Rain" if last24 >= 10 else "Dry/Light Rain"
    return {
        "temp_c": round(float(t), 1) if t is not None else 0.0,
        "rainfall_24h_mm": round(last24, 1),
        "forecast_next_24h_mm": round(next24, 1),
        "condition": condition,
        "source": "Open-Meteo",
        "mode": "LIVE",
    }

def send_emergency_sms(to_phone: str, message_body: str):
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN or not settings.TWILIO_PHONE_NUMBER:
        return None
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(body=message_body, from_=settings.TWILIO_PHONE_NUMBER, to=to_phone)
        return message.sid
    except Exception as e:
        print(f"Twilio SMS Error: {e}")
        return None
