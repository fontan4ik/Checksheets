# -*- coding: utf-8 -*-
import json
import logging
import os
import sys
import time
import argparse

import requests
from openpyxl import Workbook

import config
from etm_sync_multi_store import create_etm_session, login_etm


LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "etm_export_codes.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

JOB_POLL_SECONDS = 60
JOB_MAX_ATTEMPTS = 180
SHEETS_BATCH_SIZE = 5000


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8", mode="w"),
        logging.StreamHandler(sys.stdout),
    ],
)


def create_sggds_job(http, headers, session_id):
    job_id = str(config.ETM_SGGDS_JOB_ID).strip()
    url = f"https://ipro.etm.ru/api/v1/job/create/{job_id}?session-id={session_id}"
    response = http.post(url, headers=headers, timeout=60)
    response.raise_for_status()

    payload = response.json()
    status = payload.get("status", {})
    if status.get("code") != 200:
        raise RuntimeError(f"ETM job create failed: {status.get('message') or payload}")

    uuid = payload.get("data", {}).get("uuid")
    if not uuid:
        raise RuntimeError(f"ETM job create returned no uuid: {payload}")

    logging.info("Created ETM SgGds job: %s", uuid)
    return uuid


def wait_for_job_url(http, headers, session_id, uuid):
    url = f"https://ipro.etm.ru/api/v1/job/{uuid}?session-id={session_id}"

    for attempt in range(1, JOB_MAX_ATTEMPTS + 1):
        response = http.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status", {})
        if status.get("code") != 200:
            raise RuntimeError(
                f"ETM job status failed: {status.get('message') or payload}"
            )

        rows = payload.get("data", {}).get("rows", [])
        if rows:
            row = rows[0]
            state = str(row.get("state", ""))
            state_desc = row.get("state_desc", "")
            urls = row.get("urls", [])
            for item in urls:
                download_url = item.get("url", "").strip()
                if download_url:
                    logging.info(
                        "ETM job ready on attempt %s: state=%s %s",
                        attempt,
                        state,
                        state_desc,
                    )
                    return download_url

            if state == "2":
                raise RuntimeError(
                    f"ETM job finished with error: {row.get('msg') or state_desc}"
                )

            logging.info(
                "Waiting for ETM job %s: attempt=%s/%s state=%s %s",
                uuid,
                attempt,
                JOB_MAX_ATTEMPTS,
                state,
                state_desc,
            )
        else:
            logging.info(
                "Waiting for ETM job %s: empty rows, attempt=%s/%s",
                uuid,
                attempt,
                JOB_MAX_ATTEMPTS,
            )

        time.sleep(JOB_POLL_SECONDS)

    raise TimeoutError(f"Timed out waiting for ETM job {uuid}")


def download_json_payload(http, headers, url):
    response = http.get(url, headers=headers, timeout=300)
    response.raise_for_status()
    return response.json()


def extract_records(payload):
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("rows"), list):
            records = payload.get("rows", [])
        elif isinstance(payload.get("data"), list):
            records = payload.get("data", [])
        elif isinstance(payload.get("data"), dict) and isinstance(
            payload["data"].get("rows"), list
        ):
            records = payload["data"].get("rows", [])
        else:
            raise RuntimeError(
                f"Unsupported ETM export JSON structure: {json.dumps(payload)[:1000]}"
            )
    else:
        raise RuntimeError(f"Unsupported ETM export payload type: {type(payload)}")

    result = []
    for item in records:
        article = str(item.get("article", "") or "").strip()
        etm_code = str(item.get("id", "") or "").strip()
        if not article or not etm_code:
            continue
        result.append([article, etm_code])

    result.sort(key=lambda row: (row[0], row[1]))
    return result


def write_sheet_rows(rows):
    import gsheets_utils

    ws = gsheets_utils.get_worksheet(config.ETM_CODES_SHEET_NAME)
    required_rows = max(len(rows) + 1, 1)

    if ws.row_count < required_rows:
        ws.resize(rows=required_rows, cols=max(ws.col_count, 2))
        logging.info("Resized Google Sheet to %s rows", required_rows)

    ws.clear()
    ws.update(range_name="A1:B1", values=[["Артикул", "Код ETM"]])

    if not rows:
        logging.warning("No ETM code rows to write")
        return 0

    for offset in range(0, len(rows), SHEETS_BATCH_SIZE):
        chunk = rows[offset : offset + SHEETS_BATCH_SIZE]
        start_row = offset + 2
        end_row = start_row + len(chunk) - 1
        range_name = f"A{start_row}:B{end_row}"
        ws.update(range_name=range_name, values=chunk)
        logging.info("Wrote rows %s-%s to Google Sheets", start_row, end_row)

    return len(rows)


def export_etm_codes():
    start_time = time.time()
    headers = {"Accept": "application/json"}
    http = create_etm_session()

    logging.info("Starting ETM codes export")
    session_id, login_data = login_etm(http, headers)
    if not session_id:
        raise RuntimeError(f"Could not obtain ETM session: {login_data}")

    uuid = create_sggds_job(http, headers, session_id)
    download_url = wait_for_job_url(http, headers, session_id, uuid)
    logging.info("Downloading ETM codes JSON: %s", download_url)

    payload = download_json_payload(http, headers, download_url)
    rows = extract_records(payload)
    count = write_sheet_rows(rows)

    logging.info(
        "Finished ETM codes export: %s rows in %.1fs", count, time.time() - start_time
    )


def import_etm_codes_from_url(download_url):
    start_time = time.time()
    headers = {"Accept": "application/json"}
    http = create_etm_session()

    logging.info("Starting ETM codes import from prepared URL")
    logging.info("Downloading ETM codes JSON: %s", download_url)

    payload = download_json_payload(http, headers, download_url)
    rows = extract_records(payload)
    count = write_sheet_rows(rows)

    logging.info(
        "Finished ETM codes import from URL: %s rows in %.1fs",
        count,
        time.time() - start_time,
    )


def write_xlsx_rows(rows, xlsx_path):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = config.ETM_CODES_SHEET_NAME
    worksheet.append(["Артикул", "Код ETM"])

    for row in rows:
        worksheet.append(row)

    worksheet.column_dimensions["A"].width = 30
    worksheet.column_dimensions["B"].width = 18
    workbook.save(xlsx_path)
    logging.info("Saved Excel file: %s", xlsx_path)


def export_etm_codes_to_xlsx(download_url, xlsx_path):
    start_time = time.time()
    headers = {"Accept": "application/json"}
    http = create_etm_session()

    logging.info("Starting ETM codes export to Excel")
    logging.info("Downloading ETM codes JSON: %s", download_url)

    payload = download_json_payload(http, headers, download_url)
    rows = extract_records(payload)
    write_xlsx_rows(rows, xlsx_path)

    logging.info(
        "Finished ETM codes Excel export: %s rows in %.1fs",
        len(rows),
        time.time() - start_time,
    )


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--download-url", dest="download_url", help="Ready ETM JSON report URL"
    )
    parser.add_argument(
        "--xlsx-path", dest="xlsx_path", help="Write ETM codes to local .xlsx file"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.download_url and args.xlsx_path:
        export_etm_codes_to_xlsx(args.download_url, args.xlsx_path)
    elif args.download_url:
        import_etm_codes_from_url(args.download_url)
    else:
        export_etm_codes()
