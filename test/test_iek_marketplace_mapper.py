import unittest
from copy import deepcopy

from iek_marketplace_mapper import map_ozon, map_wb, build_preview


PRODUCT = {
    "article": "KKME11-012-230-10",
    "name": "Контактор IEK",
    "shortName": "Контактор КМИе-11210 12А 230В/АС3 1NO GENERICA",
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
    "seller_price": 715.11,
    "vat": "0.22",
    "logisticParams": [
        {"nameOrig": "Штрихкод", "value": {"individual": "123"}},
        {"nameOrig": "l_см", "value": {"individual": "7.7", "transport": "44.0"}},
        {"nameOrig": "b_см", "value": {"individual": "4.8", "transport": "27.5"}},
        {"nameOrig": "h_см", "value": {"individual": "8.8", "transport": "21.5"}},
        {"nameOrig": "ВесБрутто", "value": {"individual": "0.36", "transport": "18.0"}},
    ],
}


class MarketplaceMapperTest(unittest.TestCase):

    def test_ozon_import_name_prefers_source_russian_title(self):
        product = dict(PRODUCT, name="IEK KMIe contactor", shortName="Контактор КМИе-11210")
        category = {"description_category_id": 17028654, "type_id": 99040, "schema_verified": True,
                    "required_attribute_ids": [8229, 9048, 22232, 85, 23536],
                    "seller_price_source": "iek_priceRrc",
                    "attribute_ids": {"Тип": {"id": 8229, "static_value": "Контактор"},
                                      "Нужен код маркировки": {"id": 23536, "type": "Boolean", "value": True},
                                      "ТН ВЭД коды ЕАЭС": {"id": 22232, "allowed_values": ["8536490000"]}}}
        product["feacn"] = "8536490000"
        product["isMarked"] = True
        result = map_ozon(product, category=category, vat="0.22", product_id=6541499612)
        self.assertEqual(result.payload["name"], "Контактор КМИе-11210")
        self.assertEqual(result.payload["product_id"], 6541499612)
        self.assertIn(4180, {attribute["id"] for attribute in result.payload["attributes"]})
        self.assertTrue(all(isinstance(value["value"], (str, bool)) for attribute in result.payload["attributes"] for value in attribute["values"]))

    def test_ozon_and_wb_apply_explicit_category_attribute_mappings(self):
        mapped = build_preview(
            PRODUCT,
            ozon={
                "description_category_id": 17028654,
                "type_id": 99040,
                "schema_verified": True,
                "vat_source": "ozon_analog_iek_contactors",
                "seller_price_source": "iek_priceRrc",
                "attribute_ids": {
                    "Тип": {"id": 8229, "static_value": "Контактор"},
                    "Нужен код маркировки": {"id": 23536, "type": "Boolean", "value": True},
                },
            },
            wb={"subject_id": 4225, "schema_verified": True, "photo_contract_verified": True, "seller_price_source": "iek_priceRrc", "characteristic_ids": {"Номин рабочий ток Ie при AC-3 400 В": 81589}},
        )
        self.assertTrue(mapped["ozon"]["ready"])
        self.assertEqual(mapped["ozon"]["payload"]["price"], "715.11")
        self.assertEqual(mapped["ozon"]["payload"]["vat"], "0.22")
        self.assertEqual(mapped["ozon"]["payload"]["barcode"], "123")
        self.assertTrue(mapped["wb"]["ready"])
        card = mapped["wb"]["payload"]["variants"][0]
        self.assertEqual(card["dimensions"], {"length": 7.7, "width": 4.8, "height": 8.8, "weightBrutto": 0.36})
        self.assertEqual(card["photos"], PRODUCT["imageUrls"])
        attrs = mapped["ozon"]["payload"]["attributes"]
        self.assertTrue(any(a["id"] == 10823 and a["values"][0]["value"] == "230" for a in attrs))
        self.assertTrue(any(a["id"] == 85 and a["values"][0]["value"] == "IEK" for a in attrs))
        self.assertTrue(any(a["id"] == 8229 and a["values"][0]["value"] == "Контактор" for a in attrs))
        self.assertTrue(any(a["id"] == 23536 and a["values"][0]["value"] is True for a in attrs))
        model = next(a for a in attrs if a["id"] == 9048)
        self.assertEqual(model["values"][0]["value"], PRODUCT["shortName"])

    def test_ozon_model_name_uses_exact_supplier_short_name(self):
        product = deepcopy(PRODUCT)
        product["article"] = "KKME31-040-230-11"
        product["shortName"] = "Контактор КМИе-34012 40А 230В/АС3 1NO;1NC GENERICA"
        result = map_ozon(product, category={
            "description_category_id": 17028654,
            "type_id": 99040,
            "schema_verified": True,
            "required_attribute_ids": [9048],
        })
        model = next(a for a in result.payload["attributes"] if a["id"] == 9048)
        self.assertEqual(model["values"][0]["value"], product["shortName"])

    def test_ozon_requires_explicit_category_mapping(self):
        result = map_ozon(PRODUCT)
        self.assertFalse(result.ready)
        self.assertIn("missing Ozon description_category_id mapping", result.errors)
        self.assertEqual(result.payload["offer_id"], PRODUCT["article"] + "-1")

    def test_supplier_rrc_is_not_seller_price_without_explicit_value(self):
        product = {key: value for key, value in PRODUCT.items() if key != "seller_price"}
        result = map_ozon(product, category={"description_category_id": 17028654, "type_id": 99040})
        self.assertFalse(result.ready)
        self.assertIn("missing explicit seller_price; supplier priceRrc is not a seller-price source", result.errors)
        self.assertNotIn("price", result.payload)
        self.assertEqual(result.payload["vat"], "0.22")

    def test_explicit_rrc_seller_price_policy(self):
        product = {key: value for key, value in PRODUCT.items() if key != "seller_price"}
        product["priceRrc"] = 715.11
        result = map_ozon(product, category={"description_category_id": 17028654, "type_id": 99040, "seller_price_source": "iek_priceRrc"})
        self.assertEqual(result.payload["price"], "715.11")

    def test_missing_vat_is_not_inferred(self):
        product = {key: value for key, value in PRODUCT.items() if key != "vat"}
        result = map_ozon(product, category={"description_category_id": 17028654, "type_id": 99040})
        self.assertFalse(result.ready)
        self.assertIn("missing explicit Ozon VAT rate", result.errors)
        self.assertNotIn("vat", result.payload)

    def test_vat_can_be_bound_explicitly_to_payload(self):
        result = map_ozon(PRODUCT, category={"description_category_id": 17028654, "type_id": 99040, "schema_verified": True, "seller_price_source": "iek_priceRrc"}, vat="0.22")
        self.assertEqual(result.payload["vat"], "0.22")
        self.assertEqual(result.payload["price"], str(PRODUCT["priceRrc"]))

    def test_wb_price_is_omitted_without_explicit_seller_price(self):
        product = {key: value for key, value in PRODUCT.items() if key != "seller_price"}
        result = map_wb(product, category={"subject_id": 4225})
        self.assertFalse(result.ready)
        self.assertNotIn("price", result.payload["variants"][0]["sizes"][0])

    def test_missing_voltage_is_not_inferred_from_article(self):
        product = deepcopy(PRODUCT)
        product["etim"]["features"] = [f for f in product["etim"]["features"] if f["name"] != "Номин напряжение питания цепи управ Us AC 50 Гц"]
        result = map_ozon(product, category={"description_category_id": 17028654, "type_id": 99040, "required_attribute_ids": [10823]})
        self.assertFalse(result.ready)
        self.assertIn("missing required Ozon attributes: 10823", result.errors)
        self.assertNotIn(10823, {a["id"] for a in result.payload["attributes"]})

    def test_required_marking_is_not_invented(self):
        product = {key: value for key, value in PRODUCT.items() if key != "etim"} | {"etim": {"features": PRODUCT["etim"]["features"]}}
        result = map_ozon(product, category={"description_category_id": 17028654, "type_id": 99040, "required_attribute_ids": [23536]})
        self.assertFalse(result.ready)
        self.assertIn("missing required Ozon attributes: 23536", result.errors)

    def test_explicit_false_marking_is_preserved(self):
        product = deepcopy(PRODUCT)
        product["etim"]["features"].append({"name": "Нужен код маркировки", "value": False})
        result = map_ozon(product, category={"description_category_id": 17028654, "type_id": 99040, "schema_verified": True, "vat_source": "ozon_analog_iek_contactors", "required_attribute_ids": [23536]})
        self.assertTrue(result.ready)
        marking = next(a for a in result.payload["attributes"] if a["id"] == 23536)
        self.assertIs(marking["values"][0]["value"], False)

    def test_supplier_false_marking_is_not_overridden_by_default(self):
        self.test_explicit_false_marking_is_preserved()

    def test_brand_metadata_does_not_replace_unmapped_technical_characteristics(self):
        product = deepcopy(PRODUCT)
        product["etim"]["features"] = [{"name": "Unknown technical feature", "value": "x"}]
        result = map_ozon(
            product,
            category={
                "description_category_id": 17028654,
                "type_id": 99040,
                "schema_verified": True,
                "required_attribute_ids": [5776],
            },
        )
        self.assertFalse(result.ready)
        self.assertIn("missing required Ozon attributes: 5776", result.errors)

    def test_maps_individual_ieks_logistic_package_measurements(self):
        result = map_wb(PRODUCT, category={"subject_id": 4225, "characteristic_ids": {"Номин рабочий ток Ie при AC-3 400 В": 81589}})
        dimensions = result.payload["variants"][0]["dimensions"]
        self.assertEqual(dimensions, {"length": 7.7, "width": 4.8, "height": 8.8, "weightBrutto": 0.36})
        self.assertNotEqual(dimensions["length"], 44.0)

    def test_ozon_maps_individual_ieks_package_measurements_to_documented_units(self):
        product = deepcopy(PRODUCT)
        product["logisticParams"] = [
            {"nameOrig": "l_см", "value": {"individual": "7.7", "transport": "44.0"}},
            {"nameOrig": "b_см", "value": {"individual": "4.8", "transport": "27.5"}},
            {"nameOrig": "h_см", "value": {"individual": "8.8", "transport": "21.5"}},
            {"nameOrig": "ВесБрутто", "value": {"individual": "0.36", "transport": "18.0"}},
        ]
        result = map_ozon(product, category={"description_category_id": 17028654, "type_id": 99040}, vat="0.22")
        self.assertEqual((result.payload["depth"], result.payload["width"], result.payload["height"], result.payload["weight"]), (77, 48, 88, 360))
        self.assertEqual((result.payload["dimension_unit"], result.payload["weight_unit"]), ("mm", "g"))

    def test_ozon_converts_explicit_package_units_and_rejects_unknown_units(self):
        product = deepcopy(PRODUCT)
        product["logisticParams"] = []
        product["logisticParamsData"]["singlePackage"].update({"length": "77", "width": "48", "height": "88", "weightBrutto": "360", "dimensionUnit": "mm", "weightUnit": "g"})
        result = map_ozon(product, category={"description_category_id": 1, "type_id": 2})
        self.assertEqual((result.payload["depth"], result.payload["width"], result.payload["height"], result.payload["weight"]), (77, 48, 88, 360))
        product["logisticParamsData"]["singlePackage"]["dimensionUnit"] = "unknown"
        rejected = map_ozon(product, category={"description_category_id": 1, "type_id": 2})
        self.assertNotIn("depth", rejected.payload)
        self.assertIn("missing IEK individual package dimensions/weight with supported units", rejected.errors)

    def test_supplier_barcode_and_dimension_aliases(self):
        product = deepcopy(PRODUCT)
        product.pop("barcode", None)
        product["barcodeValue"] = "4601234567890"
        product["logisticParams"] = [
            {"nameOrig": "Длина упаковки", "value": {"individual": "12.5"}},
            {"nameOrig": "Ширина упаковки", "value": {"individual": "4.2"}},
            {"nameOrig": "Высота упаковки", "value": {"individual": "8.0"}},
            {"nameOrig": "Масса брутто", "value": {"individual": "0.36"}},
        ]
        result = map_wb(product, category={"subject_id": 4225, "schema_verified": True, "characteristic_ids": {"Баркод": 14177453}})
        self.assertEqual(result.payload["variants"][0]["dimensions"], {"length": 12.5, "width": 4.2, "height": 8, "weightBrutto": 0.36})
        self.assertEqual(result.payload["variants"][0]["sizes"][0]["skus"], ["4601234567890"])

    def test_wb_maps_images_and_characteristics(self):
        result = map_wb(PRODUCT, category={"subject_id": 4225, "schema_verified": True, "photo_contract_verified": True})
        self.assertTrue(result.ready)
        variant = result.payload["variants"][0]
        self.assertEqual(variant["vendorCode"], PRODUCT["article"] + "-1")
        self.assertEqual(variant["photos"], PRODUCT["imageUrls"])
        self.assertEqual(variant["characteristics"][0]["id"], 81589)
        attrs = {attribute["id"]: attribute["value"] for attribute in variant["characteristics"]}
        self.assertEqual(attrs[88953], [0.36])
        self.assertEqual(attrs[90630], [8.8])
        self.assertEqual(attrs[90652], [7.7])
        self.assertEqual(attrs[90673], [4.8])
        self.assertEqual(attrs[90745], [4.8])
        self.assertEqual(attrs[90846], [8.8])
        self.assertEqual(attrs[90849], [7.7])
        self.assertNotIn(14177446, attrs)

    def test_wb_fails_closed_without_verified_photo_contract(self):
        result = map_wb(PRODUCT, category={"subject_id": 4225, "schema_verified": True})
        self.assertFalse(result.ready)
        self.assertIn("WB photo/media submission contract has not been verified", result.errors)

    def test_multiplicity_one_appends_suffix_to_listing_articles(self):
        preview = build_preview(PRODUCT, ozon={"description_category_id": 1, "type_id": 2, "schema_verified": True, "vat_source": "ozon_analog_iek_contactors", "seller_price_source": "iek_priceRrc", "attribute_ids": {"Рабочий ток": 3}}, wb={"subject_id": 4225, "schema_verified": True, "photo_contract_verified": True, "seller_price_source": "iek_priceRrc", "characteristic_ids": {"Номин рабочий ток Ie при AC-3 400 В": 81589}})
        self.assertEqual(preview["multiplicity"], 1)
        self.assertEqual(preview["sourceArticle"], PRODUCT["article"])
        self.assertEqual(preview["article"], PRODUCT["article"] + "-1")
        self.assertEqual(preview["ozon"]["payload"]["offer_id"], PRODUCT["article"] + "-1")
        self.assertEqual(preview["wb"]["payload"]["variants"][0]["vendorCode"], PRODUCT["article"] + "-1")
        self.assertTrue(preview["publishable"])
        self.assertEqual(preview["ozon"]["payload"]["price"], str(PRODUCT["seller_price"]))
        self.assertEqual(preview["ozon"]["payload"]["vat"], PRODUCT["vat"])

    def test_multiplicity_suffix_is_not_duplicated(self):
        product = {**PRODUCT, "article": PRODUCT["article"] + "-1"}
        preview = build_preview(product, ozon={"description_category_id": 1, "type_id": 2, "attribute_ids": {"Рабочий ток": 3}}, wb={"subject_id": 4225, "characteristic_ids": {"Номин рабочий ток Ie при AC-3 400 В": 81589}})
        self.assertEqual(preview["article"], product["article"])
        self.assertEqual(preview["ozon"]["payload"]["offer_id"], product["article"])


if __name__ == "__main__":
    unittest.main()
