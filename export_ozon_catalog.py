#!/usr/bin/env python3
"""Export the complete seller catalog from Ozon Seller API.

Credentials are read only from OZON_CLIENT_ID and OZON_API_KEY environment
variables. The script never writes or prints credentials.

Run:
    OZON_CLIENT_ID=... OZON_API_KEY=... python3 ozon_catalog_export.py

Output: catalog.csv, brands.csv, categories.csv, and catalog.json in
./Данные_Ozon/ (or the directory passed with --out).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


API_ROOT = "https://api-seller.ozon.ru"
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
PRODUCT_BATCH_SIZE = 1000


class OzonAPIError(RuntimeError):
    pass


class OzonClient:
    def __init__(self, client_id: str, api_key: str, timeout: int = 60) -> None:
        self._client_id = client_id
        self._api_key = api_key
        self.timeout = timeout

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            API_ROOT + path,
            data=payload,
            method="POST",
            headers={
                "Client-Id": self._client_id,
                "Api-Key": self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        for attempt in range(6):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    decoded = json.loads(response.read().decode("utf-8"))
                    if not isinstance(decoded, dict):
                        raise OzonAPIError(f"Ozon вернул неожиданный формат для {path}")
                    return decoded
            except urllib.error.HTTPError as exc:
                try:
                    raw = exc.read().decode("utf-8", errors="replace")
                    detail_obj = json.loads(raw)
                    detail = str(detail_obj.get("message") or detail_obj.get("error") or "")
                except Exception:
                    detail = ""
                detail = detail.replace(self._api_key, "[скрыто]").replace(self._client_id, "[скрыто]")
                if exc.code in RETRYABLE_HTTP_STATUSES and attempt < 5:
                    time.sleep(min(2**attempt, 30))
                    continue
                suffix = f": {detail[:400]}" if detail else ""
                raise OzonAPIError(f"Ошибка Ozon API {exc.code} на {path}{suffix}") from None
            except urllib.error.URLError as exc:
                if attempt < 5:
                    time.sleep(min(2**attempt, 30))
                    continue
                raise OzonAPIError(f"Не удалось подключиться к Ozon API для {path}: {exc.reason}") from None
            except json.JSONDecodeError:
                raise OzonAPIError(f"Ozon вернул некорректный JSON для {path}") from None

        raise OzonAPIError(f"Не удалось выполнить запрос {path}")


def result_object(response: dict[str, Any]) -> dict[str, Any]:
    value = response.get("result", response)
    return value if isinstance(value, dict) else {}


def product_list(client: OzonClient, page_size: int) -> list[dict[str, Any]]:
    products: dict[str, dict[str, Any]] = {}
    cursor = ""
    seen_cursors: set[str] = set()
    page = 0

    while True:
        response = client.post(
            "/v3/product/list",
            {"filter": {"visibility": "ALL"}, "last_id": cursor, "limit": page_size},
        )
        result = result_object(response)
        items = result.get("items", [])
        if not isinstance(items, list):
            raise OzonAPIError("Ответ /v3/product/list не содержит список result.items")
        page += 1
        for item in items:
            if not isinstance(item, dict):
                continue
            product_id = item.get("product_id") or item.get("id")
            key = str(product_id) if product_id is not None else str(item.get("offer_id", ""))
            if key:
                products[key] = item

        print(f"Страница каталога {page}: получено {len(items)}, накоплено {len(products)} товаров")
        next_cursor = str(result.get("last_id") or "")
        if not items or not next_cursor:
            break
        if next_cursor == cursor or next_cursor in seen_cursors:
            raise OzonAPIError("Пагинация Ozon зациклилась; выгрузка остановлена")
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    return list(products.values())


def chunks(values: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def product_details(client: OzonClient, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    product_ids = [
        item.get("product_id") or item.get("id")
        for item in products
        if item.get("product_id") is not None or item.get("id") is not None
    ]
    offer_ids = [str(item["offer_id"]) for item in products if item.get("offer_id")]
    details_by_id: dict[str, dict[str, Any]] = {}
    details_by_offer: dict[str, dict[str, Any]] = {}

    for batch_number, batch in enumerate(chunks(product_ids, PRODUCT_BATCH_SIZE), start=1):
        response = client.post("/v3/product/info/list", {"product_id": batch})
        result = result_object(response)
        items = result.get("items", [])
        if not isinstance(items, list):
            raise OzonAPIError("Ответ /v3/product/info/list не содержит список result.items")
        for item in items:
            if isinstance(item, dict):
                product_id = item.get("product_id") or item.get("id")
                offer_id = item.get("offer_id")
                if product_id is not None:
                    details_by_id[str(product_id)] = item
                if offer_id:
                    details_by_offer[str(offer_id)] = item
        print(f"Пакет подробных карточек {batch_number}: получено {len(items)} товаров")

    for batch_number, batch in enumerate(chunks(offer_ids, PRODUCT_BATCH_SIZE), start=1):
        response = client.post(
            "/v4/product/info/attributes",
            {"filter": {"offer_id": batch}, "limit": len(batch)},
        )
        items = response.get("result", [])
        if not isinstance(items, list):
            raise OzonAPIError("Ответ /v4/product/info/attributes не содержит список result")
        for item in items:
            if not isinstance(item, dict):
                continue
            offer_id = item.get("offer_id")
            product_id = item.get("product_id") or item.get("id")
            if offer_id:
                details_by_offer[str(offer_id)] = {
                    **details_by_offer.get(str(offer_id), {}),
                    **item,
                }
            if product_id is not None:
                details_by_id[str(product_id)] = {
                    **details_by_id.get(str(product_id), {}),
                    **item,
                }
        print(f"Пакет атрибутов {batch_number}: получено {len(items)} товаров")

    merged: list[dict[str, Any]] = []
    for listed in products:
        product_id = listed.get("product_id") or listed.get("id")
        offer_id = str(listed.get("offer_id") or "")
        detail = details_by_offer.get(offer_id, {}) or (
            details_by_id.get(str(product_id), {}) if product_id is not None else {}
        )
        # Preserve type and status details from /v3 while adding Ozon attributes from /v4.
        merged.append({**listed, **details_by_id.get(str(product_id), {}), **detail})
    return merged


def first_value(item: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = item.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def scalar_text(value: Any) -> str:
    if isinstance(value, dict):
        value = first_value(value, ("name", "title", "value", "label"))
    if isinstance(value, list):
        return ", ".join(filter(None, (scalar_text(v) for v in value)))
    return str(value).strip() if value is not None else ""


def attribute_value(attributes: Any, target_names: set[str]) -> str:
    if not isinstance(attributes, list):
        return ""
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        name = scalar_text(first_value(attribute, ("name", "attribute_name", "title"))).casefold()
        attribute_id = str(first_value(attribute, ("id", "attribute_id")) or "")
        if name in target_names or (not name and attribute_id == "85"):
            values = attribute.get("values") or attribute.get("value") or []
            if isinstance(values, list):
                return ", ".join(
                    filter(
                        None,
                        (
                            scalar_text(first_value(v, ("value", "name", "title")))
                            if isinstance(v, dict)
                            else scalar_text(v)
                            for v in values
                        ),
                    )
                )
            return scalar_text(values)
    return ""


def flatten_category_tree(tree: Any) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    category_paths: dict[str, str] = {}
    type_paths: dict[tuple[str, str], str] = {}
    child_keys = ("children", "categories", "types", "type_list", "items")

    def visit(node: Any, path: tuple[str, ...] = (), parent_category_id: str = "") -> None:
        if isinstance(node, list):
            for child in node:
                visit(child, path, parent_category_id)
            return
        if not isinstance(node, dict):
            return

        category_id = first_value(node, ("description_category_id", "category_id"))
        type_id = first_value(node, ("type_id",))
        label = scalar_text(first_value(node, ("category_name", "type_name", "name", "title")))

        next_path = path
        current_category_id = parent_category_id
        if category_id is not None:
            current_category_id = str(category_id)
            next_path = path + ((label,) if label else ())
            if next_path:
                category_paths[current_category_id] = " › ".join(next_path)
        if type_id is not None:
            type_label = scalar_text(first_value(node, ("type_name", "name", "title")))
            type_path = next_path + ((type_label,) if type_label and type_label not in next_path else ())
            if current_category_id and type_path:
                type_paths[(current_category_id, str(type_id))] = " › ".join(type_path)

        for key in child_keys:
            child = node.get(key)
            if isinstance(child, (dict, list)):
                visit(child, next_path, current_category_id)

    visit(tree)
    return category_paths, type_paths


def load_category_paths(client: OzonClient) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    response = client.post("/v1/description-category/tree", {"language": "RU"})
    root = response.get("result", response)
    return flatten_category_tree(root)


def normalize_product(
    item: dict[str, Any],
    category_paths: dict[str, str],
    type_paths: dict[tuple[str, str], str],
) -> dict[str, str]:
    description_category_id = scalar_text(
        first_value(item, ("description_category_id", "category_id"))
    )
    type_id = scalar_text(item.get("type_id"))
    direct_category = scalar_text(
        first_value(item, ("description_category_name", "category_name", "category"))
    )
    category = direct_category or category_paths.get(description_category_id, "")
    if not category and description_category_id:
        category = f"Категория Ozon #{description_category_id}"

    direct_type = scalar_text(first_value(item, ("type_name", "product_type", "type")))
    product_type = direct_type or type_paths.get((description_category_id, type_id), "")
    brand = scalar_text(first_value(item, ("brand", "brand_name", "manufacturer_brand")))
    if not brand:
        brand = attribute_value(item.get("attributes"), {"бренд", "brand"})
    barcode = scalar_text(first_value(item, ("barcode", "barcodes")))

    return {
        "Артикул продавца": scalar_text(item.get("offer_id")),
        "Ozon Product ID": scalar_text(first_value(item, ("product_id", "id"))),
        "Ozon SKU": scalar_text(item.get("sku")),
        "Штрихкод": barcode,
        "Название товара": scalar_text(item.get("name")),
        "Бренд": brand,
        "Категория": category,
        "Тип товара": product_type,
        "ID категории Ozon": description_category_id,
        "ID типа Ozon": type_id,
        "Статус": scalar_text(first_value(item, ("status", "state"))),
    }


def write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Выгрузка каталога Ozon Seller API")
    parser.add_argument("--out", type=Path, default=Path("Данные_Ozon"), help="папка результатов")
    parser.add_argument("--page-size", type=int, default=1000, help="число товаров на страницу")
    args = parser.parse_args()

    client_id = os.environ.get("OZON_CLIENT_ID", "").strip()
    api_key = os.environ.get("OZON_API_KEY", "").strip()
    if not client_id or not api_key:
        print(
            "Задайте OZON_CLIENT_ID и OZON_API_KEY в окружении текущего процесса; "
            "скрипт не принимает и не сохраняет их в файлы.",
            file=sys.stderr,
        )
        return 2
    if not 1 <= args.page_size <= 1000:
        parser.error("--page-size должен быть от 1 до 1000")

    try:
        client = OzonClient(client_id, api_key)
        listed = product_list(client, args.page_size)
        detailed = product_details(client, listed)
        try:
            category_paths, type_paths = load_category_paths(client)
        except OzonAPIError as exc:
            print(f"Предупреждение: дерево категорий Ozon недоступно ({exc}); использую данные карточек.", file=sys.stderr)
            category_paths, type_paths = {}, {}

        rows = [normalize_product(item, category_paths, type_paths) for item in detailed]
        rows.sort(key=lambda row: (row["Бренд"].casefold(), row["Артикул продавца"].casefold()))

        args.out.mkdir(parents=True, exist_ok=True)
        columns = [
            "Артикул продавца",
            "Ozon Product ID",
            "Ozon SKU",
            "Штрихкод",
            "Название товара",
            "Бренд",
            "Категория",
            "Тип товара",
            "ID категории Ozon",
            "ID типа Ozon",
            "Статус",
        ]
        write_csv(args.out / "catalog.csv", rows, columns)

        brand_counts = Counter(row["Бренд"] or "Бренд не указан в API" for row in rows)
        brand_rows = [
            {"Бренд": brand, "Количество артикулов": str(count)}
            for brand, count in sorted(brand_counts.items(), key=lambda pair: pair[0].casefold())
        ]
        write_csv(args.out / "brands.csv", brand_rows, ["Бренд", "Количество артикулов"])

        category_counts = Counter(row["Категория"] or "Категория не указана в API" for row in rows)
        category_rows = [
            {"Категория": category, "Количество артикулов": str(count)}
            for category, count in sorted(category_counts.items(), key=lambda pair: pair[0].casefold())
        ]
        write_csv(args.out / "categories.csv", category_rows, ["Категория", "Количество артикулов"])

        metadata = {
            "exported_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": "Ozon Seller API",
            "product_count": len(rows),
            "unique_seller_articles": len({row["Артикул продавца"] for row in rows if row["Артикул продавца"]}),
            "brand_count": len(brand_counts),
            "category_count": len(category_counts),
            "products": rows,
        }
        (args.out / "catalog.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"Готово: {len(rows)} товаров, {metadata['unique_seller_articles']} уникальных артикулов, "
            f"{len(brand_counts)} брендов, {len(category_counts)} категорий."
        )
        print(f"Результаты: {args.out.resolve()}")
    except OzonAPIError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
