import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import feron_sync_local as feron


class MissingStockTests(unittest.TestCase):
    def test_missing_product_or_warehouse_writes_zero(self):
        warehouses = list(feron.FERON_WAREHOUSE_IDS.values())
        stocks = {
            "positive": {warehouse: 8 for warehouse in warehouses},
            "zero": {warehouse: 0 for warehouse in warehouses},
            "partial": {warehouses[0]: 3},
        }
        worksheet = Mock()
        worksheet.col_values.return_value = [
            "Артикул производителя", "positive", "zero", "partial", "missing", ""
        ]
        with (
            patch.object(feron, "get_feron_session", return_value="mock"),
            patch.object(feron, "fetch_all_feron_data", return_value=stocks),
            patch.object(feron.gsheets_utils, "get_worksheet", return_value=worksheet),
            patch.object(feron.gsheets_utils, "get_header_columns", return_value={"model": 2}),
            patch.object(feron.gsheets_utils, "update_column_by_header_masked", return_value=4) as write,
        ):
            feron.sync_feron()
        self.assertEqual(write.call_count, 4)
        for index, call in enumerate(write.call_args_list):
            self.assertEqual(call.args[2], [[8], [0], [3 if index == 0 else 0], [0], [""]])
            self.assertEqual(call.args[3], [True, True, True, True, False])


if __name__ == "__main__":
    unittest.main()
