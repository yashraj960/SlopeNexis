from fastapi import APIRouter
from app.real_data import fetch_osm_layers
from app.main_data import LOCATIONS

router = APIRouter(prefix="/api/gis", tags=["GIS Layers"])

@router.get("/layers")
async def layers():
    data = await fetch_osm_layers(LOCATIONS)
    return data

@router.get("/satellite")
def satellite():
    return {
        "provider": "Esri World Imagery",
        "type": "satellite_basemap",
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attribution": "Tiles © Esri",
        "ndvi_provider": "Copernicus Sentinel-2 L2A / NASA MODIS MOD13Q1 via Microsoft Planetary Computer",
        "ndvi_note": "Satellite basemap is live imagery. NDVI observations should be treated as remote-sensing indicators, not direct landslide measurements."
    }
