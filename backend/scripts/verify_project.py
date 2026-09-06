"""Static/in-process verification for the SlopeNexis project.
Does not call external services unless --network is used.
"""
from __future__ import annotations
import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path.insert(0, str(ROOT))


def main():
    py_files = list(PROJECT.rglob('*.py'))
    for f in py_files:
        ast.parse(f.read_text(encoding='utf-8'), filename=str(f))
    required = [
        ROOT/'app'/'main.py', ROOT/'app'/'real_data.py', ROOT/'app'/'geo_real.py',
        ROOT/'app'/'ml_model.py', ROOT/'app'/'routers'/'operations.py',
        PROJECT/'frontend'/'src'/'main.jsx', PROJECT/'frontend'/'src'/'style.css',
    ]
    missing=[str(x) for x in required if not x.exists()]
    assert not missing, f'Missing required files: {missing}'
    txt=(PROJECT/'frontend'/'src'/'main.jsx').read_text(encoding='utf-8')
    for token in ['/api/risk','/api/operations/forecast','/api/operations/priorities','/api/gis/layers','/api/v1/reports/submit','/api/alerts/evaluate-live/']:
        assert token in txt, f'Missing frontend integration: {token}'
    from app.ml_model import FEATURES, model_status
    assert len(FEATURES)==7
    print('VERIFY PASS')
    print(f'Python files parsed: {len(py_files)}')
    print('7 ML features:', ', '.join(FEATURES))
    print('Model status:', model_status())

if __name__ == '__main__':
    main()
