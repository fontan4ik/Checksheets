#!/usr/bin/env python3
"""Download a local Ozon Performance SKU report and summarize real clicks/spend.

Read-only diagnostic helper for VOL-2073.
- Uses credentials from ../config.py
- Saves raw report + extracted CSV blocks under test/tmp/
- Aggregates real ad metrics by SKU locally (clicks, impressions, spend, orders, revenue)
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEST_TMP = ROOT / "test" / "tmp"
CONFIG_PATH = ROOT / "config.py"


def load_config():
    spec = importlib.util.spec_from_file_location("checksheets_config", CONFIG_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load config from {CONFIG_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONFIG = load_config()
BASE_URL = str(CONFIG.OZON_PERF_BASE_URL).rstrip("/")
PAYMENT_TYPES = {
    x.strip().upper()
    for x in os.getenv("OZON_PERF_PAYMENT_TYPES", "CPC").split(",")
    if x.strip()
}
CAMPAIGN_STATES = {
    x.strip().upper()
    for x in os.getenv("OZON_PERF_CAMPAIGN_STATES", "").split(",")
    if x.strip()
}
MAX_CAMPAIGNS_PER_REPORT = int(os.getenv("OZON_PERF_MAX_CAMPAIGNS_PER_REPORT", "10"))
MAX_SELECTED_CAMPAIGNS = int(os.getenv("OZON_PERF_MAX_SELECTED_CAMPAIGNS", "0"))
CREATE_REPORT_RETRIES = int(os.getenv("OZON_PERF_CREATE_REPORT_RETRIES", "30"))
CREATE_REPORT_RETRY_SLEEP = int(os.getenv("OZON_PERF_CREATE_REPORT_RETRY_SLEEP", "10"))


def default_period() -> tuple[str, str]:
    env_from = os.getenv("OZON_PERF_DATE_FROM", "").strip()
    env_to = os.getenv("OZON_PERF_DATE_TO", "").strip()
    if env_from and env_to:
        return env_from, env_to

    today = date.today()
    date_to = today - timedelta(days=1)
    date_from = date_to - timedelta(days=29)
    return date_from.isoformat(), date_to.isoformat()


DATE_FROM, DATE_TO = default_period()
STAMP = datetime.now().strftime("%Y%m%dT%H%M%S")
OUT_DIR = TEST_TMP / f"ozon_real_clicks_probe_{STAMP}"
CSV_DIR = OUT_DIR / "csv"


def ensure_dirs() -> None:
    CSV_DIR.mkdir(parents=True, exist_ok=True)


class HttpError(RuntimeError):
    pass


def request_json(method: str, path: str, body: dict[str, Any] | None = None, token: str | None = None) -> dict[str, Any]:
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        payload = e.read().decode("utf-8", errors="replace")
        raise HttpError(f"{method} {url} -> HTTP {e.code}: {payload[:1000]}") from e
    except urllib.error.URLError as e:
        raise HttpError(f"{method} {url} -> URL error: {e}") from e

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise HttpError(f"{method} {url} -> invalid JSON: {raw[:1000]}") from e



def request_bytes(method: str, path: str, token: str | None = None) -> bytes:
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        payload = e.read().decode("utf-8", errors="replace")
        raise HttpError(f"{method} {url} -> HTTP {e.code}: {payload[:1000]}") from e
    except urllib.error.URLError as e:
        raise HttpError(f"{method} {url} -> URL error: {e}") from e



def get_token() -> str:
    data = request_json(
        "POST",
        "/api/client/token",
        {
            "client_id": CONFIG.OZON_PERF_CLIENT_ID,
            "client_secret": CONFIG.OZON_PERF_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
    )
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Ozon Performance token missing in response")
    return token



def get_campaigns(token: str) -> list[dict[str, Any]]:
    data = request_json("GET", "/api/client/campaign", token=token)
    return list(data.get("list", []))



def filter_campaigns(campaigns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [c for c in campaigns if str(c.get("PaymentType", "")).upper() in PAYMENT_TYPES]
    if CAMPAIGN_STATES:
        selected = [c for c in selected if str(c.get("state", "")).upper() in CAMPAIGN_STATES]
    if MAX_SELECTED_CAMPAIGNS > 0:
        selected = selected[:MAX_SELECTED_CAMPAIGNS]
    return selected



def create_report(token: str, campaign_ids: list[int]) -> str:
    body = {
        "campaigns": campaign_ids,
        "dateFrom": DATE_FROM,
        "dateTo": DATE_TO,
        "groupBy": "SKU",
    }
    for attempt in range(1, CREATE_REPORT_RETRIES + 1):
        try:
            data = request_json("POST", "/api/client/statistics", body=body, token=token)
            uuid = data.get("UUID")
            if not uuid:
                raise RuntimeError(f"Report UUID missing: {data}")
            return str(uuid)
        except HttpError as exc:
            message = str(exc)
            if "максимум 1" not in message and "Превышен лимит активных запросов" not in message:
                raise
            if attempt >= CREATE_REPORT_RETRIES:
                raise
            print(
                f"create_report rate-limited by active report slot; "
                f"retry {attempt}/{CREATE_REPORT_RETRIES} in {CREATE_REPORT_RETRY_SLEEP}s"
            )
            time.sleep(CREATE_REPORT_RETRY_SLEEP)
    raise RuntimeError("Unreachable create_report retry loop")



def wait_report(token: str, uuid: str, attempts: int = 60, sleep_seconds: int = 5) -> tuple[dict[str, Any], bytes]:
    last_state = None
    report_url = f"/api/client/statistics/report?UUID={uuid}"
    last_status: dict[str, Any] = {"state": "UNKNOWN", "uuid": uuid}
    for attempt in range(1, attempts + 1):
        time.sleep(sleep_seconds)
        status = request_json("GET", f"/api/client/statistics/{uuid}", token=token)
        last_status = status
        state = status.get("state")
        if state != last_state:
            print(f"report_state[{attempt}]={state}")
            last_state = state
        if state == "OK" and status.get("link"):
            content = request_bytes("GET", str(status["link"]), token=token)
            return status, content
        try:
            content = request_bytes("GET", report_url, token=token)
            head = content[:200].lower()
            if content[:2] == b"PK" or b";" in head or b"sku" in head:
                print(f"report_download_ready[{attempt}]=direct")
                return status, content
        except HttpError as exc:
            message = str(exc)
            if "report not found" not in message and '"state":"NOT_STARTED"' not in message:
                raise
        if state == "ERROR":
            raise RuntimeError(f"Report generation failed: {status}")
    raise TimeoutError(f"Timeout waiting for report {uuid}; last_status={last_status}")



def unpack_blocks(raw: bytes) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for idx, name in enumerate(archive.namelist(), start=1):
                text = archive.read(name).decode("utf-8-sig", errors="replace")
                blocks.append((name or f"report_{idx}.csv", text))
    else:
        blocks.append(("report.csv", raw.decode("utf-8-sig", errors="replace")))
    return blocks



def normalize(value: str) -> str:
    return " ".join(str(value or "").replace("\ufeff", "").replace("\xa0", " ").strip().lower().split())



def find_header_row(rows: list[list[str]]) -> int:
    for idx, row in enumerate(rows[:20]):
        normalized = [normalize(cell) for cell in row]
        joined = " | ".join(normalized)
        if "sku" in normalized or ("sku" in joined and ("клик" in joined or "расход" in joined or "ctr" in joined)):
            return idx
    return 0



def detect_columns(headers: list[str]) -> dict[str, int]:
    normalized = [normalize(h) for h in headers]
    result = {
        "sku": -1,
        "article": -1,
        "clicks": -1,
        "impressions": -1,
        "ctr": -1,
        "spend": -1,
        "orders": -1,
        "revenue": -1,
    }
    for idx, h in enumerate(normalized):
        if h == "sku":
            result["sku"] = idx
        elif "артикул" in h or h == "offer id" or h == "offer_id":
            result["article"] = idx
        elif (h == "клики" or h == "clicks") and result["clicks"] == -1:
            result["clicks"] = idx
        elif ("показ" in h or h == "impressions") and result["impressions"] == -1:
            result["impressions"] = idx
        elif (h == "ctr" or "ctr" in h) and result["ctr"] == -1:
            result["ctr"] = idx
        elif (h.startswith("расход") or h == "spend" or h == "cost") and result["spend"] == -1:
            result["spend"] = idx
        elif (h == "заказы" or h == "orders" or h == "количество" or h == "продано товаров") and result["orders"] == -1:
            result["orders"] = idx
        elif (
            h == "продажи в продвижении, ₽"
            or h.startswith("стоимость")
            or h.startswith("выруч")
            or h == "revenue"
            or (h.startswith("продажи в продвижении") and result["revenue"] == -1)
        ):
            result["revenue"] = idx
    return result



def parse_number(value: str) -> float:
    cleaned = (
        str(value or "")
        .replace("\ufeff", "")
        .replace("\xa0", "")
        .replace(" ", "")
        .replace("₽", "")
        .replace("%", "")
        .replace(",", ".")
        .strip()
    )
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0



def parse_blocks(blocks: list[tuple[str, str]]) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    stats: dict[str, dict[str, float]] = {}
    block_summaries: list[dict[str, Any]] = []
    header_counter: Counter[str] = Counter()

    for block_index, (name, text) in enumerate(blocks, start=1):
        rows = list(csv.reader(io.StringIO(text), delimiter=';'))
        rows = [row for row in rows if any(cell.strip() for cell in row)]
        if not rows:
            continue
        header_row = find_header_row(rows)
        headers = rows[header_row]
        for header in headers:
            header_counter[normalize(header)] += 1
        columns = detect_columns(headers)

        row_count = 0
        matched_rows = 0
        for row in rows[header_row + 1:]:
            row_count += 1
            if not row or all(not cell.strip() for cell in row):
                continue
            first = normalize(row[0]) if row else ""
            if first in {"", "всего"}:
                continue
            if columns["sku"] < 0 or len(row) <= columns["sku"]:
                continue
            sku = str(row[columns["sku"]]).strip().strip('"')
            if not sku or normalize(sku) == "sku":
                continue

            bucket = stats.setdefault(
                sku,
                {
                    "clicks": 0.0,
                    "impressions": 0.0,
                    "ctr": 0.0,
                    "spend": 0.0,
                    "orders": 0.0,
                    "revenue": 0.0,
                    "rows": 0.0,
                },
            )
            for key in ("clicks", "impressions", "spend", "orders", "revenue"):
                idx = columns[key]
                if idx >= 0 and idx < len(row):
                    bucket[key] += parse_number(row[idx])
            ctr_idx = columns["ctr"]
            if ctr_idx >= 0 and ctr_idx < len(row):
                bucket["ctr"] += parse_number(row[ctr_idx])
            bucket["rows"] += 1
            matched_rows += 1

        block_summaries.append(
            {
                "block_index": block_index,
                "name": name,
                "header_row": header_row,
                "headers": headers,
                "columns": columns,
                "rows_scanned": row_count,
                "matched_rows": matched_rows,
            }
        )

    for bucket in stats.values():
        if bucket["rows"]:
            bucket["ctr_avg"] = bucket["ctr"] / bucket["rows"]
        else:
            bucket["ctr_avg"] = 0.0

    summary = {
        "block_count": len(block_summaries),
        "block_summaries": block_summaries,
        "header_frequencies": header_counter.most_common(50),
    }
    return stats, summary



def merge_stats(target: dict[str, dict[str, float]], source: dict[str, dict[str, float]]) -> None:
    for sku, source_bucket in source.items():
        bucket = target.setdefault(
            sku,
            {
                "clicks": 0.0,
                "impressions": 0.0,
                "ctr": 0.0,
                "spend": 0.0,
                "orders": 0.0,
                "revenue": 0.0,
                "rows": 0.0,
                "ctr_avg": 0.0,
            },
        )
        for key in ("clicks", "impressions", "ctr", "spend", "orders", "revenue", "rows"):
            bucket[key] += float(source_bucket.get(key, 0.0))


def save_batch_artifacts(batch_number: int, report_status: dict[str, Any], raw: bytes, blocks: list[tuple[str, str]]) -> str:
    batch_dir = OUT_DIR / "batches" / f"batch_{batch_number:02d}"
    csv_dir = batch_dir / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "report_status.json").write_text(json.dumps(report_status, ensure_ascii=False, indent=2), encoding="utf-8")
    (batch_dir / "report_raw.bin").write_bytes(raw)
    for idx, (name, text) in enumerate(blocks, start=1):
        safe_name = pathlib.Path(name).name or f"report_{idx}.csv"
        (csv_dir / safe_name).write_text(text, encoding="utf-8")
    return str(batch_dir)


def write_outputs(stats: dict[str, dict[str, float]], batch_details: list[dict[str, Any]], all_campaigns: list[dict[str, Any]], selected_campaigns: list[dict[str, Any]]) -> None:
    ensure_dirs()

    top_rows = sorted(
        (
            {
                "sku": sku,
                "clicks": round(data.get("clicks", 0.0), 4),
                "impressions": round(data.get("impressions", 0.0), 4),
                "ctr_avg": round(data.get("ctr_avg", 0.0), 4),
                "spend": round(data.get("spend", 0.0), 4),
                "orders": round(data.get("orders", 0.0), 4),
                "revenue": round(data.get("revenue", 0.0), 4),
            }
            for sku, data in stats.items()
        ),
        key=lambda row: (-row["clicks"], -row["spend"], row["sku"]),
    )

    with (OUT_DIR / "sku_summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["sku", "clicks", "impressions", "ctr_avg", "spend", "orders", "revenue"])
        writer.writeheader()
        writer.writerows(top_rows)

    totals = {
        "sku_count": len(stats),
        "total_clicks": round(sum(row["clicks"] for row in top_rows), 4),
        "total_impressions": round(sum(row["impressions"] for row in top_rows), 4),
        "total_spend": round(sum(row["spend"] for row in top_rows), 4),
        "total_orders": round(sum(row["orders"] for row in top_rows), 4),
        "total_revenue": round(sum(row["revenue"] for row in top_rows), 4),
    }

    overall = {
        "period": {"from": DATE_FROM, "to": DATE_TO},
        "payment_types_filter": sorted(PAYMENT_TYPES),
        "campaign_states_filter": sorted(CAMPAIGN_STATES),
        "max_campaigns_per_report": MAX_CAMPAIGNS_PER_REPORT,
        "campaign_count_total": len(all_campaigns),
        "campaign_count_selected": len(selected_campaigns),
        "selected_payment_types": dict(Counter(str(c.get("PaymentType", "")) for c in selected_campaigns)),
        "totals": totals,
        "artifacts": {
            "out_dir": str(OUT_DIR),
            "batches_dir": str(OUT_DIR / "batches"),
            "sku_summary": str(OUT_DIR / "sku_summary.csv"),
        },
        "batch_details": batch_details,
        "top_20_by_clicks": top_rows[:20],
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(overall, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "period": overall["period"],
        "payment_types_filter": overall["payment_types_filter"],
        "campaign_states_filter": overall["campaign_states_filter"],
        "campaign_count_total": overall["campaign_count_total"],
        "campaign_count_selected": overall["campaign_count_selected"],
        "totals": totals,
        "top_5_by_clicks": top_rows[:5],
        "out_dir": str(OUT_DIR),
    }, ensure_ascii=False, indent=2))



def main() -> int:
    ensure_dirs()
    print(f"Output dir: {OUT_DIR}")
    print(f"Period: {DATE_FROM} -> {DATE_TO}")
    print(f"Payment types filter: {sorted(PAYMENT_TYPES)}")
    print(f"Max campaigns per report: {MAX_CAMPAIGNS_PER_REPORT}")

    token = get_token()
    print("Token received: yes")
    all_campaigns = get_campaigns(token)
    selected_campaigns = filter_campaigns(all_campaigns)
    print(f"Campaigns total={len(all_campaigns)}, selected={len(selected_campaigns)}")
    if not selected_campaigns:
        raise RuntimeError("No campaigns matched selected payment types")

    merged_stats: dict[str, dict[str, float]] = {}
    batch_details: list[dict[str, Any]] = []

    for batch_number, start in enumerate(range(0, len(selected_campaigns), MAX_CAMPAIGNS_PER_REPORT), start=1):
        batch = selected_campaigns[start:start + MAX_CAMPAIGNS_PER_REPORT]
        batch_ids = [int(c["id"]) for c in batch]
        print(f"Batch {batch_number}: campaigns={len(batch_ids)} ids={batch_ids[:3]}{'...' if len(batch_ids) > 3 else ''}")
        report_uuid = create_report(token, batch_ids)
        print(f"Batch {batch_number} UUID: {report_uuid}")
        report_status, raw = wait_report(token, report_uuid)
        print(f"Batch {batch_number} bytes: {len(raw)}")

        blocks = unpack_blocks(raw)
        print(f"Batch {batch_number} CSV blocks: {len(blocks)}")
        stats, summary = parse_blocks(blocks)
        merge_stats(merged_stats, stats)
        batch_dir = save_batch_artifacts(batch_number, report_status, raw, blocks)
        batch_details.append(
            {
                "batch_number": batch_number,
                "campaign_ids": batch_ids,
                "campaign_count": len(batch_ids),
                "report_uuid": report_uuid,
                "artifact_dir": batch_dir,
                "sku_count": len(stats),
                "parser_summary": summary,
            }
        )

    for bucket in merged_stats.values():
        rows = bucket.get("rows", 0.0)
        bucket["ctr_avg"] = bucket.get("ctr", 0.0) / rows if rows else 0.0

    write_outputs(merged_stats, batch_details, all_campaigns, selected_campaigns)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - diagnostic script
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
