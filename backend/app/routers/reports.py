from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional
import os
import uuid

from app.database import get_db
from app.models import CitizenReportDB
from app.schemas import AllReportsResponse, CitizenReportResponse, GeoLocation
from app.config import settings
from datetime import datetime, timezone

router = APIRouter(prefix="/api/v1/reports", tags=["Pillar E: Citizen Reporting"])

@router.post("/submit", response_model=dict)
async def submit_citizen_report(
    citizen_name: str = Form(...),
    contact_number: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    incident_type: str = Form(...),
    description: str = Form(...),
    media_file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db)
):
    saved_filename = "No media uploaded"

    if media_file:
        file_ext = os.path.splitext(media_file.filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{file_ext}"
        file_path = os.path.join(settings.UPLOAD_DIR, unique_filename)

        contents = await media_file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
        saved_filename = unique_filename

    new_report = CitizenReportDB(
        citizen_name=citizen_name,
        contact_number=contact_number,
        latitude=latitude,
        longitude=longitude,
        incident_type=incident_type,
        description=description,
        evidence_file=saved_filename,
        status="Pending Verification"
    )

    db.add(new_report)
    await db.commit()
    await db.refresh(new_report)

    return {
        "message": "Citizen report submitted successfully.",
        "report_details": CitizenReportResponse(
            report_id=new_report.id,
            citizen_name=new_report.citizen_name,
            contact_number=new_report.contact_number,
            geo_location=GeoLocation(latitude=new_report.latitude, longitude=new_report.longitude),
            incident_type=new_report.incident_type,
            description=new_report.description,
            evidence_file=new_report.evidence_file,
            status=new_report.status,
            submitted_at=new_report.submitted_at
        )
    }

@router.get("/all", response_model=AllReportsResponse)
async def get_all_reports(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CitizenReportDB))
    reports = result.scalars().all()

    formatted_reports = [
        CitizenReportResponse(
            report_id=r.id,
            citizen_name=r.citizen_name,
            contact_number=r.contact_number,
            geo_location=GeoLocation(latitude=r.latitude, longitude=r.longitude),
            incident_type=r.incident_type,
            description=r.description,
            evidence_file=r.evidence_file,
            status=r.status,
            submitted_at=r.submitted_at
        ) for r in reports
    ]

    return {"total_reports": len(formatted_reports), "reports": formatted_reports}
@router.post("/sync-offline", response_model=dict)
async def sync_offline_reports(payload: dict, db: AsyncSession = Depends(get_db)):
    """Sync reports queued by the PWA while offline. Media is uploaded separately when connectivity exists."""
    items = payload.get("reports", [])
    synced=[]
    for item in items:
        try:
            row=CitizenReportDB(citizen_name=str(item.get("name","Offline citizen")), contact_number=str(item.get("contact_number","N/A")), latitude=float(item["lat"]), longitude=float(item["lng"]), incident_type=str(item.get("type","Field report")), description=str(item.get("description","")), evidence_file="Queued offline - no media", status="Pending Verification")
            db.add(row); await db.flush(); synced.append({"local_id":item.get("id"),"report_id":row.id})
        except Exception:
            continue
    await db.commit()
    return {"message":"Offline queue synchronized", "synced":synced, "count":len(synced), "synced_at":datetime.now(timezone.utc).isoformat()}
