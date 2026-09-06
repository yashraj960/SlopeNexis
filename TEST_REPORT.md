# SlopeNexis Verification Report

## Checks completed in the build environment

- Python syntax compilation: PASS (all backend Python files).
- Project verification script: PASS (required backend/frontend integration points found).
- Offline self-test: PASS.
- Real-model training logic: PASS using a temporary schema-valid test table; temporary model/data artifacts were removed after the test.
- Prediction path: PASS.
- SRTM terrain fallback calculation: PASS with a mocked 3x3 elevation response.
- MODIS fallback code path: statically corrected for datetime handling.
- Frontend map containment CSS: hardened so Leaflet stays inside `.map-container`.
- Frontend dependency installation/build: not executed in this environment because outbound package-network access is unavailable; the project retains normal `npm install` / `npm run dev` commands for the user's Windows machine.

## Real-data runtime behavior

Production/default mode is `REAL`. The project does not silently create a synthetic training dataset.

Terrain order:
1. Copernicus DEM GLO-90.
2. Public USGS SRTM 90m through Open Topo Data if Copernicus is unavailable.

Satellite NDVI order:
1. Sentinel-2 L2A through Microsoft Planetary Computer.
2. NASA MODIS MOD13Q1.061 through Microsoft Planetary Computer if Sentinel-2 is unavailable.

Historical landslide inventory order:
1. NASA COOLR.
2. NASA Global Landslide Catalog CSV if COOLR is unavailable.

Weather:
- Open-Meteo live forecast and historical archive.

GIS:
- OpenStreetMap Overpass for roads, villages and infrastructure.
- Esri World Imagery for the satellite basemap.

Alerts:
- Live AI evaluation endpoint uses live feature data.
- Twilio SMS is sent only when valid credentials are configured; otherwise SMS remains unconfigured and is not falsely reported as sent.
