#!/usr/bin/env python3
"""
Copy a subset of Ozon product cards from one seller cabinet to another.

What it does:
1. Reads offer IDs from column A of an .xlsx file.
2. Loads source card data from the source cabinet using official Ozon Seller API.
3. Rebuilds import payloads for the target cabinet.
4. Sends product imports in batches and polls task status.

Official Ozon API notes reflected here:
- /v3/product/import accepts up to 100 items per request.
- /v1/product/import/info is used to check asynchronous import status by task_id.
- Ozon currently allows up to 50 requests/sec per Client ID, but the script
  defaults to a safer lower rate.
- items.type_id is required in /v3/product/import.
- Images must be public URLs and should be JPG or PNG.

This script is intentionally conservative:
- It skips rows that do not have the required source fields.
- It reports validation problems before upload.
- It retries transient network/server errors with backoff.

The implementation uses only the Python standard library, so it can run in the
current environment without extra dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET


API_BASE_URL = "https://api-seller.ozon.ru"
DEFAULT_SOURCE_BATCH_SIZE = 1000
DEFAULT_IMPORT_BATCH_SIZE = 100
DEFAULT_SAFE_RPS = 20.0
MAX_DOC_RPS = 50.0
REQUEST_TIMEOUT = 90

NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


@dataclass
class ParsedCard:
    offer_id: str
    raw: dict[str, Any]
    source_status: str = ""
    source_errors: list[str] = field(default_factory=list)
    import_item: dict[str, Any] = field(default_factory=dict)

    @property
    def is_ready(self) -> bool:
        return not self.source_errors and bool(self.import_item)


class OzonApiError(RuntimeError):
    pass


class RateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        self.interval = 0 if requests_per_second <= 0 else 1.0 / requests_per_second
        self._last = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        now = time.monotonic()
        if self._last:
            remaining = self.interval - (now - self._last)
            if remaining > 0:
                time.sleep(remaining)
        self._last = time.monotonic()


def chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\ufeff", "").strip()
    return text


def to_number(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return value
    text = normalize_text(value)
    if not text:
        return None
    text = text.replace(" ", "").replace("\xa0", "").replace(",", ".")
    try:
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        return float(text)
    except ValueError:
        return value


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple, dict)) and not value:
            continue
        return value
    return None


def ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def resolve_xlsx_sheet_path(xlsx_path: Path, sheet_name: str | None) -> str:
    with zipfile.ZipFile(xlsx_path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels.findall(f"{NS_REL}Relationship")
        }

        sheets = workbook.find(f"{NS_MAIN}sheets")
        if sheets is None:
            raise RuntimeError("Workbook has no sheets")

        selected_target = None
        for sheet in sheets.findall(f"{NS_MAIN}sheet"):
            current_name = sheet.attrib.get("name", "")
            r_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            if not r_id or r_id not in rel_map:
                continue
            if sheet_name is None:
                selected_target = rel_map[r_id]
                break
            if current_name == sheet_name:
                selected_target = rel_map[r_id]
                break

        if selected_target is None:
            available = ", ".join(sheet.attrib.get("name", "") for sheet in sheets.findall(f"{NS_MAIN}sheet"))
            raise RuntimeError(
                f"Sheet '{sheet_name}' was not found. Available sheets: {available or 'none'}"
            )

        return selected_target.lstrip("/")


def read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []

    values: list[str] = []
    for si in shared.findall(f"{NS_MAIN}si"):
        parts: list[str] = []
        for node in si.iter():
            if node.tag == f"{NS_MAIN}t" and node.text:
                parts.append(node.text)
        values.append("".join(parts))
    return values


def read_excel_column_a(xlsx_path: Path, sheet_name: str | None = None) -> list[str]:
    with zipfile.ZipFile(xlsx_path) as archive:
        sheet_path = resolve_xlsx_sheet_path(xlsx_path, sheet_name)
        shared_strings = read_shared_strings(archive)
        root = ET.fromstring(archive.read(f"xl/{sheet_path}" if not sheet_path.startswith("xl/") else sheet_path))

    rows: list[str] = []
    sheet_data = root.find(f"{NS_MAIN}sheetData")
    if sheet_data is None:
        return rows

    for row in sheet_data.findall(f"{NS_MAIN}row"):
        cell_a = None
        for cell in row.findall(f"{NS_MAIN}c"):
            ref = cell.attrib.get("r", "")
            if ref.startswith("A"):
                cell_a = cell
                break

        if cell_a is None:
            continue

        value = ""
        cell_type = cell_a.attrib.get("t", "")
        if cell_type == "s":
            v = cell_a.find(f"{NS_MAIN}v")
            if v is not None and v.text is not None:
                idx = int(v.text)
                value = shared_strings[idx] if 0 <= idx < len(shared_strings) else ""
        elif cell_type == "inlineStr":
            parts: list[str] = []
            for node in cell_a.iter():
                if node.tag == f"{NS_MAIN}t" and node.text:
                    parts.append(node.text)
            value = "".join(parts)
        else:
            v = cell_a.find(f"{NS_MAIN}v")
            if v is not None and v.text is not None:
                value = v.text
            else:
                is_node = cell_a.find(f"{NS_MAIN}is")
                if is_node is not None:
                    parts = [node.text for node in is_node.iter() if node.tag == f"{NS_MAIN}t" and node.text]
                    value = "".join(parts)

        value = normalize_text(value)
        if value:
            rows.append(value)

    return rows


def build_headers(client_id: str, api_key: str) -> dict[str, str]:
    return {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def request_json(
    path: str,
    payload: dict[str, Any],
    client_id: str,
    api_key: str,
    *,
    timeout: int = REQUEST_TIMEOUT,
    max_attempts: int = 5,
    retry_sleep: float = 1.5,
) -> dict[str, Any]:
    url = path if path.startswith("http") else f"{API_BASE_URL}{path}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = build_headers(client_id, api_key)

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if exc.code in {429, 500, 502, 503, 504} and attempt < max_attempts:
                sleep_for = retry_sleep * attempt
                if retry_after:
                    try:
                        sleep_for = max(sleep_for, float(retry_after))
                    except ValueError:
                        pass
                time.sleep(sleep_for)
                last_error = OzonApiError(
                    f"{path} returned HTTP {exc.code}: {raw[:500] or exc.reason}"
                )
                continue
            raise OzonApiError(f"{path} returned HTTP {exc.code}: {raw[:1000] or exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            if attempt < max_attempts:
                time.sleep(retry_sleep * attempt)
                last_error = exc
                continue
            raise OzonApiError(f"{path} failed after {max_attempts} attempts: {exc}") from exc

    if last_error is not None:
        raise OzonApiError(f"{path} failed: {last_error}")
    raise OzonApiError(f"{path} failed with an unknown error")


def extract_list_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    result = data.get("result")
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ("items", "result", "products"):
            items = result.get(key)
            if isinstance(items, list):
                return items
    for key in ("items", "result"):
        items = data.get(key)
        if isinstance(items, list):
            return items
        if isinstance(items, dict):
            nested = items.get("items")
            if isinstance(nested, list):
                return nested
    return []


def fetch_source_cards(
    offer_ids: list[str],
    client_id: str,
    api_key: str,
    *,
    limiter: RateLimiter,
) -> dict[str, ParsedCard]:
    cards: dict[str, ParsedCard] = {}

    for batch in chunked(offer_ids, DEFAULT_SOURCE_BATCH_SIZE):
        limiter.wait()
        payload = {
            "filter": {"offer_id": batch},
            "limit": len(batch),
        }
        data = request_json("/v4/product/info/attributes", payload, client_id, api_key)
        items = extract_list_response(data)

        for item in items:
            offer_id = normalize_text(item.get("offer_id"))
            if not offer_id:
                continue

            card = ParsedCard(offer_id=offer_id, raw=item)
            normalized = build_import_item(item)
            card.import_item = normalized["item"]
            card.source_status = normalized["status"]
            card.source_errors = normalized["errors"]
            cards[offer_id] = card

    return cards


def pick_price(item: dict[str, Any]) -> Any:
    price_value = item.get("price")
    candidates: list[Any] = []
    if isinstance(price_value, dict):
        candidates.extend(
            [
                price_value.get("price"),
                price_value.get("net_price"),
                price_value.get("value"),
            ]
        )
    else:
        candidates.append(price_value)

    candidates.extend([item.get("old_price"), item.get("price_value")])
    for candidate in candidates:
        number = to_number(candidate)
        if number is not None:
            return number
    return None


def pick_images(item: dict[str, Any]) -> list[str]:
    images = ensure_list(item.get("images"))
    if not images:
        images = ensure_list(item.get("primary_image"))
    cleaned: list[str] = []
    for image in images:
        text = normalize_text(image)
        if text:
            cleaned.append(text)
    return cleaned


def pick_barcode(item: dict[str, Any]) -> str:
    candidates = [
        item.get("barcode"),
        item.get("barcodes"),
        item.get("barcode_list"),
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            for entry in candidate:
                text = normalize_text(entry)
                if text:
                    return text
        else:
            text = normalize_text(candidate)
            if text:
                return text
    return ""


def pick_dimensions(item: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("depth", "width", "height", "weight", "volume_weight"):
        value = to_number(first_non_empty(item.get(key), item.get(key, {}).get("value") if isinstance(item.get(key), dict) else None))
        if value is not None:
            result[key] = value
    for key in ("dimension_unit", "weight_unit", "currency_code"):
        value = normalize_text(item.get(key))
        if value:
            result[key] = value
    return result


def pick_description(item: dict[str, Any]) -> str:
    for key in ("description", "rich_description", "short_description"):
        value = normalize_text(item.get(key))
        if value:
            return value
    return ""


def normalize_attributes(source_attributes: Any) -> list[dict[str, Any]]:
    attributes: list[dict[str, Any]] = []
    for attr in ensure_list(source_attributes):
        if not isinstance(attr, dict):
            continue

        attr_id = first_non_empty(
            attr.get("id"),
            attr.get("attribute_id"),
            attr.get("description_category_attribute_id"),
        )
        if attr_id is None:
            continue

        normalized_attr: dict[str, Any] = {
            "id": attr_id,
        }

        if "complex_id" in attr and attr.get("complex_id") is not None:
            normalized_attr["complex_id"] = attr.get("complex_id")
        elif "attribute_complex_id" in attr and attr.get("attribute_complex_id") is not None:
            normalized_attr["complex_id"] = attr.get("attribute_complex_id")
        else:
            normalized_attr["complex_id"] = 0

        values: list[dict[str, Any]] = []
        raw_values = ensure_list(attr.get("values"))
        if not raw_values and attr.get("value") not in (None, ""):
            raw_values = [attr.get("value")]

        for value in raw_values:
            if isinstance(value, dict):
                new_value: dict[str, Any] = {}
                for key in ("value", "dictionary_value_id", "name", "type", "slug"):
                    if key in value and value.get(key) not in (None, ""):
                        new_value[key] = value.get(key)
                if new_value:
                    values.append(new_value)
            else:
                text = normalize_text(value)
                if text:
                    values.append({"value": text})

        if values:
            normalized_attr["values"] = values
            attributes.append(normalized_attr)

    return attributes


def build_import_item(item: dict[str, Any]) -> dict[str, Any]:
    offer_id = normalize_text(item.get("offer_id"))
    description_category_id = first_non_empty(
        item.get("description_category_id"),
        item.get("category_id"),
        item.get("description_category", {}).get("id") if isinstance(item.get("description_category"), dict) else None,
    )
    type_id = first_non_empty(
        item.get("type_id"),
        item.get("type", {}).get("id") if isinstance(item.get("type"), dict) else None,
    )

    errors: list[str] = []
    if not offer_id:
        errors.append("missing offer_id")
    if description_category_id is None:
        errors.append("missing description_category_id")
    if type_id is None:
        errors.append("missing type_id")

    price = pick_price(item)
    if price is None:
        errors.append("missing price")

    images = pick_images(item)
    if not images:
        errors.append("missing images")

    dimensions = pick_dimensions(item)
    if not all(key in dimensions for key in ("depth", "width", "height", "weight")):
        errors.append("missing dimensions or weight")

    barcode = pick_barcode(item)
    if not barcode:
        errors.append("missing barcode")

    attributes = normalize_attributes(item.get("attributes"))
    if not attributes:
        errors.append("missing attributes")

    payload: dict[str, Any] = {
        "offer_id": offer_id,
        "description_category_id": description_category_id,
        "type_id": type_id,
        "price": price,
        "images": images,
        "attributes": attributes,
    }

    name = normalize_text(item.get("name"))
    if name:
        payload["name"] = name

    description = pick_description(item)
    if description:
        payload["description"] = description

    if barcode:
        payload["barcode"] = barcode

    vat = first_non_empty(item.get("vat"), item.get("tax"), item.get("vat_rate"))
    if vat not in (None, ""):
        payload["vat"] = vat

    currency_code = normalize_text(item.get("currency_code")) or "RUB"
    payload["currency_code"] = currency_code

    old_price = first_non_empty(item.get("old_price"), item.get("price_old"))
    if old_price not in (None, ""):
        normalized_old_price = to_number(old_price)
        if normalized_old_price is not None:
            payload["old_price"] = normalized_old_price

    for key, value in dimensions.items():
        if key in {"currency_code"}:
            continue
        payload[key] = value

    return {"item": payload, "errors": errors, "status": "ready" if not errors else "skipped"}


def summarize_cards(cards: dict[str, ParsedCard]) -> None:
    ready = sum(1 for card in cards.values() if card.is_ready)
    skipped = len(cards) - ready
    print(f"Loaded source cards: {len(cards)}")
    print(f"Ready to import:     {ready}")
    print(f"Skipped by validator:{skipped}")


def build_import_batches(
    cards: dict[str, ParsedCard],
    ordered_offer_ids: list[str],
    batch_size: int,
) -> list[list[dict[str, Any]]]:
    items = [cards[offer_id].import_item for offer_id in ordered_offer_ids if offer_id in cards and cards[offer_id].is_ready]
    return [items[idx : idx + batch_size] for idx in range(0, len(items), batch_size)]


def import_batch(
    batch: list[dict[str, Any]],
    client_id: str,
    api_key: str,
    *,
    limiter: RateLimiter,
) -> dict[str, Any]:
    limiter.wait()
    payload = {"items": batch}
    return request_json("/v3/product/import", payload, client_id, api_key)


def fetch_import_status(
    task_id: Any,
    client_id: str,
    api_key: str,
    *,
    limiter: RateLimiter,
) -> dict[str, Any]:
    limiter.wait()
    payload = {"task_id": task_id}
    return request_json("/v1/product/import/info", payload, client_id, api_key)


def wait_for_task(
    task_id: Any,
    client_id: str,
    api_key: str,
    *,
    limiter: RateLimiter,
    poll_interval: float,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] = {}

    while time.monotonic() < deadline:
        last_payload = fetch_import_status(task_id, client_id, api_key, limiter=limiter)
        items = extract_list_response(last_payload)
        if items:
            statuses = {normalize_text(item.get("status")).lower() for item in items}
            if statuses and statuses <= {"imported"}:
                return last_payload
            if "failed" in statuses or "error" in statuses:
                return last_payload
        time.sleep(poll_interval)

    raise TimeoutError(f"Timed out waiting for import task {task_id}")


def report_validation(cards: dict[str, ParsedCard]) -> None:
    for card in cards.values():
        if card.source_errors:
            print(f"[SKIP] {card.offer_id}: {', '.join(card.source_errors)}")


def print_task_result(task_result: dict[str, Any]) -> None:
    items = extract_list_response(task_result)
    if not items:
        print("No task items returned by import/info.")
        print(json.dumps(task_result, ensure_ascii=False, indent=2))
        return

    for item in items:
        offer_id = normalize_text(item.get("offer_id"))
        status = normalize_text(item.get("status"))
        errors = item.get("errors") or []
        if errors:
            error_text = ", ".join(normalize_text(e) for e in errors if normalize_text(e))
        else:
            error_text = ""
        line = f"{offer_id}: {status}"
        if error_text:
            line += f" | {error_text}"
        print(line)


def collect_limit_hint(result: dict[str, Any]) -> str:
    if isinstance(result, dict):
        for key in ("limit", "quota", "total", "available"):
            if key in result:
                return f"{key}={result[key]}"
    return "limit info not returned"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy a subset of Ozon product cards from a source cabinet into a target cabinet."
    )
    parser.add_argument("--input", required=True, help="Path to .xlsx file with offer_id values in column A")
    parser.add_argument("--sheet", default=None, help="Optional sheet name. Default: first sheet")
    parser.add_argument(
        "--source-client-id",
        default=os.getenv("OZON_SOURCE_CLIENT_ID", ""),
        help="Source cabinet Client ID",
    )
    parser.add_argument(
        "--source-api-key",
        default=os.getenv("OZON_SOURCE_API_KEY", ""),
        help="Source cabinet API key",
    )
    parser.add_argument(
        "--target-client-id",
        default=os.getenv("OZON_TARGET_CLIENT_ID", ""),
        help="Target cabinet Client ID",
    )
    parser.add_argument(
        "--target-api-key",
        default=os.getenv("OZON_TARGET_API_KEY", ""),
        help="Target cabinet API key",
    )
    parser.add_argument(
        "--source-rps",
        type=float,
        default=min(DEFAULT_SAFE_RPS, MAX_DOC_RPS),
        help="Throttle for source requests. Default is conservative.",
    )
    parser.add_argument(
        "--target-rps",
        type=float,
        default=min(DEFAULT_SAFE_RPS, MAX_DOC_RPS),
        help="Throttle for target requests. Default is conservative.",
    )
    parser.add_argument(
        "--import-batch-size",
        type=int,
        default=DEFAULT_IMPORT_BATCH_SIZE,
        help="Items per /v3/product/import request (docs allow up to 100).",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="Seconds between import/info polls.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=1800,
        help="Maximum wait time for each import task.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not send imports, only validate and print payloads.")
    parser.add_argument(
        "--keep-duplicates",
        action="store_true",
        help="Keep duplicate offer_ids from the spreadsheet instead of deduplicating them.",
    )
    return parser.parse_args()


def validate_creds(label: str, client_id: str, api_key: str) -> None:
    if not client_id or not api_key:
        raise SystemExit(
            f"Missing {label} credentials. Provide --{label}-client-id and --{label}-api-key or set environment variables."
        )


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"Input file does not exist: {input_path}")
    if input_path.suffix.lower() != ".xlsx":
        raise SystemExit("Only .xlsx spreadsheets are supported.")

    validate_creds("source", args.source_client_id, args.source_api_key)
    validate_creds("target", args.target_client_id, args.target_api_key)

    offer_ids = read_excel_column_a(input_path, args.sheet)
    if not offer_ids:
        raise SystemExit("No offer IDs found in column A.")

    if not args.keep_duplicates:
        seen = set()
        unique_offer_ids: list[str] = []
        for offer_id in offer_ids:
            if offer_id in seen:
                continue
            seen.add(offer_id)
            unique_offer_ids.append(offer_id)
        duplicates = len(offer_ids) - len(unique_offer_ids)
        offer_ids = unique_offer_ids
        if duplicates:
            print(f"Deduplicated {duplicates} repeated offer_id values from the spreadsheet.")

    print(f"Input rows: {len(offer_ids)}")
    print(f"Source RPS: {args.source_rps}")
    print(f"Target RPS: {args.target_rps}")

    source_limiter = RateLimiter(args.source_rps)
    target_limiter = RateLimiter(args.target_rps)

    source_cards = fetch_source_cards(
        offer_ids,
        args.source_client_id,
        args.source_api_key,
        limiter=source_limiter,
    )

    missing = [offer_id for offer_id in offer_ids if offer_id not in source_cards]
    if missing:
        print(f"Source did not return {len(missing)} offer_id values.")
        for offer_id in missing[:20]:
            print(f"[MISS] {offer_id}")
        if len(missing) > 20:
            print(f"... and {len(missing) - 20} more")

    summarize_cards(source_cards)
    report_validation(source_cards)

    if args.dry_run:
        print("Dry run requested. Showing first payloads only.")
        for card in source_cards.values():
            if card.is_ready:
                print(json.dumps(card.import_item, ensure_ascii=False, indent=2))
                break
        return 0

    batches = build_import_batches(source_cards, offer_ids, args.import_batch_size)
    if not batches:
        raise SystemExit("No cards are ready for import.")

    print(f"Import batches: {len(batches)} (batch size <= {args.import_batch_size})")

    for index, batch in enumerate(batches, start=1):
        print(f"Sending batch {index}/{len(batches)} with {len(batch)} items...")
        response = import_batch(
            batch,
            args.target_client_id,
            args.target_api_key,
            limiter=target_limiter,
        )
        task_id = first_non_empty(
            response.get("result", {}).get("task_id") if isinstance(response.get("result"), dict) else None,
            response.get("task_id"),
        )
        if task_id is None:
            raise OzonApiError(f"Import response does not contain task_id: {json.dumps(response, ensure_ascii=False)[:1000]}")

        print(f"task_id: {task_id}")
        task_result = wait_for_task(
            task_id,
            args.target_client_id,
            args.target_api_key,
            limiter=target_limiter,
            poll_interval=args.poll_interval,
            timeout_seconds=args.timeout_seconds,
        )
        print_task_result(task_result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
