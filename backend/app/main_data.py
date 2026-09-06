from pathlib import Path
import json
DATA_FILE=Path(__file__).resolve().parent.parent/"data"/"locations.json"
LOCATIONS=json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else []
