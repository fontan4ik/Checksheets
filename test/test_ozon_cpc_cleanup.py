import io
import pathlib
import sys
import unittest
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ozon_cpc_cleanup import (
    Metric,
    SheetRow,
    build_statistics_payload,
    build_candidates,
    campaign_budget,
    current_day_period,
    parse_report,
    parse_report_block,
    write_sheet_metrics,
)


class OzonCpcCleanupTests(unittest.TestCase):
    def test_current_day_period_uses_moscow_date(self):
        start, end = current_day_period()
        self.assertTrue(start.endswith("T00:00:00+03:00"))
        self.assertTrue(end.endswith("T23:59:59+03:00"))
        self.assertEqual(start[:10], end[:10])

    def test_statistics_payload_uses_documented_rfc3339_fields_and_date_grouping(self):
        payload = build_statistics_payload(
            ["33230388"],
            "2026-08-04T00:00:00+03:00",
            "2026-08-04T23:59:59+03:00",
        )
        self.assertEqual(payload["campaigns"], ["33230388"])
        self.assertEqual(payload["from"], "2026-08-04T00:00:00+03:00")
        self.assertEqual(payload["to"], "2026-08-04T23:59:59+03:00")
        self.assertEqual(payload["groupBy"], "DATE")
        self.assertNotIn("dateFrom", payload)
        self.assertNotIn("dateTo", payload)
        with self.assertRaises(ValueError):
            build_statistics_payload(["33230388"], "from", "to", "SKU")

    def test_parse_report_block_maps_clicks_and_metrics_by_header(self):
        csv_text = (
            ";Кампания 33230388\n"
            "sku;Показы;Клики;CTR, %;Расход, ₽, с НДС;Средняя стоимость клика, ₽;Продано товаров;Добавления в корзину\n"
            "986315608;100;12;12;123,45;10,29;2;4\n"
            "986315608;50;3;6;30;10;1;2\n"
        )
        block = parse_report_block("33230388_24.07.2026.csv", csv_text)
        self.assertEqual(block.campaign_id, "33230388")
        self.assertEqual(block.metrics["986315608"].clicks, 15)
        self.assertEqual(block.metrics["986315608"].impressions, 150)
        self.assertAlmostEqual(block.metrics["986315608"].spend, 153.45)
        self.assertEqual(block.metrics["986315608"].sold, 3)
        self.assertEqual(block.metrics["986315608"].carts, 6)

    def test_parse_report_reads_zip_and_keeps_campaign_sku_key(self):
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            archive.writestr(
                "33230388_24.07.2026.csv",
                "sku;Клики\n986315608;11\n",
            )
        stats = parse_report(content.getvalue(), ["33230388"])
        self.assertEqual(stats[("33230388", "986315608")].clicks, 11)

    def test_campaign_budget_uses_explicit_budget_not_weekly_cap(self):
        self.assertEqual(campaign_budget({"budget": "1500", "dailyBudget": "0", "weeklyBudget": "2000000000"}), 1500)
        self.assertEqual(campaign_budget({"budget": "0", "dailyBudget": "250"}), 0)
        self.assertEqual(campaign_budget(None), 0)

    def test_write_sheet_metrics_translates_all_empty_cpc_columns(self):
        class FakeWorksheet:
            def __init__(self):
                self.updates = []

            def update(self, range_label, values):
                self.updates.append((range_label, values))

        headers = [
            "art", "model", "brand", "pic", "SKU OZON", "CAMPAIN ID", "Расход", "Показы",
            "Клики", "CTR, %", "Средняя стоимость клика", "Продано", "ДРР в продвижении", "Бюджет",
            "Корзины", "Статус",
        ]
        row = SheetRow(2, "39171-1", "986315608", "33230388", ["39171-1", "39171", "Stekker", "", "986315608", "33230388"] + [""] * 10)
        metric = Metric(clicks=12, impressions=100, ctr=12, spend=123.45, average_cpc=10.29, sold=2, drr=4, carts=3)
        worksheet = FakeWorksheet()

        write_sheet_metrics(
            worksheet,
            headers,
            [row],
            {("33230388", "986315608"): metric},
            {"33230388": {"budget": "1500", "state": "CAMPAIGN_STATE_RUNNING"}},
        )

        updates = dict(worksheet.updates)
        self.assertEqual(set(updates), {"G2:G2", "H2:H2", "I2:I2", "J2:J2", "K2:K2", "L2:L2", "M2:M2", "N2:N2", "O2:O2", "P2:P2"})
        self.assertEqual(updates["G2:G2"], [[123.45]])
        self.assertEqual(updates["N2:N2"], [[1500]])
        self.assertEqual(updates["P2:P2"], [["CAMPAIGN_STATE_RUNNING"]])
        self.assertNotIn("A2:P2", updates)

    def test_build_candidates_requires_sku_still_in_campaign(self):
        rows = [
            SheetRow(2, "39171-1", "986315608", "33230388", []),
            SheetRow(3, "other", "123", "33230388", []),
        ]
        metrics = {
            ("33230388", "986315608"): Metric(clicks=10),
            ("33230388", "123"): Metric(clicks=12),
        }
        candidates = build_candidates(rows, metrics, {"33230388": {"986315608"}}, 10)
        self.assertEqual(
            {(item.sku, item.action) for item in candidates},
            {("986315608", "delete"), ("123", "skip_not_in_campaign")},
        )


if __name__ == "__main__":
    unittest.main()
