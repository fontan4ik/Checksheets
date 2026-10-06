import unittest

from iek_marketplace_mapper import map_ozon, map_wb, build_preview


PRODUCT = {
    "article": "KKME11-012-230-10",
    "name": "Светильник IEK",
    "tm": "IEK",
    "description": "Описание",
    "logisticParamsData": {"singlePackage": {"multiplicity": 1, "unit": "шт"}},
    "imageUrls": ["https://example.test/image.jpg"],
    "etim": {"features": [{"name": "Рабочий ток", "value": "12 А"}]},
    "priceRrc": 715.11,
    "logisticParams": [
        {"nameOrig": "Штрихкод", "value": {"individual": "123"}},
        {"nameOrig": "l_см", "value": {"individual": "7.7", "transport": "44.0"}},
        {"nameOrig": "b_см", "value": {"individual": "4.8", "transport": "27.5"}},
        {"nameOrig": "h_см", "value": {"individual": "8.8", "transport": "21.5"}},
        {"nameOrig": "ВесБрутто", "value": {"individual": "0.36", "transport": "18.0"}},
    ],
}


class MarketplaceMapperTest(unittest.TestCase):
    def test_ozon_requires_explicit_category_mapping(self):
        result = map_ozon(PRODUCT)
        self.assertFalse(result.ready)
        self.assertIn("missing Ozon description_category_id mapping", result.errors)
        self.assertEqual(result.payload["offer_id"], PRODUCT["article"])

    def test_ozon_does_not_treat_supplier_rrc_as_seller_price(self):
        product = {**PRODUCT, "priceRrc": 715.11}
        result = map_ozon(
            product,
            category={"description_category_id": 17028654, "type_id": 99040, "attribute_ids": {"Рабочий ток": 3}},
        )
        self.assertTrue(result.ready)
        self.assertEqual(result.payload["price"], 715.11)
        self.assertEqual(result.payload["barcode"], "123")

    def test_maps_individual_ieks_logistic_package_measurements(self):
        mapped = map_wb(
            PRODUCT,
            category={"subject_id": 123, "characteristic_ids": {"Рабочий ток": 456}},
        )
        dimensions = mapped.payload["variants"][0]["dimensions"]
        self.assertEqual(
            dimensions,
            {"length": 7.7, "width": 4.8, "height": 8.8, "weightBrutto": 0.36},
        )
        self.assertNotEqual(dimensions["length"], 44.0)  # transport packaging excluded

    def test_wb_maps_images_and_characteristics(self):
        result = map_wb(
            PRODUCT,
            category={"subject_id": 123, "characteristic_ids": {"Рабочий ток": 456}},
        )
        self.assertTrue(result.ready)
        variant = result.payload["variants"][0]
        self.assertEqual(variant["vendorCode"], PRODUCT["article"])
        self.assertEqual(variant["photos"]["c246x328"], PRODUCT["imageUrls"])
        self.assertEqual(variant["characteristics"][0]["id"], 456)

    def test_multiplicity_one_does_not_add_suffix(self):
        preview = build_preview(
            PRODUCT,
            ozon={"description_category_id": 1, "type_id": 2, "attribute_ids": {"Рабочий ток": 3}},
            wb={"subject_id": 4, "characteristic_ids": {"Рабочий ток": 5}},
        )
        self.assertEqual(preview["multiplicity"], 1)
        self.assertEqual(preview["article"], PRODUCT["article"])
        self.assertTrue(preview["publishable"])


if __name__ == "__main__":
    unittest.main()
