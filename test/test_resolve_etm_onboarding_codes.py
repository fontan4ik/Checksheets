import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from resolve_etm_onboarding_codes import validate_product, resolve_rows

ROW = {'offer_id': '18068DEK-1', 'model': '18068DEK', 'brand': 'DEKraft', 'title': 'Модульный контактор МК-103 3НО+1НЗ 25А 230В'}
PRODUCT = {'gdsCode': '6253372', 'gdsArt': '18068DEK', 'gdsExtArt': '18068DEK', 'gdsMnfName': 'Dekraft', 'gdsUnitName': 'шт', 'gdsNameTitle': 'Контактор модульный 3НО+1НЗ 25А 230В МК-103'}

class ExactIdentityTest(unittest.TestCase):
    def test_exact_identity(self):
        self.assertEqual(validate_product(ROW, PRODUCT), ('6253372', None))

    def test_reject_inferred_manufacturer(self):
        self.assertEqual(validate_product(ROW, {**PRODUCT, 'gdsMnfName': 'SE Dekraft'})[1], 'manufacturer_mismatch')

    def test_reject_other_article(self):
        self.assertEqual(validate_product(ROW, {**PRODUCT, 'gdsArt': '18069DEK'})[1], 'manufacturer_article_mismatch')
        self.assertEqual(validate_product(ROW, {**PRODUCT, 'gdsExtArt': '18069DEK'})[1], 'external_article_mismatch')

    def test_no_unit_guessing(self):
        self.assertEqual(validate_product(ROW, {**PRODUCT, 'gdsUnitName': 'м'})[1], 'supplier_unit_review')

    def test_title_corroboration(self):
        self.assertEqual(validate_product(ROW, {**PRODUCT, 'gdsNameTitle': 'Лампа светодиодная'})[1], 'title_corroboration_missing')
        self.assertEqual(validate_product({**ROW, 'title': ''}, PRODUCT)[1], 'title_corroboration_missing')

    def test_deduplicate_models_preserve_existing(self):
        calls = []
        def lookup(model):
            calls.append(model)
            return PRODUCT
        result = resolve_rows([ROW, {**ROW, 'offer_id': '18068DEK-3'}, {**ROW, 'offer_id': '18068DEK-6', 'code': 'existing'}], lookup)
        self.assertEqual(calls, ['18068DEK'])
        self.assertEqual(len(result['codes']), 2)
        self.assertEqual(result['pending'][0]['reason'], 'existing_code_preserved')

    def test_missing_or_duplicate_offer(self):
        with self.assertRaises(ValueError): resolve_rows([ROW, ROW], lambda _: PRODUCT)
        with self.assertRaises(ValueError): resolve_rows([{**ROW, 'offer_id': ''}], lambda _: PRODUCT)

    def test_lookup_failure_propagates(self):
        def lookup(_): raise RuntimeError('unavailable')
        with self.assertRaises(RuntimeError): resolve_rows([ROW], lookup)

if __name__ == '__main__': unittest.main()
