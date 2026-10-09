import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rs_sync_local as rs


class MissingStockTests(unittest.TestCase):
    def test_missing_residue_clears_cell_but_explicit_zero_is_preserved(self):
        models = ["positive", "zero", "missing", "invalid", "unmatched", ""]
        catalog = {name: name for name in models[:4]}
        samara = rs.RSStockSnapshot()
        samara.update({"positive": 12, "zero": 0})
        moscow = rs.RSStockSnapshot()
        moscow.update({"positive": 7, "zero": 0})
        samara.invalid_codes.add("invalid")
        moscow.invalid_codes.add("invalid")
        worksheet = Mock()
        worksheet.col_values.return_value = ["Артикул производителя", *models]

        with (
            patch.object(rs.gsheets_utils, "get_worksheet", return_value=worksheet),
            patch.object(rs.gsheets_utils, "get_header_columns", return_value={"model": 2}),
            patch.object(rs, "fetch_rs_code_map", side_effect=[catalog, catalog]),
            patch.object(rs, "fetch_all_rs_stocks", side_effect=[samara, moscow]),
            patch.object(rs.gsheets_utils, "update_column_by_header_masked", return_value=3) as write,
        ):
            rs.sync_rs()

        self.assertEqual(write.call_count, 2)
        for call, positive in zip(write.call_args_list, (12, 7)):
            self.assertEqual(call.args[2], [[positive], [0], [""], [""], [""], [""]])
            # Missing stock actively clears the old cell. Invalid and unmatched
            # products retain their existing cells through the write mask.
            self.assertEqual(call.args[3], [True, True, True, False, False, False])


if __name__ == "__main__":
    unittest.main()
