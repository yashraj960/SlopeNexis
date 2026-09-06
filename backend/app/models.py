from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean
from datetime import datetime, timezone
from app.database import Base

class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="field_officer")
    is_active = Column(Boolean, default=True)

class CitizenReportDB(Base):
    __tablename__ = "citizen_reports"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    citizen_name = Column(String, nullable=False)
    contact_number = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    incident_type = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    evidence_file = Column(String, nullable=True)
    status = Column(String, default="Pending Verification")
    submitted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class EmergencyContactDB(Base):
    __tablename__ = "emergency_contacts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    district = Column(String, nullable=False)
    state = Column(String, nullable=False)