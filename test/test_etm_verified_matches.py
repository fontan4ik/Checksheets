import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('etm_verified_test_module', Path(__file__).resolve().parents[1] / 'sync_etm_codes.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

HEADERS = ['Артикул продавца', 'Артикул производителя', 'brand', 'CODES']
COLUMNS = dict(article=1, model=2, brand=3, etm_code=4)
ENTRY = dict(offer_id='A-1', model='00123', brand='DKC', etm_code='00007', etm_article='00123',
             etm_manufacturer='DKC IT', evidence=[dict(source='ETM API', url='https://example.com/item', note='Exact catalog article and product identity reviewed')])


class VerifiedMatchesTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'registry.json'
            path.write_text(json.dumps(data), encoding='utf8')
            return m.load_verified_matches(path)

    def test_missing_registry_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(m.load_verified_matches(Path(tmp) / 'absent.json'), {})

    def test_valid_registry_keeps_leading_zeros(self):
        records = self.load(dict(version=1, entries=[ENTRY]))
        updates, _ = m.plan_verified_updates([HEADERS, [' A-1 ', '00123', ' dkc ', '']], COLUMNS, records)
        self.assertEqual([(u.code, u.model, u.matched_by) for u in updates], [('00007', '00123', 'verified')])

    def test_schema_rejects_invalid_entries(self):
        cases = [dict(version=2, entries=[]), dict(version=True, entries=[]), dict(version=1, entries={})]
        for key, value in [('offer_id', ''), ('model', ''), ('etm_article', ''), ('etm_manufacturer', ''),
                           ('etm_code', 'ETM123'), ('etm_code', 123), ('etm_code', '12.0'), ('etm_code', '000'), ('brand', None),
                           ('evidence', []), ('evidence', [{}])]:
            entry = copy.deepcopy(ENTRY)
            entry[key] = value
            cases.append(dict(version=1, entries=[entry]))
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.load(data)

    def test_conflicting_duplicate_offer_rejected_including_model_and_brand(self):
        for key in ['model', 'brand', 'etm_code']:
            conflicting = dict(ENTRY, **{key: 'different' if key != 'etm_code' else '999'})
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.load(dict(version=1, entries=[ENTRY, conflicting]))
        self.assertEqual(len(self.load(dict(version=1, entries=[ENTRY, ENTRY]))), 1)

    def test_stale_offer_model_brand_and_existing_code_never_selected(self):
        rows = [HEADERS, ['a-1', '00123', 'DKC', ''], ['A-1', '123', 'DKC', ''],
                ['A-1', '00123', 'DKC IT', ''], ['A-1', '00123', '', ''], ['A-1', '00123', 'DKC', 'keep']]
        updates, stats = m.plan_verified_updates(rows, COLUMNS, {'A-1': ENTRY})
        self.assertEqual(updates, [])
        self.assertEqual(stats, dict(matched=0, existing=1, stale=3, unmatched=1))

    def test_blank_brand_only_matches_explicit_blank_expected(self):
        record = dict(ENTRY, brand='')
        rows = [HEADERS, ['A-1', '00123', '', ''], ['A-1', '00123', 'DKC', '']]
        updates, _ = m.plan_verified_updates(rows, COLUMNS, {'A-1': record})
        self.assertEqual([u.row for u in updates], [2])

    def test_registry_validation_precedes_any_sheet_access_or_write(self):
        with patch.object(m, 'load_verified_matches', side_effect=ValueError('bad registry')), \
             patch.object(m.gsheets_utils, 'get_worksheet') as get_sheet, \
             patch.object(m.gsheets_utils, 'update_column_by_header_masked') as write:
            with self.assertRaises(ValueError):
                m.run(verified_only=True)
            get_sheet.assert_not_called()
            write.assert_not_called()

    def test_verified_only_skips_ftp_and_rereads_current_identity(self):
        original = [HEADERS, ['A-1', '00123', 'DKC', '']]
        changed = [HEADERS, ['A-1', '00123', 'DKC', 'manual-code']]
        with patch.object(m, 'load_verified_matches', return_value={'A-1': ENTRY}), \
             patch.object(m, 'fetch_ftp_source') as ftp, \
             patch.object(m.gsheets_utils, 'get_worksheet', return_value=Mock()), \
             patch.object(m, 'read_sheet_rows', side_effect=[original, changed]) as read, \
             patch.object(m.gsheets_utils, 'update_column_by_header_masked') as write:
            self.assertEqual(m.run(verified_only=True), 0)
            ftp.assert_not_called()
            self.assertEqual(read.call_count, 2)
            write.assert_not_called()

    def test_default_daily_runs_registry_after_both_ftp_sources(self):
        rows = [HEADERS, ['A-1', '00123', 'DKC', '']]
        with patch.object(m, 'load_verified_matches', return_value={'A-1': ENTRY}), \
             patch.object(m, 'fetch_ftp_source', return_value=(b'', m.FtpFile('price.csv'))) as ftp, \
             patch.object(m, 'load_mapping_from_bytes', return_value=({}, dict(source_rows=0, mapping_keys=0, duplicate_rows=0, empty_rows=0, conflict_keys=0))), \
             patch.object(m.gsheets_utils, 'get_worksheet', return_value=Mock()) as get_sheet, \
             patch.object(m, 'read_sheet_rows', side_effect=lambda _: copy.deepcopy(rows)), \
             patch.object(m.gsheets_utils, 'update_column_by_header_masked') as write:
            self.assertEqual(m.run(), 0)
            self.assertEqual([c.args[0] for c in ftp.call_args_list], list(m.FTP_REMOTE_DIRS))
            write.assert_called_once_with(get_sheet.return_value, 'CODES', [['00007']], [True])

    def test_dry_run_registry_does_not_double_count_ftp_or_write(self):
        rows = [HEADERS, ['A-1', '00123', 'DKC', '']]
        stats = dict(source_rows=1, mapping_keys=1, duplicate_rows=0, empty_rows=0, conflict_keys=0)
        with patch.object(m, 'load_verified_matches', return_value={'A-1': ENTRY}), \
             patch.object(m, 'load_csv_mapping', return_value=({('00123', 'dkc'): '333'}, stats)), \
             patch.object(m.gsheets_utils, 'get_worksheet', return_value=Mock()), \
             patch.object(m, 'read_sheet_rows', return_value=copy.deepcopy(rows)), \
             patch.object(m, 'plan_verified_updates', wraps=m.plan_verified_updates) as planner, \
             patch.object(m.gsheets_utils, 'update_column_by_header_masked') as write:
            self.assertEqual(m.run('test.csv', dry_run=True), 0)
            self.assertEqual(planner.call_args.args[0][1][3], '333')
            write.assert_not_called()

    def test_verified_only_dry_run_no_writes(self):
        with patch.object(m, 'load_verified_matches', return_value={'A-1': ENTRY}), \
             patch.object(m, 'fetch_ftp_source') as ftp, \
             patch.object(m.gsheets_utils, 'get_worksheet', return_value=Mock()), \
             patch.object(m, 'read_sheet_rows', return_value=[HEADERS, ['A-1', '00123', 'DKC', '']]), \
             patch.object(m.gsheets_utils, 'update_column_by_header_masked') as write:
            self.assertEqual(m.run(verified_only=True, dry_run=True), 0)
            ftp.assert_not_called()
            write.assert_not_called()

    def test_cli_verified_only(self):
        with patch.object(sys, 'argv', ['sync_etm_codes.py', '--verified-only', '--dry-run']):
            args = m.parse_args()
        self.assertTrue(args.verified_only)
        self.assertTrue(args.dry_run)


if __name__ == '__main__':
    unittest.main()
