"""Disposable Google Sheets test of the local F-stage state machine.

Creates one temporary tab in the existing workbook, exercises F updates, and
deletes the tab in finally. Never touches «НТЦ списания» or marketplace APIs.
"""

import sys
import uuid
from pathlib import Path

import gspread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ntc_f_stage import advance  # noqa: E402


SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI"


def payload(f, status, handed_over=False, returns=None, manual=0):
    return {"stock_by_model": {"M": f},
            "articles": [{"offer_id": "M-5", "model": "M", "H": 5}],
            "postings": [{"posting_number": "TEST-1", "status": status,
                          "ever_handed_over": handed_over,
                          "items": [{"offer_id": "M-5", "quantity": 2}]}],
            "returns": returns or [], "manual_k": {"M-5": manual}}


def accepted_return():
    return {"id": "RETURN-1", "schema": "Fbs", "posting_number": "TEST-1",
            "product": {"offer_id": "M-5", "quantity": 1},
            "visual": {"status": {"sys_name": "ReceivedBySeller"}}}


def main():
    client = gspread.service_account(filename=str(ROOT / "nomadic-bedrock-485314-b0-d7624dedd83c.json"))
    book = client.open_by_key(SPREADSHEET_ID)
    tab = book.add_worksheet(title="_TEST_NTC_F_" + uuid.uuid4().hex[:8], rows=8, cols=4)
    try:
        tab.update("A1:C2", [["Модель", "F физические штуки", "L упаковки"], ["M", 100, 20]])
        stock = int(tab.acell("B2").value)
        first = advance(payload(stock, "awaiting_packaging"))
        tab.update("B2:C2", [[first["F_by_model"]["M"], first["L_by_offer"]["M-5"]]])
        assert [int(v) for v in tab.row_values(2)[1:3]] == [90, 18]

        stock = int(tab.acell("B2").value)
        repeat = advance(payload(stock, "awaiting_packaging"), first["state"])
        assert repeat["delta_physical_by_model"]["M"] == 0

        cancelled = advance(payload(stock, "cancelled"), repeat["state"])
        tab.update("B2:C2", [[cancelled["F_by_model"]["M"], cancelled["L_by_offer"]["M-5"]]])
        assert [int(v) for v in tab.row_values(2)[1:3]] == [100, 20]

        sent = advance(payload(100, "delivering", handed_over=True), cancelled["state"])
        tab.update("B2:C2", [[sent["F_by_model"]["M"], sent["L_by_offer"]["M-5"]]])
        assert [int(v) for v in tab.row_values(2)[1:3]] == [90, 18]
        late_cancel = advance(payload(90, "cancelled", handed_over=True), sent["state"])
        assert late_cancel["F_by_model"]["M"] == 90

        partial = advance(payload(90, "cancelled", handed_over=True,
                                  returns=[accepted_return()]), late_cancel["state"])
        tab.update("B2:C2", [[partial["F_by_model"]["M"], partial["L_by_offer"]["M-5"]]])
        assert [int(v) for v in tab.row_values(2)[1:3]] == [95, 19]
        print("Google scratch NTC F-stage: order 100→90, early cancel 90→100, "
              "late cancel stays 90, accepted partial return 90→95; passed")
    finally:
        book.del_worksheet(tab)


if __name__ == "__main__":
    main()
