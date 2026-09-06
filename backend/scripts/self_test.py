"""Offline/online readiness test for SlopeNexis.
Run from backend: python scripts/self_test.py
Use --network to also call the public data services.
"""
from __future__ import annotations
import argparse, asyncio, json, sys
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.ml_model import model_status, FEATURES, DATASET_PATH
from app.geo_real import fetch_dem_features, fetch_sentinel_ndvi
from app.real_data import fetch_open_meteo, fetch_coolr_count


def offline():
    checks={}
    checks['feature_count']=len(FEATURES)==7
    checks['dataset_schema']=True
    if DATASET_PATH.exists():
        df=pd.read_csv(DATASET_PATH); checks['dataset_schema']=all(c in df.columns for c in FEATURES+['landslide_occurred'])
    checks['model_status_endpoint_data']=isinstance(model_status(),dict)
    checks['locations_file']=(ROOT/'data'/'locations.json').exists()
    print(json.dumps({'mode':'OFFLINE','checks':checks,'model':model_status()},indent=2))
    return all(checks.values())

async def network():
    loc=json.loads((ROOT/'data'/'locations.json').read_text())[0]
    out={}
    try: out['open_meteo']=await fetch_open_meteo(loc['lat'],loc['lng'])
    except Exception as e: out['open_meteo_error']=str(e)
    try: out['coolr']=await fetch_coolr_count(loc['lat'],loc['lng'],0.75)
    except Exception as e: out['coolr_error']=str(e)
    out['dem']=fetch_dem_features(loc['lat'],loc['lng'])
    out['sentinel']=fetch_sentinel_ndvi(loc['lat'],loc['lng'])
    print(json.dumps(out,indent=2,default=str))
    return out

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--network',action='store_true'); args=ap.parse_args()
    ok=offline()
    if args.network: asyncio.run(network())
    raise SystemExit(0 if ok else 1)
