import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ntc_fbs_reserve_sync import reconcile


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.articles = {"a-5": ("a", 5)}

    def posting(self, status, quantity=2, number="1"):
        return {"posting_number": number, "status": status,
                "in_process_at": "2026-09-15T00:00:00Z",
                "products": [{"offer_id": "a-5", "quantity": quantity}]}

    def test_repeat_and_pre_shipment_cancellation(self):
        first, reserve = reconcile({}, [self.posting("awaiting_packaging")], self.articles, self.start)
        self.assertEqual(reserve, {"a": 10})
        second, reserve = reconcile(first, [self.posting("awaiting_packaging")], self.articles, self.start)
        self.assertEqual(reserve, {"a": 10})
        _, reserve = reconcile(second, [self.posting("cancelled")], self.articles, self.start)
        self.assertEqual(reserve, {})

    def test_post_shipment_cancellation_keeps_reserve(self):
        first, _ = reconcile({}, [self.posting("delivering")], self.articles, self.start)
        _, reserve = reconcile(first, [self.posting("cancelled")], self.articles, self.start)
        self.assertEqual(reserve, {"a": 10})

    def test_unlisted_offer_ignored(self):
        posting = self.posting("awaiting_packaging")
        posting["products"][0]["offer_id"] = "other"
        ledger, reserve = reconcile({}, [posting], self.articles, self.start)
        self.assertEqual(ledger, {})
        self.assertEqual(reserve, {})

    def test_invalid_quantity_fails(self):
        with self.assertRaises(ValueError):
            reconcile({}, [self.posting("awaiting_packaging", -1)], self.articles, self.start)


if __name__ == "__main__":
    unittest.main()
