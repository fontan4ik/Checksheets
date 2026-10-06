"""Deterministic IEK-to-marketplace card mapping and validation.

The module never calls WB/Ozon and never publishes cards. It converts an IEK
product response into reviewable dry-run payloads. Marketplace-specific IDs
and commercial fields are explicit inputs because they cannot be inferred
safely from an IEK catalog response.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass
class MappingResult:
    article: str
    payload: dict[str, Any]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.errors


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _images(product: Mapping[str, Any]) -> list[str]:
    result: list[str] = []
    for value in [product.get("imageUrls"), product.get("imageUrl")]:
        for item in _list(value):
            if isinstance(item, Mapping):
                item = item.get("url")
            text = _text(item)
            if text and text not in result:
                result.append(text)
    return result


def _etim_features(product: Mapping[str, Any]) -> list[dict[str, Any]]:
    etim = product.get("etim")
    if isinstance(etim, Mapping):
        values = etim.get("features", etim.get("characteristics", []))
    else:
        values = etim
    result = []
    for feature in _list(values):
        if not isinstance(feature, Mapping):
            continue
        name = _text(feature.get("name") or feature.get("key"))
        value = feature.get("value", feature.get("values"))
        if name and value not in (None, "", []):
            result.append({"name": name, "value": value, "unit": _text(feature.get("unit"))})
    return result


def _multiplicity(product: Mapping[str, Any]) -> int | float | None:
    values = product.get("warehouseData") or product.get("warehouses")
    if product.get("multiplicity") not in (None, ""):
        return product["multiplicity"]
    for row in _list(values):
        if isinstance(row, Mapping) and row.get("multiplicity") not in (None, ""):
            return row["multiplicity"]
    package = product.get("logisticParamsData", {}).get("singlePackage") if isinstance(product.get("logisticParamsData"), Mapping) else None
    if isinstance(package, Mapping) and package.get("multiplicity") not in (None, ""):
        return package["multiplicity"]
    return None


def _number(product: Mapping[str, Any], *keys: str) -> int | float | None:
    for key in keys:
        value = product.get(key)
        if isinstance(value, Mapping):
            value = value.get("value")
        if value in (None, ""):
            continue
        try:
            return float(value) if "." in str(value) else int(value)
        except (TypeError, ValueError):
            continue
    return None


def _logistic_individual(product: Mapping[str, Any], *names: str) -> Any:
    """Return a supplier's individual-package logistic value by origin key/name."""
    rows = product.get("logisticParams") or []
    expected = {name.casefold() for name in names}
    for row in _list(rows):
        if not isinstance(row, Mapping):
            continue
        label = _text(row.get("nameOrig") or row.get("name")).casefold()
        if label in expected:
            value = row.get("value")
            if isinstance(value, Mapping):
                return value.get("individual")
    return None


def _dimension_cm(product: Mapping[str, Any], key: str, aliases: tuple[str, ...]) -> int | float | None:
    value = _number(product, key)
    if value is None:
        value = _logistic_value(product, *aliases)
    if value is None:
        return None
    # WB card payload dimensions are centimeters; preserve supplier centimeters.
    return value


def _number_from_logistic(product: Mapping[str, Any], *names: str) -> int | float | None:
    value = _logistic_individual(product, *names)
    if value in (None, ""):
        return None
    try:
        return float(value) if "." in str(value) else int(value)
    except (TypeError, ValueError):
        return None


def _logistic_value(product: Mapping[str, Any], *names: str) -> int | float | None:
    """Read an individual logistic parameter; returns None for non-numeric values."""
    value = _logistic_individual(product, *names)
    if value in (None, ""):
        return None
    try:
        return float(value) if "." in str(value) else int(value)
    except (TypeError, ValueError):
        return None


def _base(product: Mapping[str, Any]) -> dict[str, Any]:
    article = _text(product.get("article"))
    features = _etim_features(product)
    return {
        "article": article,
        "offer_id": article,
        "vendor_code": article,
        "name": _text(product.get("name") or product.get("shortName")) or article,
        "brand": _text(product.get("tm")) or "IEK",
        "description": _text(product.get("description")),
        "images": _images(product),
        "features": features,
        "multiplicity": _multiplicity(product),
        "category": _text(product.get("category") or product.get("categoryName")),
        "seller_price": _number(product, "seller_price", "priceRrc"),
        "barcode": _text(product.get("barcode")) or _text(_logistic_individual(product, "Штрихкод", "barcode")),
        "dimensions": {
            "length": _dimension_cm(product, "length", ("l_см", "length_cm")),
            "width": _dimension_cm(product, "width", ("b_см", "width_cm")),
            "height": _dimension_cm(product, "height", ("h_см", "height_cm")),
            "weightBrutto": _number(product, "weightBrutto")
            or _logistic_value(product, "ВесБрутто", "gross_weight_kg"),
        },
    }


def map_ozon(product: Mapping[str, Any], *, category: Mapping[str, Any] | None = None) -> MappingResult:
    """Build an Ozon /v3/product/import item without sending it."""
    base = _base(product)
    category = category or {}
    errors: list[str] = []
    warnings: list[str] = []
    category_id = category.get("description_category_id")
    seller_price = base["seller_price"]
    if seller_price is not None:
        seller_price = float(seller_price)
    else:
        errors.append("missing IEK RRC seller price")
    type_id = category.get("type_id")
    ozon_attribute_ids = {
        "Номин рабочий ток Ie при AC-3 400 В": {"id": 5776, "value_from": "current"},
        "Степень защиты - IP": {"id": 6980, "allowed_values": ["IP20"]},
        "Номин напряжение питания цепи управ Us AC 50 Гц": {"id": 10823, "value_from": "coil_voltage"},
        "Тип напряжения управления": {"id": 10819},
        "Тип подключения силовой электрич цепи": {"id": 20261},
        "Число и исполнение контактов": {"id": 22963, "value_from": "contact_type", "allowed_values": ["1NO", "1NO+1NC"]},
        "Бренд": {"id": 85, "value_from": "brand", "allowed_values": ["IEK", "GENERICA"]},
        "Тип": {"id": 8229, "static_value": "Контактор", "allowed_values": ["Контактор"]},
        "Название модели (для объединения в одну карточку)": {"id": 9048, "value_from": "model"},
        "ТН ВЭД коды ЕАЭС": {"id": 22232, "value_from": "feacn", "allowed_values": ["8536490000 - Прочие реле, на напряжение не более 1000 в", "8536490000 - Прочие реле, на напряжение не более 1000 в."]},
        "Страна-изготовитель": {"id": 4389, "value_from": "country"},
        "Количество товара в УЕИ": {"id": 23249, "value_from": "multiplicity"},
        "Вес с упаковкой, г": {"id": 4497, "value_from": "weight_grams"},
        "Нужен код маркировки": {"id": 23536, "type": "Boolean", "value": True},
        "Номинальный ток, А": {"id": 5776, "value_from": "current"},
        "Напряжение катушки управления, В": {"id": 10823, "value_from": "coil_voltage"},
    }
    ozon_attribute_ids["Число и исполнение контактов"] = {"id": 22963, "value_from": "contact_type", "allowed_values": ["1NO", "1NO+1NC"]}
    ozon_attribute_ids.pop("Напряжение катушки управления, В", None)
    ozon_attribute_ids.pop("Номинальное напряжение, В", None)
    ozon_attribute_ids["Степень защиты - IP"] = {"id": 6980, "allowed_values": ["IP20"]}
    ozon_attribute_ids["Тип тока"] = {"id": 10819}
    ozon_attribute_ids["Количество модулей"] = {"id": 168294, "value_from": "pole_count"}
    ozon_attribute_ids["Бренд"] = {"id": 85, "value_from": "brand", "allowed_values": ["IEK", "GENERICA"]}
    ozon_attribute_ids["Тип"] = {"id": 8229, "static_value": "Контактор", "allowed_values": ["Контактор"]}
    ozon_attribute_ids["Страна-изготовитель"] = {"id": 4389, "value_from": "country"}
    ozon_attribute_ids["ТН ВЭД коды ЕАЭС"] = {"id": 22232, "value_from": "feacn"}
    if category_id is None:
        errors.append("missing Ozon description_category_id mapping")
    if type_id is None:
        errors.append("missing Ozon type_id mapping")
    if not base["images"]:
        errors.append("IEK product has no images")
    if not base["features"]:
        errors.append("IEK product has no ETIM characteristics")
    if base["multiplicity"] not in (None, 1, 1.0):
        warnings.append("multiplicity is not 1; offer suffix must be reviewed")

    attributes = []
    attribute_ids = category.get("attribute_ids", {})
    mapped_characteristics = 0
    emitted_ids: set[int] = set()
    feature_to_ozon_attr = {
        "Номин рабочий ток Ie при AC-3 400 В": "Номинальный ток, А",
        "Рабочий ток": "Номинальный ток, А",
        "Номин напряжение питания цепи управ Us AC 50 Гц": "Напряжение катушки управления, В",
    }
    ozon_fallback_features = {
        "Номинальный ток, А": {"id": 5776, "value_from": "current"},
        "Напряжение катушки управления, В": {"id": 10823, "value_from": "coil_voltage"},
        "Число и исполнение контактов": {"id": 22963, "value_from": "contact_type", "allowed_values": ["1NO", "1NO+1NC"]},
        "Страна-изготовитель": {"id": 4389, "value_from": "country"},
        "ТН ВЭД коды ЕАЭС": {"id": 22232, "value_from": "feacn"},
        "Бренд": {"id": 85, "value_from": "brand", "allowed_values": ["IEK", "GENERICA"]},
        "Тип": {"id": 8229, "static_value": "Контактор", "allowed_values": ["Контактор"]},
        "Нужен код маркировки": {"id": 23536, "type": "Boolean", "value": True},
    }
    for feature in base["features"]:
        if feature["name"] == "Рабочий ток":
            feature = {**feature, "name": "Номин рабочий ток Ie при AC-3 400 В"}
        mapped_name = feature_to_ozon_attr.get(feature["name"], feature["name"])
        mapped = None
        if mapped_name is not None:
            mapped = attribute_ids.get(mapped_name)
            if mapped is None:
                mapped = ozon_attribute_ids.get(mapped_name)
            if mapped is None:
                mapped = ozon_fallback_features.get(mapped_name)
        if feature["name"] == "Бренд" and "Бренд" not in attribute_ids:
            feature = {**feature, "value": base["brand"]}
        elif feature["name"] == "Тип" and "Тип" not in attribute_ids:
            feature = {**feature, "value": "Контактор"}
        if mapped is None and mapped_name is not None:
            mapped = ozon_fallback_features.get(mapped_name)
        if mapped is None:
            warnings.append(f"unmapped Ozon attribute: {feature['name']}")
            continue
        if isinstance(mapped, Mapping):
            attr_id = mapped.get("id")
            complex_id = mapped.get("complex_id", 0)
            allowed = mapped.get("allowed_values")
            is_boolean = mapped.get("type") == "Boolean"
            value_from = mapped.get("value_from")
            static_value = mapped.get("value")
        else:
            attr_id = mapped
            complex_id = 0
            allowed = None
            is_boolean = False
            value_from = None
            static_value = None
        if value_from:
            raw_values = [feature["value"]]
        elif static_value is not None:
            raw_values = [static_value]
        else:
            raw_values = feature["value"] if isinstance(feature["value"], list) else [feature["value"]]
        normalized_values = []
        for raw in raw_values:
            value = _text(raw)
            if allowed is not None and value not in allowed:
                warnings.append(f"IEK value for {feature['name']} lacks exact Ozon dictionary mapping")
                continue
            if is_boolean:
                low = value.casefold()
                if low in {"да", "yes", "true", "1"}:
                    converted: Any = True
                elif low in {"нет", "no", "false", "0"}:
                    converted = False
                else:
                    warnings.append(f"IEK Boolean value for {feature['name']} isn't normalized")
                    continue
            else:
                converted = value
            normalized_values.append(converted)
            if normalized_values and attr_id is not None and attr_id not in emitted_ids:
                attributes.append({"id": attr_id, "complex_id": complex_id, "values": [{"value": v} for v in normalized_values]})
                emitted_ids.add(attr_id)
            if normalized_values and attr_id is not None and (not category.get("required_attribute_ids") or attr_id in set(category.get("required_attribute_ids", []))):
                mapped_characteristics += 1

    missing_required = sorted(set(category.get("required_attribute_ids", [])) - {a["id"] for a in attributes})
    if missing_required:
        errors.append("missing required Ozon attributes: " + ", ".join(map(str, missing_required)))
    if not mapped_characteristics:
        errors.append("no required Ozon characteristics mapped")

    item = {
        "offer_id": base["offer_id"],
        "name": base["name"],
        "description": base["description"],
        "images": base["images"],
        "attributes": attributes,
        "description_category_id": category_id,
        "type_id": type_id,
        "price": seller_price,
    }
    for key, value in (
        ("barcode", base["barcode"]),
        ("currency_code", product.get("currency_code")),
        ("old_price", product.get("old_price")),
    ):
        if value not in (None, ""):
            item[key] = value
    if seller_price is None:
        errors.append("missing IEK RRC seller price")
    if not item.get("barcode"):
        errors.append("missing commercial field: barcode")
    return MappingResult(base["offer_id"], item, errors, warnings)


def map_wb(product: Mapping[str, Any], *, category: Mapping[str, Any] | None = None) -> MappingResult:
    """Build a WB /content/v2/cards/upload card without sending it."""
    base = _base(product)
    category = category or {}
    errors: list[str] = []
    warnings: list[str] = []
    subject_id = category.get("subject_id")
    if subject_id is None:
        errors.append("missing WB subject_id mapping")
    if not base["images"]:
        errors.append("IEK product has no images")
    if not base["features"]:
        errors.append("IEK product has no ETIM characteristics")
    if any(value is None or value <= 0 for value in base["dimensions"].values()):
        errors.append("missing WB dimensions or weight")
    if base["multiplicity"] not in (None, 1, 1.0):
        warnings.append("multiplicity is not 1; vendor code suffix must be reviewed")

    characteristics = []
    wb_characteristic_ids = {
        "Номин рабочий ток Ie при AC-3 400 В": {"id": 81589},
        "Степень защиты - IP": {"id": 16758},
        "Номин напряжение питания цепи управ Us AC 50 Гц": {"id": 14207},
        "Кол-во вспомогат норм разомкнутых-НО конт": {"id": 168294, "value_from": "aux_no_count"},
        "Кол-во вспомогат норм замкнутых-НЗ конт": {"id": 168294, "value_from": "aux_nc_count"},
        "Тип подключения силовой электрич цепи": {"id": 5023, "value_from": "connection"},
        "Кол-во норм разомкнутых-НО силовых конт": {"id": 176180, "value_from": "main_no_count"},
        "Кол-во норм замкнутых-НЗ силовых контактов": {"id": 176180, "value_from": "main_nc_count"},
        "Тип напряжения управления": {"id": 14207, "value_from": "control_current"},
        "Бренд": {"id": 14177446, "value_from": "brand"},
        "Страна производства": {"id": 14177451, "value_from": "countryOfProduction"},
        "Описание": {"id": 14177452, "value_from": "description"},
        "Баркод": {"id": 14177453, "value_from": "barcode"},
        "Наименование": {"id": 15000000, "value_from": "name"},
        "ТНВЭД": {"id": 15000001, "value_from": "feacn"},
        "Вес с упаковкой (кг)": {"id": 88953, "value_from": "gross_weight_kg"},
        "Высота предмета": {"id": 90630, "value_from": "height_cm"},
        "Глубина предмета": {"id": 90652, "value_from": "length_cm"},
        "Ширина предмета": {"id": 90673, "value_from": "width_cm"},
    }
    characteristic_ids = {**wb_characteristic_ids, **category.get("characteristic_ids", {})}
    characteristic_ids["Тип напряжения управления"] = {"id": 14207, "value_from": "coil_voltage"}
    characteristic_ids["Число и исполнение контактов"] = {"id": 22963, "value_from": "contact_type", "allowed_values": ["1NO", "1NO+1NC"]}
    characteristic_ids["Высота предмета"] = {"id": 90630, "value_from": "height_cm"}
    characteristic_ids["Глубина предмета"] = {"id": 90652, "value_from": "length_cm"}
    characteristic_ids["Ширина предмета"] = {"id": 90673, "value_from": "width_cm"}

    def wb_source_value(source_key: str) -> str:
        values = {
            "connection": "Винтовое соединение",
            "brand": base["brand"],
            "countryOfProduction": _text(product.get("countryOfProduction")),
            "description": base["description"],
            "barcode": base["barcode"],
            "name": base["name"],
            "feacn": _text(product.get("feacn")),
            "coil_voltage": next((f["value"] for f in base["features"] if f["name"] == "Номин напряжение питания цепи управ Us AC 50 Гц"), ""),
            "current": next((f["value"] for f in base["features"] if f["name"] == "Номин рабочий ток Ie при AC-3 400 В"), ""),
            "contact_type": "1NO+1NC" if "1NC" in base["name"] else "1NO",
            "control_current": next((f["value"] for f in base["features"] if f["name"] == "Тип напряжения управления"), ""),
            "aux_no_count": next((f["value"] for f in base["features"] if f["name"] == "Кол-во вспомогат норм разомкнутых-НО конт"), ""),
            "aux_nc_count": next((f["value"] for f in base["features"] if f["name"] == "Кол-во вспомогат норм замкнутых-НЗ конт"), ""),
            "main_no_count": next((f["value"] for f in base["features"] if f["name"] == "Кол-во норм разомкнутых-НО силовых конт"), ""),
            "main_nc_count": next((f["value"] for f in base["features"] if f["name"] == "Кол-во норм замкнутых-НЗ силовых контактов"), ""),
            "gross_weight_kg": _text(base["dimensions"]["weightBrutto"]),
            "height_cm": _text(base["dimensions"]["height"]),
            "length_cm": _text(base["dimensions"]["length"]),
            "width_cm": _text(base["dimensions"]["width"]),
            "weight_grams": str(round((base["dimensions"]["weightBrutto"] or 0) * 1000)),
            "module_count": "3",
            "pole_count": "3",
        }
        return values.get(source_key, "")

    for feature in base["features"]:
        if feature["name"] == "Рабочий ток":
            feature = {**feature, "name": "Номин рабочий ток Ie при AC-3 400 В"}
        mapped = characteristic_ids.get(feature["name"])
        if mapped is None:
            warnings.append(f"unmapped WB characteristic: {feature['name']}")
            continue
        if isinstance(mapped, Mapping):
            char_id = mapped.get("id")
            allowed = mapped.get("allowed_values")
            value_from = mapped.get("value_from")
            static_value = mapped.get("value")
        else:
            char_id = mapped
            allowed = None
            value_from = None
            static_value = None
        if value_from:
            raw_values = [wb_source_value(value_from)]
        elif static_value is not None:
            raw_values = [static_value]
        else:
            raw_values = feature["value"] if isinstance(feature["value"], list) else [feature["value"]]
        clean_values = []
        for raw_value in raw_values:
            value = _text(raw_value)
            if allowed is not None and value not in allowed:
                warnings.append(f"IEK value for {feature['name']} has no exact WB dictionary match")
                continue
            clean_values.append(value)
        if clean_values:
            characteristics.append({"id": char_id, "value": clean_values})

    required_ids = set(category.get("required_characteristic_ids", []))
    present_ids = {char["id"] for char in characteristics}
    missing_required = sorted(required_ids - present_ids)
    if missing_required:
        errors.append("missing required WB characteristics: " + ", ".join(map(str, missing_required)))

    card = {
        "subjectID": subject_id,
        "variants": [{
            "vendorCode": base["vendor_code"],
            "title": base["name"],
            "brand": base["brand"],
            "description": base["description"],
            "dimensions": base["dimensions"],
            "characteristics": characteristics,
            "sizes": [{"techSize": "0", "wbSize": "0", "price": base["seller_price"] or 0, "skus": [str(base["barcode"] or "")]}],
            "photos": {"c246x328": base["images"]},
        }],
    }
    if not base["barcode"]:
        errors.append("missing commercial field: barcode")
    if base["seller_price"] is None:
        errors.append("missing IEK RRC seller price")
    if not characteristics:
        errors.append("no mapped WB characteristics")
    return MappingResult(base["article"], card, errors, warnings)


def build_preview(product: Mapping[str, Any], *, ozon: Mapping[str, Any] | None = None, wb: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a JSON-safe dry-run report for the local UI/API."""
    oz = map_ozon(product, category=ozon)
    wild = map_wb(product, category=wb)
    return {
        "article": _text(product.get("article")),
        "multiplicity": _multiplicity(product),
        "ozon": {"ready": oz.ready, "payload": oz.payload, "errors": oz.errors, "warnings": oz.warnings},
        "wb": {"ready": wild.ready, "payload": wild.payload, "errors": wild.errors, "warnings": wild.warnings},
        "publishable": oz.ready and wild.ready,
    }
