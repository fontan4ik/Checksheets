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
    for feature in base["features"]:
        mapped = attribute_ids.get(feature["name"])
        if mapped is None:
            warnings.append(f"unmapped Ozon attribute: {feature['name']}")
            continue
        if isinstance(mapped, Mapping):
            attr_id = mapped.get("id")
            complex_id = mapped.get("complex_id", 0)
            allowed = mapped.get("allowed_values")
            is_boolean = mapped.get("type") == "Boolean"
        else:
            attr_id = mapped
            complex_id = 0
            allowed = None
            is_boolean = False
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
        if normalized_values:
            attributes.append({"id": attr_id, "complex_id": complex_id, "values": [{"value": v} for v in normalized_values]})
            if not category.get("required_attribute_ids") or attr_id in set(category.get("required_attribute_ids", [])):
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
    characteristic_ids = category.get("characteristic_ids", {})
    for feature in base["features"]:
        mapped = characteristic_ids.get(feature["name"])
        if mapped is None:
            warnings.append(f"unmapped WB characteristic: {feature['name']}")
            continue
        if isinstance(mapped, Mapping):
            char_id = mapped.get("id")
            allowed = mapped.get("allowed_values")
        else:
            char_id = mapped
            allowed = None
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
