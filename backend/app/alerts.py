from collections import deque
from datetime import datetime, timezone
from typing import Set
from fastapi import WebSocket

class AlertManager:
    def __init__(self):
        self.alerts = deque(maxlen=200)
        self.clients: Set[WebSocket] = set()

    def build_alert(self, location: dict, probability: float, level: str, reason: str) -> dict:
        return {
            "id": f"ALT-{int(datetime.now(timezone.utc).timestamp())}",
            "location_id": location["id"],
            "location_name": location["name"],
            "district": location["district"],
            "state": location["state"],
            "lat": location["lat"],
            "lng": location["lng"],
            "risk_probability": round(probability, 4),
            "risk_percent": round(probability * 100, 1),
            "risk_level": level,
            "reason": reason,
            "triggered_at": datetime.now(timezone.utc).isoformat()
        }

    def add(self, alert: dict):
        self.alerts.appendleft(alert)

    def recent(self, limit: int = 50):
        return list(self.alerts)[:limit]

    async def broadcast(self, message: dict):
        disconnected = set()
        for client in self.clients:
            try:
                await client.send_json(message)
            except Exception:
                disconnected.add(client)
        self.clients -= disconnected

alerts = AlertManager()