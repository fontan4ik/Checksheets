"""Stock accounting scenarios; all data is local and synthetic."""

import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ntc_stock_engine import calculate  # noqa: E402


def fixture():
    return {
        "stock_by_model": {"model": 100},
        "articles": [
            {"offer_id": "model-3", "model": "model", "H": 3},
            {"offer_id": "model-5", "model": "model", "H": 5},
            {"offer_id": "model-10", "model": "model", "H": 10},
        ],
        "postings": [],
        "returns": [],
    }


def posting(status="awaiting_packaging", quantity=1, handed_over=False):
    return {"posting_number": "P-1", "status": status, "ever_handed_over": handed_over,
            "items": [{"offer_id": "model-10", "quantity": quantity}]}


def accepted_return(quantity=1, status="ReceivedBySeller"):
    return {"id": "R-1", "schema": "Fbs", "posting_number": "P-1",
            "product": {"offer_id": "model-10", "quantity": quantity},
            "visual": {"status": {"sys_name": status}}}


class StockEngineTests(unittest.TestCase):
    def test_order_reduces_the_exact_article(self):
        data = fixture()
        self.assertEqual(calculate(data)["L_by_offer"],
                         {"model-3": 6, "model-5": 6, "model-10": 5})
        data["postings"] = [posting()]
        result = calculate(data)
        self.assertEqual(result["L_by_offer"],
                         {"model-3": 6, "model-5": 6, "model-10": 4})
        self.assertEqual(result["unreflected_physical_by_model"], {"model": 10})

    def test_cancel_before_and_after_handover(self):
        data = fixture()
        data["postings"] = [posting("cancelled")]
        self.assertEqual(calculate(data)["L_by_offer"]["model-10"], 5)
        data["postings"] = [posting("cancelled", handed_over=True)]
        self.assertEqual(calculate(data)["L_by_offer"]["model-10"], 4)
        data["returns"] = [accepted_return(status="ArrivedAtReturnPlace")]
        self.assertEqual(calculate(data)["L_by_offer"]["model-10"], 4)
        data["returns"] = [accepted_return()]
        result = calculate(data)
        self.assertEqual(result["L_by_offer"]["model-10"], 4)
        self.assertEqual(result["accepted_return_waiting_for_warehouse_by_offer"], {"model-10": 1})
        data["return_reconciled"] = {"P-1": {"model-10": 1}}
        self.assertEqual(calculate(data)["L_by_offer"]["model-10"], 5)

    def test_unknown_handoff_history_keeps_cancelled_order_reserved(self):
        data = fixture()
        data["postings"] = [posting("cancelled")]
        del data["postings"][0]["ever_handed_over"]
        self.assertEqual(calculate(data)["L_by_offer"]["model-10"], 4)

    def test_warehouse_outbound_and_return_do_not_double_count(self):
        data = fixture()
        data["postings"] = [posting("delivering", handed_over=True)]
        data["stock_by_model"]["model"] = 90
        data["outbound_booked"] = {"P-1": {"model-10": 1}}
        result = calculate(data)
        self.assertEqual(result["unreflected_physical_by_model"], {"model": 0})
        self.assertEqual(sum(result["L_by_offer"][a["offer_id"]] * a["H"] for a in data["articles"]), 90)
        data["postings"] = [posting("cancelled", handed_over=True)]
        data["returns"] = [accepted_return()]
        self.assertEqual(calculate(data)["unreflected_physical_by_model"], {"model": 0})
        data["stock_by_model"]["model"] = 100
        self.assertEqual(calculate(data)["L_by_offer"]["model-10"], 5)

    def test_partial_return_and_manual_k(self):
        data = fixture()
        data["postings"] = [posting("cancelled", quantity=2, handed_over=True)]
        data["returns"] = [accepted_return(quantity=1)]
        data["return_reconciled"] = {"P-1": {"model-10": 1}}
        data["manual_k"] = {"model-5": 2}
        result = calculate(data)
        self.assertEqual(result["unreflected_units_by_offer"]["model-10"], 1)
        self.assertEqual(result["unreflected_units_by_offer"]["model-5"], 2)
        self.assertEqual(result["unreflected_physical_by_model"], {"model": 20})
        self.assertEqual(result["L_by_offer"]["model-10"], 4)
        self.assertEqual(result["L_by_offer"]["model-5"], 4)
        data["manual_booked"] = {"model-5": 2}
        data["stock_by_model"]["model"] = 90
        self.assertEqual(calculate(data)["unreflected_physical_by_model"], {"model": 10})

    def test_large_order_still_respects_shared_physical_cap(self):
        data = fixture()
        data["postings"] = [posting(quantity=6)]
        result = calculate(data)
        self.assertEqual(result["L_by_offer"]["model-10"], 0)
        physical = sum(result["L_by_offer"][a["offer_id"]] * a["H"] for a in data["articles"])
        self.assertLessEqual(physical, 40)

    def test_shared_cap_for_many_stock_and_order_sizes(self):
        data = fixture()
        for stock in range(0, 151):
            data["stock_by_model"]["model"] = stock
            baseline = calculate(data)["L_by_offer"]
            for ordered in range(0, 13):
                data["postings"] = [posting(quantity=ordered)]
                result = calculate(data)
                physical = sum(result["L_by_offer"][a["offer_id"]] * a["H"]
                               for a in data["articles"])
                self.assertLessEqual(physical, max(0, stock - ordered * 10))
                self.assertLessEqual(result["L_by_offer"]["model-10"],
                                     max(0, baseline["model-10"] - ordered))
            data["postings"] = []

    def test_duplicate_return_id_is_not_counted_twice_and_overcredit_fails(self):
        data = fixture()
        data["postings"] = [posting("cancelled", handed_over=True)]
        data["returns"] = [accepted_return(), deepcopy(accepted_return())]
        data["return_reconciled"] = {"P-1": {"model-10": 1}}
        self.assertEqual(calculate(data)["unreflected_physical_by_model"], {"model": 0})
        data["return_reconciled"]["P-1"]["model-10"] = 2
        with self.assertRaisesRegex(ValueError, "inconsistent movement"):
            calculate(data)


if __name__ == "__main__":
    unittest.main()
