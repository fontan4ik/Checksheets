import sys
from pathlib import Path
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rs_sync_local


class Response:
    status_code = 200

    def __init__(self, items, pages, rows):
        self._data = {"items": items, "meta": {"last_page": pages, "rows_count": rows}}

    def json(self):
        return self._data


def items_for(start, count, stale_last=False):
    items = [
        {"CODE": f"c{index}", "VENDOR_CODE": f"v{index}", "ARTICLE": f"a{index}"}
        for index in range(start, start + count)
    ]
    if stale_last:
        items[-1] = {"CODE": "stale", "VENDOR_CODE": "stale-only", "ARTICLE": "stale-only"}
    return items


class RsCatalogSnapshotRetryTests(unittest.TestCase):
    def test_restarts_changed_category_and_discards_partial_attempt(self):
        responses = iter([
            Response(items_for(0, 1000, stale_last=True), pages=2, rows=1001),
            Response(items_for(1000, 1), pages=2, rows=1002),
            Response(items_for(0, 1000), pages=2, rows=1001),
            Response(items_for(1000, 1), pages=2, rows=1001),
        ])

        with (
            patch.object(rs_sync_local, "create_rs_session", return_value=object()),
            patch.object(rs_sync_local, "get_rs_headers", return_value={}),
            patch.object(rs_sync_local, "rs_get_with_retry", side_effect=lambda *args, **kwargs: next(responses)),
            patch.object(rs_sync_local.time, "sleep"),
        ):
            result = rs_sync_local.fetch_rs_code_map(287)

        self.assertIn("v1000", result)
        self.assertNotIn("stale-only", result)


if __name__ == "__main__":
    unittest.main()
