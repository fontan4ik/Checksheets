import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import etm_onboarding_codes_local as onboarding
import sync_etm_codes as codes

COLUMNS = {'article': 1, 'model': 2, 'brand': 3, 'etm_code': 4}
MANIFEST = [{'offer_id': 'new-1', 'model': 'new', 'brand': 'DEKraft', 'title': 'Контактор'}]
ROWS = [['offer', 'model', 'brand', 'code'], ['new-1', 'new', 'DEKraft', '']]

class HelperTest(unittest.TestCase):
    def test_exact_aliases_only(self):
        self.assertEqual(codes.normalize_brand(' SE Dekraft '), 'dekraft')
        self.assertEqual(codes.normalize_brand('SE Systeme'), 'systeme electric')
        self.assertEqual(codes.normalize_brand('IEK'), 'iek')
        self.assertNotEqual(codes.normalize_brand('ONI'), codes.normalize_brand('IEK'))
        self.assertEqual(codes.normalize_brand('SE Unknown'), 'se unknown')

    def test_select_rejects_changed_identity(self):
        update = codes.Update(2, '123', 'other', 'new-1', 'DEKraft', 'ftp')
        self.assertEqual(onboarding.select_updates([update], {'new-1': MANIFEST[0]}), [])

    def test_readback_short_missing_changed_and_duplicate(self):
        update = codes.Update(2, '123', 'new', 'new-1', 'DEKraft', 'ftp')
        for rows in [[ROWS[0]], [ROWS[0], ['new-1']], [ROWS[0], ['new-1', 'other', 'DEKraft', '123']], [ROWS[0], ['new-1', 'new', 'DEKraft', '123'], ['new-1', 'new', 'DEKraft', '123']]]:
            with self.assertRaisesRegex(RuntimeError, 'read-back|duplicate'):
                onboarding.verify_updates(rows, COLUMNS, [update])

    def run_case(self, *, dry_run=False, lost_ftp=False, mutate_before_registry=False, api_pending=False):
        current = copy.deepcopy(ROWS)
        reads, writes = [], []
        def read(_):
            reads.append(1)
            if mutate_before_registry and len(reads) == 3:
                current[1][1] = 'changed'
            return copy.deepcopy(current)
        def write(_ws, rows, updates):
            writes.extend(updates)
            for update in updates:
                if not lost_ftp:
                    current[update.row - 1][3] = update.code
        def plan(rows, _columns, _mapping):
            return ([codes.Update(2, '123', 'new', 'new-1', 'DEKraft', 'ftp')] if not rows[1][3] else []), {}
        api = {'codes': {}, 'pending': [{'offer_id': 'new-1', 'reason': 'supplier_unit_review', 'unitReview': True}] if api_pending else [], 'unique_queries': 1, 'evidence': {}}
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'manifest.json'
            manifest.write_text(json.dumps(MANIFEST))
            with patch.object(onboarding, '__file__', str(Path(directory) / 'helper.py')), patch.object(onboarding.gsheets_utils, 'get_worksheet', return_value=object()), patch.object(codes, 'FTP_REMOTE_DIRS', [] if api_pending else ['/13']), patch.object(codes, 'FTP_LOCAL_ROOT', Path(directory)), patch.object(codes, 'fetch_ftp_source', return_value=(b'data', type('Remote', (), {'remote_path': 'remote.csv'})())), patch.object(codes, 'load_mapping_from_bytes', return_value=({}, {})), patch.object(codes, 'read_sheet_rows', side_effect=read), patch.object(codes, 'resolve_sheet_columns', return_value=COLUMNS), patch.object(codes, 'plan_updates', side_effect=plan), patch.object(codes, 'load_verified_matches', return_value={}), patch.object(codes, 'plan_verified_updates', return_value=([], {})) as registry, patch.object(codes, '_write_code_updates', side_effect=write), patch.object(onboarding, 'resolve_codes', return_value=api):
                result = onboarding.run_onboarding(manifest, dry_run=dry_run)
            receipt = json.loads((Path(directory) / 'logs/etm-onboarding-last.json').read_text()) if not dry_run else None
        return result, reads, writes, receipt, registry

    def test_all_ftp_writes_verified_and_receipt(self):
        result, reads, writes, receipt, _ = self.run_case()
        self.assertEqual(result, 0)
        self.assertEqual(len(writes), 1)
        self.assertEqual(receipt['written'], 1)
        self.assertGreaterEqual(len(reads), 5)

    def test_lost_ftp_write_raises_before_registry(self):
        with self.assertRaisesRegex(RuntimeError, 'read-back'):
            self.run_case(lost_ftp=True)

    def test_changed_identity_before_registry_raises(self):
        with self.assertRaisesRegex(RuntimeError, 'read-back'):
            self.run_case(mutate_before_registry=True)

    def test_dry_run_never_writes(self):
        _, _, writes, receipt, _ = self.run_case(dry_run=True)
        self.assertEqual(writes, [])
        self.assertIsNone(receipt)

    def test_api_unit_review_receipt_preserved(self):
        _, _, _, receipt, _ = self.run_case(api_pending=True)
        self.assertTrue(receipt['api']['pending'][0]['unitReview'])

if __name__ == '__main__': unittest.main()
