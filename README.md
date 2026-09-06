# SlopeNexis — AI-Based Early Warning & Landslide Risk Monitoring System (NER)

This build is configured for **REAL DATA MODE**. The AI model does not silently fall back to synthetic training data. You first build a real training table and train the model.

## Real data pipeline

1. **NASA COOLR** — primary historical landslide event inventory for the North Eastern Region; the builder paginates the ArcGIS service and automatically falls back to NASA's published Global Landslide Catalog CSV.
2. **Open-Meteo ERA5-Land** — historical rainfall, soil-moisture, temperature and humidity reanalysis for each event/background sample date.
3. **Copernicus DEM GLO-90 / USGS SRTM 90m** — real elevation plus locally derived slope; Open Topo Data is used as a public fallback when the Copernicus tile endpoint is unavailable.
4. **Sentinel-2 L2A / Microsoft Planetary Computer** — real satellite red/NIR bands used to calculate NDVI; for historical dates/scenes where Sentinel-2 is unavailable, the pipeline falls back to NASA MODIS MOD13Q1.061 250 m 16-day NDVI (real satellite data).
5. **Open-Meteo live forecast** — current rainfall, forecast rainfall and soil moisture.
6. **NASA COOLR live query** — nearby historical-event count.
7. **OpenStreetMap Overpass** — roads, villages and critical infrastructure, cached for 10 minutes to avoid unnecessary repeated queries.
8. **Esri World Imagery** — satellite basemap.
9. **Citizen/field reports** — real uploaded reports and optional photo/video evidence.
10. **Twilio SMS** — real SMS when valid Twilio credentials and `TWILIO_ALERT_TO` are configured.

NASA COOLR documents its event inventory and its manual/automatic mapping methods. Open-Meteo provides historical ERA5/ERA5-Land precipitation and soil-moisture variables. Copernicus DEM GLO-90 is used when reachable; the project falls back to the public USGS SRTM 90m API through Open Topo Data and derives slope from the returned local elevation grid. Slope/elevation are never taken from the old configured demo values. Sentinel-2 L2A can be searched through the public Planetary Computer STAC API; its assets can be signed for access without a registered account.

## 10-year large-data training design

The default training window is **2016-2025**, giving ten calendar years. The builder keeps observed NASA landslide events in that period and adds geographically and temporally screened background samples at a default ratio of 5 background samples per observed event. The background class is explicitly not treated as confirmed absence of landslides. The dataset also records 7-day and 30-day rainfall totals plus recent temperature and relative humidity for research/audit use.

Training uses a time-aware evaluation when the inventory contains both classes in the relevant years: training through 2022, validation on 2023-2024 when available, and an unseen 2025 test set when available. After evaluation, the final Random Forest is retrained on the complete 2016-2025 dataset for deployment.

## Important scientific limitation

COOLR is an observed/reporting inventory and therefore is not exhaustive ground truth. The training pipeline uses spatial hold-out validation to reduce geographic leakage, but the resulting metrics should be presented as **prototype validation**, not a guaranteed operational accuracy number.

## First-time setup — Windows

### Option A: one click

Run:

`RUN_REAL_DATASET.bat`

It installs dependencies, downloads/builds the real training table, trains the real Random Forest, runs the offline self-test, then starts backend and frontend.

### Option B: manual

Backend:

```powershell
cd backend
python -m pip install -r requirements.txt
python scripts/build_real_dataset.py --start-year 2016 --end-year 2025 --negatives-per-event 5 --workers 6
python scripts/train_real_model.py
python scripts/self_test.py
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend in a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL, normally `http://localhost:5173`.

## Verify the AI is real

Open:

`GET /api/model/status`

It must report:

- `mode: REAL`
- `real_dataset_exists: true`
- `trained_model_exists: true`
- metrics containing `roc_auc`, `precision`, `recall`, `f1`

If the real dataset/model is missing, `/api/risk` and `/api/predict` intentionally return a clear `503` instead of using synthetic training data.

## API features

- `/api/risk` — live real weather + DEM slope/elevation + Sentinel-2 NDVI + NASA COOLR + real trained AI.
- `/api/predict` — prediction using the trained real model for supplied feature values.
- `/api/operations/forecast` — live weather forecast/risk.
- `/api/operations/priorities` — AI-driven emergency prioritisation using live real features.
- `/api/gis/layers` — real OSM roads/villages/infrastructure.
- `/api/gis/satellite` — satellite basemap metadata.
- `/api/real-data/history/{location_id}` — nearby NASA COOLR events.
- `/api/alerts/evaluate-live/{location_id}` — evaluates the current live feature set and broadcasts an alert.
- `/api/v1/reports/submit` — stores geo-tagged citizen/field reports and optional media evidence.
- `/ws/alerts` — live WebSocket alert channel.

## Configuration for real SMS

Create `backend/.env` and set valid Twilio values:

```text
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=...
TWILIO_ALERT_TO=+91XXXXXXXXXX
```

If these are not configured, the dashboard still evaluates and broadcasts the real AI alert but reports SMS as `NOT_CONFIGURED`; it does not pretend an SMS was sent.

## Files for the real model

- `backend/scripts/build_real_dataset.py` — creates the real training dataset.
- `backend/scripts/train_real_model.py` — spatially validates and trains the model.
- `backend/app/geo_real.py` — DEM slope/elevation + Sentinel-2 NDVI extraction.
- `backend/app/ml_model.py` — real-data-only model loading in production mode.
- `backend/scripts/self_test.py` — offline schema/model readiness test and optional network smoke test.

## Network smoke test

After installing dependencies, run:

```powershell
cd backend
python scripts/self_test.py --network
```

This checks the live Open-Meteo, NASA COOLR, Copernicus DEM and Sentinel-2 paths from the same machine that will run the application.

## Important run location
The dependency file is at `backend/requirements.txt`; the included `RUN_REAL_DATASET.bat` automatically changes into `backend`. If you run commands manually, use `cd backend` first. A copy is also provided at the project root as `requirements.txt` for convenience.

## SlopeNexis completeness upgrades
- Multilingual UI and alert-ready text: English, Hindi, Assamese, Bengali and Khasi.
- PWA/offline shell with service worker and installable dashboard.
- Offline citizen/field report queue with automatic/manual synchronization when connectivity returns.
- Browser GPS capture for geo-tagged reports.
- Browser notifications for incoming non-LOW WebSocket alerts.
- SMS alert integration remains available through Twilio environment variables.
- Optional authorised IMD adapter at `GET /api/weather/imd/{location_id}`; configure `IMD_API_URL` and `IMD_API_KEY`. Open-Meteo remains the operational fallback.
- Road connectivity/ETA demo endpoint at `/api/operations/route` using OSRM/OpenStreetMap.
- Docker + Nginx deployment files for cloud/server deployment, including WebSocket proxying.

### Demo note
The IMD connector is intentionally configuration-driven because access to official IMD feeds depends on the authorised API/feed credentials supplied to the deployment. No fake IMD data is generated.
