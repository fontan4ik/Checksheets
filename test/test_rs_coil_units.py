import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rs_sync_local as rs


class RSCoilUnitsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(
            (Path(__file__).parent / "new_rs_cable_units_20261020.json").read_text()
        )

    def test_supplier_fixture_counts_complete_sections_per_lot(self):
        expected = {
            "LC1-C5E04-121-T-R": 0,
            "LC1-C5E04-121-T-P-R": 3,
            "LC1-C5E04-321-T-P-R": 1,
            "LC1-C5E04-311": 0,
            "LC1-C5E04-111-T-R": 8,
        }
        for model, count in expected.items():
            with self.subTest(model=model):
                residue = copy.deepcopy(self.fixture["residues"][model])
                self.assertEqual(rs.parse_rs_coil_quantity(residue), count)
                residue["partnerQuantityInfo"] = {"partnerQuantity": 999999}
                self.assertEqual(rs.parse_rs_coil_quantity(residue), count)

    def test_invalid_evidence_is_rejected(self):
        valid = {"UOM_OKEI": "006", "Residue": "305", "qtyLots": "305"}
        for change in (
            {"UOM_OKEI": "778"}, {"UOM_OKEI": None}, {"qtyLots": None},
            {"qtyLots": ""}, {"qtyLots": "305;"}, {"qtyLots": "-1;306"},
            {"qtyLots": "NaN"}, {"qtyLots": "Infinity"}, {"Residue": "NaN"},
            {"Residue": -305}, {"Residue": True}, {"qtyLots": "304"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                rs.parse_rs_coil_quantity({**valid, **change})
        with self.assertRaises(ValueError):
            rs.parse_rs_coil_quantity(None)

    def test_decimal_precision_and_explicit_zero_lot(self):
        self.assertEqual(rs.parse_rs_coil_quantity(
            {"UOM_OKEI": "006", "Residue": "305.0000001", "qtyLots": ".0015;304.9985"}
        ), 0)
        self.assertEqual(rs.parse_rs_coil_quantity(
            {"UOM_OKEI": "006", "Residue": 0, "qtyLots": "0"}
        ), 0)
        for lots in (None, "", " "):
            self.assertEqual(rs.parse_rs_coil_quantity(
                {"UOM_OKEI": "006", "Residue": 0, "qtyLots": lots}
            ), 0)

    def test_fetch_targets_only_explicit_models_and_uses_production_retry(self):
        model = "LC1-C5E04-321-T-P-R"
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = self.fixture["residues"][model]
        with (
            patch.object(rs, "create_rs_session", return_value=http),
            patch.object(rs, "get_rs_headers", return_value={"test": "header"}),
            patch.object(rs, "rs_get_with_retry", return_value=response) as fetch,
            patch.object(rs.time, "sleep"),
        ):
            result = rs.fetch_rs_coil_quantities([model, model, "other"], {model: "1854834"}, 287)
        self.assertEqual(result, {model: 1})
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(fetch.call_args.args[1].endswith("/residue/287/1854834"))
        http.close.assert_called_once()

    def test_sync_changes_only_samara_coil_rows(self):
        model = "LC1-C5E04-111-T-R"
        catalog = {model: "coil", "ordinary": "ordinary"}
        stocks = rs.RSStockSnapshot()
        stocks.update({"coil": 2470, "ordinary": 20})
        worksheet = Mock()
        worksheet.col_values.return_value = ["Артикул производителя", model, "ordinary"]
        with (
            patch.object(rs.gsheets_utils, "get_worksheet", return_value=worksheet),
            patch.object(rs.gsheets_utils, "get_header_columns", return_value={"model": 2}),
            patch.object(rs, "fetch_rs_code_map", return_value=catalog),
            patch.object(rs, "fetch_all_rs_stocks", return_value=stocks),
            patch.object(rs, "fetch_rs_coil_quantities", return_value={model: 8}),
            patch.object(rs.gsheets_utils, "update_column_by_header_masked", return_value=2) as write,
        ):
            rs.sync_rs()
        self.assertEqual(write.call_args_list[0].args[1:3], ("RS SMR", [[8], [20]]))
        self.assertEqual(write.call_args_list[1].args[1:3], ("RS MSK", [[2470], [20]]))

    def test_quarantine_invalid_model_continues_and_retries_mismatch_once(self):
        bad = "LC1-C5E04-321-T-P-R"
        good = "LC1-C5E04-111-T-R"
        invalid_response = Mock(status_code=200)
        invalid_response.json.return_value = {"UOM_OKEI": "006", "Residue": 640, "qtyLots": "305"}
        good_response = Mock(status_code=200)
        good_response.json.return_value = self.fixture["residues"][good]
        with (
            patch.object(rs, "create_rs_session", return_value=Mock()),
            patch.object(rs, "get_rs_headers", return_value={}),
            patch.object(rs, "rs_get_with_retry", side_effect=[good_response, invalid_response, invalid_response]) as fetch,
            patch.object(rs.time, "sleep") as sleep,
        ):
            result = rs.fetch_rs_coil_quantities([bad, good], {bad: "bad", good: "good"}, 287, quarantine_invalid=True)
        self.assertEqual(result, {good: 8})
        self.assertEqual(result.invalid_models, {bad})
        self.assertEqual(fetch.call_count, 3)
        sleep.assert_any_call(2)

    def test_invalid_coil_preserves_samara_cell_and_receipt_excludes_freshness(self):
        model = "LC1-C5E04-321-T-P-R"
        catalog = {model: "coil", "ordinary": "ordinary"}
        stocks = rs.RSStockSnapshot()
        stocks.update({"coil": 640, "ordinary": 20})
        quantities = rs.RSCoilQuantities()
        quantities.invalid_models.add(model)
        worksheet = Mock()
        worksheet.col_values.return_value = ["Артикул производителя", model, "ordinary"]
        with (
            patch.object(rs.gsheets_utils, "get_worksheet", return_value=worksheet),
            patch.object(rs.gsheets_utils, "get_header_columns", return_value={"model": 2}),
            patch.object(rs, "fetch_rs_code_map", return_value=catalog),
            patch.object(rs, "fetch_all_rs_stocks", return_value=stocks),
            patch.object(rs, "fetch_rs_coil_quantities", return_value=quantities) as fetch,
            patch.object(rs.gsheets_utils, "update_column_by_header_masked", return_value=1) as write,
        ):
            receipt = rs.sync_rs()
        self.assertTrue(fetch.call_args.kwargs["quarantine_invalid"])
        self.assertEqual(write.call_args_list[0].args[1:], ("RS SMR", [[""], [20]], [False, True]))
        self.assertEqual(write.call_args_list[1].args[1:], ("RS MSK", [[640], [20]], [True, True]))
        self.assertEqual(receipt["quarantinedModels"], [model])

    def test_missing_code_and_http_error_quarantine_independently_but_strict_raises(self):
        models = ["LC1-C5E04-111-T-R", "LC1-C5E04-121-T-R"]
        with (
            patch.object(rs, "create_rs_session", return_value=Mock()),
            patch.object(rs, "get_rs_headers", return_value={}),
            patch.object(rs, "rs_get_with_retry", return_value=Mock(status_code=503)),
            patch.object(rs.time, "sleep"),
        ):
            result = rs.fetch_rs_coil_quantities(models, {models[1]: "code"}, 287, quarantine_invalid=True)
            self.assertEqual(result, {})
            self.assertEqual(result.invalid_models, set(models))
            with self.assertRaises(RuntimeError):
                rs.fetch_rs_coil_quantities(models, {}, 287)


if __name__ == "__main__":
    unittest.main()
