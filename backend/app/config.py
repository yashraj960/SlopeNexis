import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "NE India Disaster Management API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = "sqlite+aiosqlite:///./disaster_management.db"
    SECRET_KEY: str = "sih26001_super_secret_production_key_change_me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    OPENWEATHER_API_KEY: str = ""
    IMD_API_URL: str = ""
    IMD_API_KEY: str = ""
    ROUTING_API_URL: str = "https://router.project-osrm.org/route/v1/driving"
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    TWILIO_ALERT_TO: str = ""

    UPLOAD_DIR: str = os.path.join(os.getcwd(), "uploads")

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)