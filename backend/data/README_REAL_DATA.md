# Real-data training pipeline

`real_training_dataset.csv` is generated locally by `scripts/build_real_dataset.py` from public observations. It is intentionally not bundled as a fabricated CSV.

Sources:
- NASA COOLR event inventory: positive event labels and historical event context.
- Open-Meteo ERA5-Land: historical precipitation and soil moisture.
- Copernicus DEM GLO-90: elevation and derived local slope.
- Sentinel-2 L2A through Microsoft Planetary Computer: point NDVI from B04/B08.

The model is trained by `scripts/train_real_model.py` and saved to `app/landslide_model.joblib`, with metrics in `app/model_metrics.json`.

Important: COOLR is a reporting/inventory dataset, not exhaustive ground truth. A high validation score is not proof that the system can guarantee a landslide prediction.
