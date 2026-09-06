from pathlib import Path
import json
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
import joblib

APP_DIR = Path(__file__).resolve().parent
MODEL_PATH = APP_DIR / "landslide_model.joblib"
METRICS_PATH = APP_DIR / "model_metrics.json"
DATASET_PATH = APP_DIR.parent / "data" / "real_training_dataset.csv"
FEATURES = ["rainfall_24h_mm","rainfall_72h_mm","soil_moisture_pct","slope_deg","elevation_m","ndvi","historical_events"]


def make_demo_model():
                                                                      
    rng=np.random.default_rng(26001); n=1500
    r24=rng.gamma(2.2,22,n).clip(0,220); r72=(r24*rng.uniform(1.3,3.4,n)).clip(0,500)
    soil=rng.normal(55,18,n).clip(5,100); slope=rng.uniform(2,55,n); elev=rng.uniform(30,3200,n); ndvi=rng.uniform(.05,.9,n); hist=rng.poisson(1.8,n).clip(0,12)
    score=.018*r24+.010*r72+.025*soil+.065*slope+.35*hist-.65*ndvi; prob=1/(1+np.exp(-(score-5.5))); y=(rng.random(n)<prob).astype(int)
    X=np.column_stack([r24,r72,soil,slope,elev,ndvi,hist]); return X,y


def train_and_save_model(allow_demo=True):
    if DATASET_PATH.exists():
        df=pd.read_csv(DATASET_PATH).dropna(subset=FEATURES+['landslide_occurred'])
        if len(df)<60 or df['landslide_occurred'].nunique()!=2: raise RuntimeError('Real dataset exists but is not trainable.')
        X=df[FEATURES].values; y=df['landslide_occurred'].astype(int).values
    elif allow_demo:
        X,y=make_demo_model()
    else:
        raise RuntimeError('REAL_DATA mode requires backend/data/real_training_dataset.csv. Run scripts/build_real_dataset.py then scripts/train_real_model.py.')
    pipe=Pipeline([('scale',StandardScaler()),('rf',RandomForestClassifier(n_estimators=300,max_depth=14,min_samples_leaf=2,class_weight='balanced_subsample',random_state=26001,n_jobs=-1))])
    pipe.fit(X,y); joblib.dump(pipe,MODEL_PATH); return pipe


def get_model():
    mode=__import__('os').getenv('MODEL_MODE','real').lower()
    if mode=='demo':
        if MODEL_PATH.exists() and METRICS_PATH.exists():
            return joblib.load(MODEL_PATH)
        return train_and_save_model(True)
    if not DATASET_PATH.exists():
        raise RuntimeError('REAL_DATA model not trained. Run: python scripts/build_real_dataset.py && python scripts/train_real_model.py')
    if MODEL_PATH.exists() and METRICS_PATH.exists(): return joblib.load(MODEL_PATH)
    return train_and_save_model(False)


def model_status():
    mode=__import__('os').getenv('MODEL_MODE','real').lower()
    metrics=json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else None
    return {'mode':mode.upper(),'real_dataset_exists':DATASET_PATH.exists(),'trained_model_exists':MODEL_PATH.exists(),'metrics':metrics}


def predict(model, values:dict):
    x=pd.DataFrame([[values[k] for k in FEATURES]], columns=FEATURES, dtype=float)
    prob=float(model.predict_proba(x)[0][1])
    level='CRITICAL' if prob>=.75 else 'HIGH' if prob>=.50 else 'MODERATE' if prob>=.25 else 'LOW'
    return prob,level
