"""Build a current-catalog document candidate manifest; offline only."""
from __future__ import annotations
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / 'test/certificate_api_pilot_20261012'
sys.path.insert(0, str(API))
import expand_found_certificates_queue_20261014 as exp

SNAP = HERE / 'live_marketplaces_snapshot_resume_20261020.json'
OUT = HERE / 'expanded_found_certificates_manifest_20261020.json'
snapshot = json.loads(SNAP.read_text())
if snapshot.get('ozon_products', {}).get('complete') is not True:
    raise RuntimeError('Current Ozon catalog snapshot is incomplete')
original_load = exp.load

def load_current_products(path):
    if Path(path).name == 'all_found_ozon_products_snapshot_20261014.json':
        return {'complete': True, 'products': snapshot['ozon_products']['products']}
    return original_load(path)

exp.load = load_current_products
original_paths = exp.corpus_json_paths
exp.corpus_json_paths = lambda: [p for p in original_paths()
    if not p.name.startswith(('live_marketplaces_snapshot', 'current_coverage_report'))]
manifest = exp.build_expanded_manifest()
manifest['current_catalog_snapshot'] = str(SNAP)
manifest['built_against_current_catalog_at'] = snapshot['ozon_products']['checked_at']
OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'manifest': str(OUT), 'built_at': manifest.get('built_at'),
    'coverage': manifest.get('coverage'), 'skips': len(manifest.get('expansion_skips', []))},
    ensure_ascii=False, indent=2))
