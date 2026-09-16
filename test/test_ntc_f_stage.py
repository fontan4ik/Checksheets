"""Local scenarios for direct F accounting; never contacts the sheet or Ozon."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ntc_f_stage import advance  # noqa: E402


def snapshot(stock=100, status=None, quantity=1, handed_over=False, manual=0, returns=None):
    data = {
        "stock_by_model": {"M": stock},
        "articles": [
            {"offer_id": "M-3", "model": "M", "H": 3},
            {"offer_id": "M-5", "model": "M", "H": 5},
            {"offer_id": "M-10", "model": "M", "H": 10},
        ],
        "postings": [], "returns": returns or [], "manual_k": {"M-5": manual},
    }
    if status:
        data["postings"] = [{"posting_number": "P", "status": status,
                             "ever_handed_over": handed_over,
                             "items": [{"offer_id": "M-10", "quantity": quantity}]}]
    return data


def accepted_return(quantity=1, status="ReceivedBySeller", return_id="R"):
    return {"id": return_id, "schema": "Fbs", "posting_number": "P",
            "product": {"offer_id": "M-10", "quantity": quantity},
            "visual": {"status": {"sys_name": status}}}


class FStageTests(unittest.TestCase):
    def test_order_debits_f_and_exact_article_once(self):
        first = advance(snapshot(status="awaiting_packaging"))
        self.assertEqual(first["F_by_model"], {"M": 90})
        self.assertEqual(first["L_by_offer"], {"M-3": 6, "M-5": 6, "M-10": 4})
        repeated = advance(snapshot(stock=90, status="awaiting_packaging"), first["state"])
        self.assertEqual(repeated["delta_physical_by_model"], {"M": 0})
        self.assertEqual(repeated["F_by_model"], {"M": 90})

    def test_cancel_before_handover_restores_f_once(self):
        first = advance(snapshot(status="awaiting_packaging"))
        cancelled = advance(snapshot(stock=90, status="cancelled"), first["state"])
        self.assertEqual(cancelled["delta_physical_by_model"], {"M": -10})
        self.assertEqual(cancelled["F_by_model"], {"M": 100})
        self.assertEqual(cancelled["L_by_offer"], {"M-3": 6, "M-5": 6, "M-10": 5})
        repeated = advance(snapshot(stock=100, status="cancelled"), cancelled["state"])
        self.assertEqual(repeated["delta_physical_by_model"], {"M": 0})

    def test_cancel_after_handover_waits_for_accepted_return(self):
        first = advance(snapshot(status="delivering", handed_over=True))
        cancelled = advance(snapshot(stock=90, status="cancelled", handed_over=True), first["state"])
        self.assertEqual(cancelled["F_by_model"], {"M": 90})
        in_transit = advance(snapshot(stock=90, returns=[accepted_return(status="ArrivedAtReturnPlace")]),
                             cancelled["state"])
        self.assertEqual(in_transit["F_by_model"], {"M": 90})
        received = advance(snapshot(stock=90, returns=[accepted_return()]), in_transit["state"])
        self.assertEqual(received["F_by_model"], {"M": 100})
        replay = advance(snapshot(stock=100, returns=[accepted_return()]), received["state"])
        self.assertEqual(replay["F_by_model"], {"M": 100})

    def test_partial_return_and_manual_k(self):
        first = advance(snapshot(status="delivering", quantity=2, handed_over=True, manual=2))
        self.assertEqual(first["F_by_model"], {"M": 70})
        self.assertEqual(first["applied_units_by_offer"], {"M-10": 2, "M-5": 2})
        returned = advance(snapshot(stock=70, manual=2, returns=[accepted_return()]), first["state"])
        self.assertEqual(returned["F_by_model"], {"M": 80})
        self.assertEqual(returned["applied_units_by_offer"], {"M-10": 1, "M-5": 2})
        self.assertLessEqual(sum(returned["L_by_offer"][a["offer_id"]] * a["H"]
                                 for a in snapshot()["articles"]), 80)

    def test_manual_k_changes_apply_only_the_difference(self):
        first = advance(snapshot(manual=2))
        self.assertEqual(first["F_by_model"], {"M": 90})
        repeated = advance(snapshot(stock=90, manual=2), first["state"])
        self.assertEqual(repeated["delta_physical_by_model"], {"M": 0})
        increased = advance(snapshot(stock=90, manual=3), repeated["state"])
        self.assertEqual(increased["F_by_model"], {"M": 85})
        reduced = advance(snapshot(stock=85, manual=1), increased["state"])
        self.assertEqual(reduced["F_by_model"], {"M": 95})

    def test_partial_cancellation_before_handover_returns_difference(self):
        first = advance(snapshot(status="awaiting_packaging", quantity=2))
        self.assertEqual(first["F_by_model"], {"M": 80})
        partial = advance(snapshot(stock=80, status="awaiting_packaging", quantity=1), first["state"])
        self.assertEqual(partial["F_by_model"], {"M": 90})

    def test_external_f_change_is_rejected(self):
        first = advance(snapshot(status="awaiting_packaging"))
        with self.assertRaisesRegex(ValueError, "F changed outside"):
            advance(snapshot(stock=100), first["state"])

    def test_debit_over_f_is_rejected_without_mutation(self):
        first = advance(snapshot(stock=5))
        with self.assertRaisesRegex(ValueError, "exceeds F"):
            advance(snapshot(stock=5, status="awaiting_packaging"), first["state"])
        self.assertEqual(first["state"]["last_f_by_model"], {"M": 5})

    def test_unknown_handoff_on_cancelled_order_is_conservative(self):
        data = snapshot(status="cancelled")
        del data["postings"][0]["ever_handed_over"]
        self.assertEqual(advance(data)["F_by_model"], {"M": 90})


if __name__ == "__main__":
    unittest.main()
