"""Regression coverage for the IEK per-package logistics shape returned by the supplier API."""
import unittest

from iek_marketplace_mapper import map_ozon


PRODUCTS = [
    ("KKME11-012-230-10", "715.11", "7.7000", "4.8000", "8.8000", "0.3600000", (77, 48, 88, 360)),
    ("KKME11-018-230-10", "808.61", "7.7000", "4.8000", "8.8000", "0.3760000", (77, 48, 88, 376)),
    ("KKME11-009-230-10", "645.36", "7.7000", "4.8000", "8.8000", "0.3600000", (77, 48, 88, 360)),
    ("KKME21-025-110-10", "1390.64", "8.5000", "5.8000", "10.0000", "0.5380000", (85, 58, 100, 538)),
    ("KKME31-040-230-11", "2756.18", "12.8000", "8.1000", "12.0000", "1.2400000", (128, 81, 120, 1240)),
]

CATEGORY = {
    "description_category_id": 17028654,
    "type_id": 99040,
    "schema_verified": True,
    "seller_price_source": "iek_priceRrc",
    "required_attribute_ids": [8229, 9048, 22232, 85, 23536],
    "attribute_ids": {
        "Тип": {"id": 8229, "static_value": "Контактор"},
        "Название модели (для объединения в одну карточку)": {"id": 9048},
        "ТН ВЭД коды ЕАЭС": {"id": 22232, "allowed_values": ["8536490000"]},
        "Бренд": {"id": 85, "allowed_values": ["IEK"]},
        "Нужен код маркировки": {"id": 23536, "type": "Boolean", "value": True},
    },
}


def supplier_record(row):
    article, price, length, width, height, weight, _ = row
    return {
        "article": article,
        "name": "Контактор IEK",
        "shortName": f"Контактор {article}",
        "tm": "IEK",
        "description": "supplier record",
        "priceRrc": float(price),
        "barcode": "4601234567890",
        "imageUrls": ["https://example.invalid/iek.jpg"],
        "multiplicity": 1,
        "feacn": "8536490000",
        "isMarked": True,
        "logisticParamsData": {"singlePackage": {"multiplicity": 1, "unit": "шт"}},
        "logisticParams": [
            {"nameOrig": "l_см", "unit": None, "value": {"individual": length, "transport": "44.0000"}},
            {"nameOrig": "b_см", "unit": None, "value": {"individual": width, "transport": "27.5000"}},
            {"nameOrig": "h_см", "unit": None, "value": {"individual": height, "transport": "21.5000"}},
            {"nameOrig": "ВесБрутто", "unit": None, "value": {"individual": weight, "transport": "18.0000"}},
        ],
    }


class LivePackageMappingTest(unittest.TestCase):
    def test_five_supplier_shapes_map_per_item_values_to_ozon_units(self):
        for row in PRODUCTS:
            with self.subTest(article=row[0]):
                product = supplier_record(row)
                result = map_ozon(product, category=CATEGORY, vat="0.22")
                self.assertEqual(result.article, row[0] + "-1")
                self.assertEqual(result.errors, [])
                item = result.payload
                self.assertEqual((item["depth"], item["width"], item["height"], item["weight"]), row[6])
                self.assertEqual((item["dimension_unit"], item["weight_unit"]), ("mm", "g"))
                self.assertEqual(item["vat"], "0.22")
                self.assertEqual(item["price"], float(row[1]))
                self.assertEqual(item["images"], product["imageUrls"])
                self.assertEqual({a["id"] for a in item["attributes"]} & set(CATEGORY["required_attribute_ids"],), set(CATEGORY["required_attribute_ids"]))

    def test_unknown_units_and_transport_only_values_never_produce_ready_dimensions(self):
        product = supplier_record(PRODUCTS[0])
        for record in product["logisticParams"]:
            record["value"].pop("individual")
        result = map_ozon(product, category=CATEGORY, vat="0.22")
        self.assertFalse(result.ready)
        self.assertNotIn("depth", result.payload)
        product = supplier_record(PRODUCTS[0])
        for record in product["logisticParams"]:
            record["unit"] = "unknown"
        # The IEK aliases explicitly encode cm/kg; this unknown metadata must not override that source contract.
        result = map_ozon(product, category=CATEGORY, vat="0.22")
        self.assertTrue(result.ready)


if __name__ == "__main__":
    unittest.main()
