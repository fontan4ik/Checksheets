import io
import pathlib
import sys
import unittest
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ozon_cpc_cleanup import (
    Metric,
    SheetRow,
    build_candidates,
    current_day_period,
    parse_report,
    parse_report_block,
)


class OzonCpcCleanupTests(unittest.TestCase):
    def test_current_day_period_uses_moscow_date(self):
        start, end = current_day_period()
        self.assertTrue(start.endswith("T00:00:00+03:00"))
        self.assertTrue(end.endswith("T23:59:59+03:00"))
        self.assertEqual(start[:10], end[:10])

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
