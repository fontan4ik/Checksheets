"""Deterministic IEK-to-marketplace card mapping and validation.

This module never calls WB/Ozon and never publishes cards. It converts a
supplier response plus explicitly supplied seller-commercial facts and verified
marketplace schema into reviewable payloads. Supplier RRC is used only when an
explicit policy selects it as the seller-price source.
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
    for value in (product.get("imageUrls"), product.get("imageUrl")):
        for item in _list(value):
            if isinstance(item, Mapping):
                item = item.get("url")
            text = _text(item)
            if text and text not in result:
                result.append(text)
    return result


def _etim_features(product: Mapping[str, Any]) -> list[dict[str, Any]]:
    etim = product.get("etim")
    values = etim.get("features", etim.get("characteristics", [])) if isinstance(etim, Mapping) else etim
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


def marketplace_article(product: Mapping[str, Any]) -> str:
    """Append supplier multiplicity to the marketplace listing article."""
    article = _text(product.get("article"))
    multiplicity = _multiplicity(product)
    if not article or multiplicity in (None, ""):
        return article
    try:
        quantity = float(multiplicity)
    except (TypeError, ValueError):
        return article
    if quantity <= 0 or not quantity.is_integer():
        return article
    suffix = f"-{int(quantity)}"
    return article if article.endswith(suffix) else article + suffix


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
    expected = {name.casefold() for name in names}
    for row in _list(product.get("logisticParams") or []):
        if not isinstance(row, Mapping):
            continue
        label = _text(row.get("nameOrig") or row.get("name")).casefold()
        if label in expected:
            value = row.get("value")
            return value.get("individual") if isinstance(value, Mapping) else None
    return None


def _logistic_value(product: Mapping[str, Any], *names: str) -> int | float | None:
    value = _logistic_individual(product, *names)
    if value in (None, ""):
        return None
    try:
        return float(value) if "." in str(value) else int(value)
    except (TypeError, ValueError):
        return None


def _package_measurements(product: Mapping[str, Any]) -> dict[str, int | float | None]:
    """Resolve dimensions from IEK's single-package record, never transport size."""
    logistics = product.get("logisticParamsData")
    package = logistics.get("singlePackage") if isinstance(logistics, Mapping) else None
    package = package if isinstance(package, Mapping) else {}

    def dimension(axis: str, logistics_alias: str, legacy_aliases: tuple[str, ...]) -> float | None:
        raw = package.get(axis)
        unit = _text(package.get("dimensionUnit") or package.get("unit")).casefold()
        if isinstance(raw, Mapping):
            unit = _text(raw.get("unit") or unit).casefold()
            raw = raw.get("individual", raw.get("value"))
        if raw in (None, ""):
            raw = _logistic_individual(product, logistics_alias)
            unit = "cm" if logistics_alias.endswith("_см") else unit
        if raw in (None, ""):
            raw = _logistic_individual(product, *legacy_aliases)
            unit = unit or ("cm" if any(alias.endswith("_см") for alias in legacy_aliases) else "")
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return None
        if number <= 0:
            return None
        if unit in {"см", "cm"}:
            return number
        if unit in {"мм", "mm"}:
            return number / 10
        return None

    weight = package.get("weightBrutto", package.get("weight"))
    weight_unit = _text(package.get("weightUnit") or package.get("weight_unit")).casefold()
    if isinstance(weight, Mapping):
        weight_unit = _text(weight.get("unit") or weight_unit).casefold()
        weight = weight.get("individual", weight.get("value"))
    if weight in (None, ""):
        weight = _logistic_value(product, "ВесБрутто", "Вес брутто", "Масса брутто")
        weight_unit = weight_unit or "kg"
    try:
        weight_value = float(weight)
    except (TypeError, ValueError):
        weight_value = None
    if weight_value is not None:
        if weight_unit in {"кг", "kg"}:
            pass
        elif weight_unit in {"г", "g"}:
            weight_value /= 1000
        else:
            weight_value = None
    return {
        "length": dimension("length", "l_см", ("Длина упаковки", "Длина")),
        "width": dimension("width", "b_см", ("Ширина упаковки", "Ширина")),
        "height": dimension("height", "h_см", ("Высота упаковки", "Высота")),
        "weightBrutto": weight_value if weight_value and weight_value > 0 else None,
    }


def _base(product: Mapping[str, Any]) -> dict[str, Any]:
    source_article = _text(product.get("article"))
    listing_article = marketplace_article(product)
    return {
        "source_article": source_article,
        "article": listing_article,
        "offer_id": listing_article,
        "vendor_code": listing_article,
        "name": _text(product.get("name") or product.get("shortName")) or source_article,
        "brand": _text(product.get("tm")) or "IEK",
        "description": _text(product.get("description")),
        "images": _images(product),
        "features": _etim_features(product),
        "multiplicity": _multiplicity(product),
        "seller_price": _number(product, "seller_price"),
        "source_family": _text(product.get("family")),
        "source_series": _text(product.get("series")),
        "barcode": next((_text(product.get(key)) for key in ("barcode", "barcodeValue", "gtin", "gtin13", "ean", "ean13") if _text(product.get(key))), "") or _text(_logistic_individual(product, "Штрихкод", "Штрихкод товара", "barcode", "EAN", "EAN13", "GTIN", "GTIN-13")),
        "dimensions": _package_measurements(product),
    }


def map_ozon(product: Mapping[str, Any], *, category: Mapping[str, Any] | None = None, vat: str | None = None, product_id: int | None = None) -> MappingResult:
    """Build an Ozon /v3/product/import item without sending it."""
    base = _base(product)
    category = category or {}
    errors: list[str] = []
    warnings: list[str] = []
    category_id = category.get("description_category_id")
    type_id = category.get("type_id")
    price = base["seller_price"]
    if price is None and category.get("seller_price_source") == "iek_priceRrc":
        price = _number(product, "priceRrc")
    vat = vat if vat not in (None, "") else product.get("vat")

    if price is None:
        errors.append("missing explicit seller_price; supplier priceRrc is not a seller-price source")
    if vat in (None, ""):
        errors.append("missing explicit Ozon VAT rate")
    if category_id is None:
        errors.append("missing Ozon description_category_id mapping")
    if type_id is None:
        errors.append("missing Ozon type_id mapping")
    if not base["images"]:
        errors.append("IEK product has no images")
    if base["multiplicity"] not in (None, 1, 1.0):
        warnings.append("multiplicity is not 1; offer suffix must be reviewed")

    builtins = {
        "Номин рабочий ток Ie при AC-3 400 В": {"id": 5776},
        "Рабочий ток": {"id": 5776},
        "Степень защиты - IP": {"id": 6980},
        "Номин напряжение питания цепи управ Us AC 50 Гц": {"id": 10823},
        "Тип напряжения управления": {"id": 10819},
        "Бренд": {"id": 85},
        "Название": {"id": 4180},
        "Тип": {"id": 8229, "static_value": "Контактор"},
        "Название модели (для объединения в одну карточку)": {"id": 9048},
        "ТН ВЭД коды ЕАЭС": {"id": 22232},
        "Страна-изготовитель": {"id": 4389},
        "Нужен код маркировки": {"id": 23536, "type": "Boolean"},
        "Количество полюсов": {"id": 10818},
        "Число и исполнение контактов": {"id": 22963},
    }
    aliases = {
        "Рабочий ток": "Номин рабочий ток Ie при AC-3 400 В",
        "Кол-во вспомогат норм разомкнутых-НО конт": "Количество полюсов",
        "Кол-во вспомогат норм замкнутых-НЗ конт": "Количество полюсов",
        "Кол-во норм разомкнутых-НО силовых конт": "Количество полюсов",
        "Кол-во норм замкнутых-НЗ силовых контактов": "Количество полюсов",
    }
    source_features = list(base["features"])
    # Ozon 9048 is required free text (dictionary_id=0). IEK's exact
    # catalogue name/shortName is the source-backed model label; never infer it
    # from an article code or substitute a cabinet's opaque grouped value.
    model_name = _text(product.get("model_name") or product.get("shortName") or product.get("name"))
    if model_name and not any(feature["name"] == "Название модели (для объединения в одну карточку)" for feature in source_features):
        source_features.append({"name": "Название модели (для объединения в одну карточку)", "value": model_name})
    product_title = _text(product.get("russianName") or product.get("shortName") or product.get("name"))
    if product_title and not any(feature["name"] == "Название" for feature in source_features):
        source_features.append({"name": "Название", "value": product_title})
    if not any(feature["name"].casefold() in {"тн вэд", "тн вэд коды еаэс", "код тн вэд"} for feature in source_features):
        feacn = _text(product.get("feacn") or product.get("tn_ved"))
        if feacn:
            source_features.append({"name": "ТН ВЭД коды ЕАЭС", "value": feacn})
    marking_names = {"нужен код маркировки", "маркировка", "товар подлежит маркировке"}
    if not any(feature["name"].casefold() in marking_names for feature in source_features):
        is_marked = product.get("isMarked")
        if isinstance(is_marked, bool):
            source_features.append({"name": "Нужен код маркировки", "value": is_marked})
    else:
        source_features = [feature for feature in source_features if feature["name"].casefold() not in marking_names] + [next(feature for feature in reversed(source_features) if feature["name"].casefold() in marking_names)]
    if not any(feature["name"] == "Бренд" for feature in source_features):
        source_features.append({"name": "Бренд", "value": base["brand"]})
    attribute_ids = category.get("attribute_ids", {})
    for name, mapping in attribute_ids.items():
        if isinstance(mapping, Mapping):
            constant = mapping.get("value", mapping.get("static_value"))
            if constant is not None and not any(feature["name"] == name for feature in source_features):
                source_features.append({"name": name, "value": constant})

    attributes: list[dict[str, Any]] = []
    emitted: set[int] = set()
    for feature in source_features:
        name = feature["name"]
        mapped_name = aliases.get(name, name)
        mapped = attribute_ids.get(mapped_name) if mapped_name is not None else None
        if mapped is None and mapped_name is not None:
            mapped = builtins.get(mapped_name)
        if mapped is None:
            warnings.append(f"unmapped Ozon attribute: {name}")
            continue
        if isinstance(mapped, Mapping):
            attr_id = mapped.get("id")
            static = mapped.get("value", mapped.get("static_value"))
            allowed = mapped.get("allowed_values")
            declared_type = _text(mapped.get("type")).casefold()
            boolean = declared_type in {"boolean", "bool"} or "boolean" in declared_type
        else:
            attr_id, static, allowed, boolean = mapped, None, None, False
        raw = static if static is not None else feature.get("value")
        values = raw if isinstance(raw, list) else [raw]
        clean = []
        for raw_value in values:
            value: Any = raw_value if boolean and isinstance(raw_value, bool) else _text(raw_value)
            if boolean and not isinstance(value, bool):
                normalized = _text(value).casefold()
                if normalized in {"да", "yes", "true", "1"}:
                    value = True
                elif normalized in {"нет", "no", "false", "0"}:
                    value = False
                else:
                    warnings.append(f"IEK Boolean value for {name} isn't normalized")
                    continue
            clean.append(value)
        if clean and attr_id is not None and attr_id not in emitted:
            complex_id = mapped.get("complex_id", 0) if isinstance(mapped, Mapping) else 0
            output_values = clean if boolean else [_text(value) for value in clean]
            attributes.append({"id": attr_id, "complex_id": complex_id, "values": [{"value": value} for value in output_values]})
            emitted.add(attr_id)

    required_ids = set(category.get("required_attribute_ids", []))
    missing_required = sorted(required_ids - emitted)
    if missing_required:
        errors.append("missing required Ozon attributes: " + ", ".join(map(str, missing_required)))
    if not attributes:
        errors.append("no required Ozon characteristics mapped")
    if not category.get("schema_verified"):
        errors.append("Ozon schema has not been verified for this payload")

    item: dict[str, Any] = {
        "offer_id": base["offer_id"],
        # Ozon validates attribute 4180 as a Russian product title. Prefer a
        # source-backed Russian supplier shortName/name rather than an
        # English fallback, which previously caused DESCRIPTION_DECLINE.
        "name": _text(product.get("russianName") or product.get("shortName") or product.get("name")) or base["name"],
        "description": _text(product.get("russianDescription") or product.get("description")) or base["description"],
        "images": base["images"],
        "attributes": attributes,
        "description_category_id": category_id,
        "type_id": type_id,
    }
    if product_id is not None:
        if isinstance(product_id, bool) or product_id <= 0:
            errors.append("product_id must be a positive Ozon product ID")
        else:
            item["product_id"] = product_id
    package_dims = base["dimensions"]
    if any(package_dims[key] is None or package_dims[key] <= 0 for key in ("length", "width", "height", "weightBrutto")):
        errors.append("missing IEK individual package dimensions/weight with supported units")
    else:
        item.update({
            "depth": round(float(package_dims["length"]) * 10),
            "width": round(float(package_dims["width"]) * 10),
            "height": round(float(package_dims["height"]) * 10),
            "weight": round(float(package_dims["weightBrutto"]) * 1000),
            "dimension_unit": "mm",
            "weight_unit": "g",
        })
    if price is not None:
        item["price"] = float(price)
    if vat not in (None, ""):
        item["vat"] = str(vat)
    for key, value in (("barcode", base["barcode"]), ("currency_code", product.get("currency_code")), ("old_price", product.get("old_price"))):
        if value not in (None, ""):
            item[key] = value
    if not base["barcode"]:
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
    if not base["barcode"]:
        errors.append("missing commercial field: barcode")
    seller_price = base["seller_price"]
    if seller_price is None and category.get("seller_price_source") == "iek_priceRrc":
        seller_price = _number(product, "priceRrc")
    if seller_price is None:
        errors.append("missing explicit seller_price; supplier priceRrc is not a seller-price source")

    if base["images"] and category.get("photo_contract_verified") is not True:
        errors.append("WB photo/media submission contract has not been verified")

    # Only the numeric WB mappings below are grounded in the reviewed subject
    # descriptor. Text/enum mappings must be supplied after dictionary lookup.
    characteristic_ids = category.get("characteristic_ids", {})
    if subject_id == 4225:
        reviewed_ids = {
            "Номин рабочий ток Ie при AC-3 400 В": {"id": 81589, "kind": "number"},
            "Рабочий ток": {"id": 81589, "kind": "number"},
            "Высота предмета": {"id": 90630, "kind": "number"},
            "Глубина предмета": {"id": 90652, "kind": "number"},
            "Ширина предмета": {"id": 90673, "kind": "number"},
            "Вес с упаковкой (кг)": {"id": 88953, "kind": "number"},
            "Ширина упаковки": {"id": 90745, "kind": "number"},
            "Высота упаковки": {"id": 90846, "kind": "number"},
            "Длина упаковки": {"id": 90849, "kind": "number"},
        }
        characteristic_ids = reviewed_ids | characteristic_ids
    characteristics = []
    wb_features = list(base["features"])
    dims = base["dimensions"]
    derived = (
        ("Бренд", base["brand"]), ("Описание", base["description"]),
        ("Высота предмета", dims["height"]), ("Глубина предмета", dims["length"]),
        ("Ширина предмета", dims["width"]), ("Вес с упаковкой (кг)", dims["weightBrutto"]),
        ("Ширина упаковки", dims["width"]), ("Высота упаковки", dims["height"]),
        ("Длина упаковки", dims["length"]),
        ("Баркод", base["barcode"]), ("Наименование", base["name"]),
    )
    for extra_name, extra_value in derived:
        if extra_value and not any(feature["name"] == extra_name for feature in wb_features):
            wb_features.append({"name": extra_name, "value": extra_value})
    if subject_id == 4225:
        wb_features = [feature for feature in wb_features if feature["name"] not in {"Бренд", "Баркод", "Наименование"}]
    for feature in wb_features:
        mapped = characteristic_ids.get(feature["name"])
        if mapped is None:
            warnings.append(f"unmapped WB characteristic: {feature['name']}")
            continue
        char_id = mapped.get("id") if isinstance(mapped, Mapping) else mapped
        raw_values = feature["value"] if isinstance(feature["value"], list) else [feature["value"]]
        values = []
        for raw_value in raw_values:
            if raw_value in (None, ""):
                continue
            if isinstance(mapped, Mapping) and mapped.get("kind") == "number":
                try:
                    values.append(float(raw_value))
                except (TypeError, ValueError):
                    warnings.append(f"non-numeric WB value for {feature['name']}")
            else:
                values.append(_text(raw_value))
        if values and char_id is not None:
            characteristics.append({"id": char_id, "value": values})
    required = set(category.get("required_characteristic_ids", []))
    missing = sorted(required - {feature["id"] for feature in characteristics})
    if missing:
        errors.append("missing required WB characteristics: " + ", ".join(map(str, missing)))
    if not characteristics:
        errors.append("no mapped WB characteristics")
    if not category.get("schema_verified"):
        errors.append("WB schema has not been verified for this payload")

    size: dict[str, Any] = {"techSize": "0", "wbSize": "0", "skus": [str(base["barcode"])]}
    if seller_price is not None:
        size["price"] = seller_price
    card = {
        "subjectID": subject_id,
        "variants": [{
            "vendorCode": base["vendor_code"],
            "title": base["name"],
            "brand": base["brand"],
            "description": base["description"],
            "dimensions": base["dimensions"],
            "characteristics": characteristics,
            "sizes": [size],
            "photos": base["images"],
        }],
    }
    return MappingResult(base["article"], card, errors, warnings)


def build_preview(product: Mapping[str, Any], *, ozon: Mapping[str, Any] | None = None, wb: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a JSON-safe dry-run report for the local UI/API."""
    oz = map_ozon(product, category=ozon)
    wild = map_wb(product, category=wb)
    return {
        "sourceArticle": _text(product.get("article")),
        "article": marketplace_article(product),
        "multiplicity": _multiplicity(product),
        "ozon": {"ready": oz.ready, "payload": oz.payload, "errors": oz.errors, "warnings": oz.warnings},
        "wb": {"ready": wild.ready, "payload": wild.payload, "errors": wild.errors, "warnings": wild.warnings},
        "publishable": oz.ready and wild.ready,
    }
