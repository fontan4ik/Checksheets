import unittest
from copy import deepcopy

from iek_marketplace_mapper import map_ozon, map_wb, build_preview


PRODUCT = {
    "article": "KKME11-012-230-10",
    "name": "Контактор IEK",
    "tm": "IEK",
    "description": "Описание",
    "logisticParamsData": {"singlePackage": {"multiplicity": 1, "unit": "шт"}},
    "imageUrls": ["https://example.test/image.jpg"],
    "etim": {"features": [
        {"name": "Номин рабочий ток Ie при AC-3 400 В", "value": "12", "unit": "А"},
        {"name": "Номин напряжение питания цепи управ Us AC 50 Гц", "value": "230", "unit": "В"},
        {"name": "Степень защиты - IP", "value": "IP20"},
        {"name": "Тип напряжения управления", "value": "Переменный (AC)"},
        {"name": "Кол-во вспомогат норм разомкнутых-НО конт", "value": "1"},
    ]},
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
    def test_ozon_and_wb_apply_explicit_category_attribute_mappings(self):
        ozon = build_preview(
            PRODUCT,
            ozon={
                "description_category_id": 17028654,
                "type_id": 99040,
                "attribute_ids": {
                    "Тип": {"id": 8229, "static_value": "Контактор"},
                    "Нужен код маркировки": {"id": 23536, "type": "Boolean", "value": True},
                },
            },
            wb={"subject_id": 4225},
        )
        self.assertTrue(ozon["ozon"]["ready"])
        self.assertEqual(ozon["ozon"]["payload"]["price"], 715.11)
        self.assertEqual(ozon["ozon"]["payload"]["barcode"], "123")
        self.assertTrue(ozon["wb"]["ready"])
        card = ozon["wb"]["payload"]["variants"][0]
        self.assertEqual(card["dimensions"], {"length": 7.7, "width": 4.8, "height": 8.8, "weightBrutto": 0.36})
        ozon_attrs = ozon["ozon"]["payload"]["attributes"]
        self.assertTrue(any(a["id"] == 10823 and a["values"][0]["value"] == "230" for a in ozon_attrs))
        self.assertTrue(any(a["id"] == 85 and a["values"][0]["value"] == "IEK" for a in ozon_attrs))
        self.assertTrue(any(a["id"] == 8229 and a["values"][0]["value"] == "Контактор" for a in ozon_attrs))
        self.assertTrue(any(a["id"] == 23536 and a["values"][0]["value"] is True for a in ozon_attrs))

    def test_ozon_requires_explicit_category_mapping(self):
        result = map_ozon(PRODUCT)
        self.assertFalse(result.ready)
        self.assertIn("missing Ozon description_category_id mapping", result.errors)
        self.assertEqual(result.payload["offer_id"], PRODUCT["article"] + "-1")

    def test_ozon_uses_supplier_rrc_as_authorized_seller_price(self):
        product = {**PRODUCT, "priceRrc": 715.11}
        result = map_ozon(
            product,
            category={"description_category_id": 17028654, "type_id": 99040, "attribute_ids": {"Рабочий ток": 3}},
        )
        self.assertTrue(result.ready)
        self.assertEqual(result.payload["price"], 715.11)
        self.assertEqual(result.payload["barcode"], "123")

    def test_missing_voltage_is_not_inferred_from_article(self):
        product = deepcopy(PRODUCT)
        product["etim"]["features"] = [
            feature for feature in product["etim"]["features"]
            if feature["name"] != "Номин напряжение питания цепи управ Us AC 50 Гц"
        ]
        result = map_ozon(product, category={
            "description_category_id": 17028654,
            "type_id": 99040,
            "required_attribute_ids": [10823],
        })
        self.assertFalse(result.ready)
        self.assertIn("missing required Ozon attributes: 10823", result.errors)
        self.assertNotIn(10823, {attribute["id"] for attribute in result.payload["attributes"]})

    def test_required_marking_is_not_invented(self):
        result = map_ozon(PRODUCT, category={
            "description_category_id": 17028654,
            "type_id": 99040,
            "required_attribute_ids": [23536],
        })
        self.assertFalse(result.ready)
        self.assertIn("missing required Ozon attributes: 23536", result.errors)
        self.assertNotIn(23536, {attribute["id"] for attribute in result.payload["attributes"]})

    def test_brand_metadata_does_not_replace_unmapped_technical_characteristics(self):
        product = deepcopy(PRODUCT)
        product["etim"]["features"] = [{"name": "Unknown technical feature", "value": "x"}]
        result = map_ozon(product, category={
            "description_category_id": 17028654,
            "type_id": 99040,
        })
        self.assertFalse(result.ready)
        self.assertIn("no required Ozon characteristics mapped", result.errors)

    def test_explicit_false_marking_is_preserved(self):
        result = map_ozon(PRODUCT, category={
            "description_category_id": 17028654,
            "type_id": 99040,
            "required_attribute_ids": [23536],
            "attribute_ids": {
                "Нужен код маркировки": {"id": 23536, "type": "Boolean", "value": False},
            },
        })
        self.assertTrue(result.ready)
        marking = next(attribute for attribute in result.payload["attributes"] if attribute["id"] == 23536)
        self.assertIs(marking["values"][0]["value"], False)

    def test_supplier_false_marking_is_not_overridden_by_default(self):
        product = deepcopy(PRODUCT)
        product["etim"]["features"].append({"name": "Нужен код маркировки", "value": False})
        result = map_ozon(product, category={
            "description_category_id": 17028654,
            "type_id": 99040,
            "required_attribute_ids": [23536],
        })
        self.assertTrue(result.ready)
        marking = next(attribute for attribute in result.payload["attributes"] if attribute["id"] == 23536)
        self.assertIs(marking["values"][0]["value"], False)

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
        self.assertEqual(variant["vendorCode"], PRODUCT["article"] + "-1")
        self.assertEqual(variant["photos"]["c246x328"], PRODUCT["imageUrls"])
        self.assertEqual(variant["characteristics"][0]["id"], 81589)

    def test_multiplicity_one_appends_suffix_to_listing_articles(self):
        preview = build_preview(
            PRODUCT,
            ozon={"description_category_id": 1, "type_id": 2, "attribute_ids": {"Рабочий ток": 3}},
            wb={"subject_id": 4, "characteristic_ids": {"Рабочий ток": 5}},
        )
        self.assertEqual(preview["multiplicity"], 1)
        self.assertEqual(preview["sourceArticle"], PRODUCT["article"])
        self.assertEqual(preview["article"], PRODUCT["article"] + "-1")
        self.assertEqual(preview["ozon"]["payload"]["offer_id"], PRODUCT["article"] + "-1")
        self.assertEqual(preview["wb"]["payload"]["variants"][0]["vendorCode"], PRODUCT["article"] + "-1")
        self.assertTrue(preview["publishable"])
        self.assertEqual(preview["ozon"]["payload"]["price"], PRODUCT["priceRrc"])
        self.assertEqual(preview["ozon"]["payload"]["barcode"], "123")

    def test_multiplicity_suffix_is_not_duplicated(self):
        product = {**PRODUCT, "article": PRODUCT["article"] + "-1"}
        preview = build_preview(
            product,
            ozon={"description_category_id": 1, "type_id": 2, "attribute_ids": {"Рабочий ток": 3}},
            wb={"subject_id": 4, "characteristic_ids": {"Рабочий ток": 5}},
        )
        self.assertEqual(preview["article"], product["article"])
        self.assertEqual(preview["ozon"]["payload"]["offer_id"], product["article"])


if __name__ == "__main__":
    unittest.main()
