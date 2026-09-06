from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime

class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role: Optional[str] = "field_officer"

class UserResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    role: str
    is_active: bool

    class Config:
        from_attributes = True

class WeatherData(BaseModel):
    temp_c: float
    rainfall_24h_mm: float
    condition: str

class SatelliteAnalysis(BaseModel):
    vegetation_index: float
    landslide_susceptibility: str

class TerrainProfile(BaseModel):
    elevation_m: float
    slope_deg: float

class StateAnalysisResponse(BaseModel):
    state: str
    timestamp: str
    weather_data: WeatherData
    soil_moisture_percentage: float
    satellite_analysis: SatelliteAnalysis
    terrain_profile: TerrainProfile
    historical_risk_trend: List[str]
    calculated_risk_level: str

class GeoLocation(BaseModel):
    latitude: float
    longitude: float

class CitizenReportResponse(BaseModel):
    report_id: int
    citizen_name: str
    contact_number: str
    geo_location: GeoLocation
    incident_type: str
    description: str
    evidence_file: Optional[str]
    status: str
    submitted_at: datetime

class AllReportsResponse(BaseModel):
    total_reports: int
    reports: List[CitizenReportResponse]

class PredictionInput(BaseModel):
    rainfall_24h_mm: float = Field(ge=0, le=1000)
    rainfall_72h_mm: float = Field(ge=0, le=2000)
    soil_moisture_pct: float = Field(ge=0, le=100)
    slope_deg: float = Field(ge=0, le=90)
    elevation_m: float = Field(ge=-100, le=9000)
    ndvi: float = Field(ge=-1, le=1)
    historical_events: int = Field(ge=0, le=100)