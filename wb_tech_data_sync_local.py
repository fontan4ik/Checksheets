import time
import requests
import config
import gsheets_utils

WB_CONTENT_BASE_URL = "https://content-api.wildberries.ru"
WB_TECH_SHEET_NAME = "ТЕХ данные wb"
WB_PAGE_LIMIT = 100
WB_SLEEP_SECONDS = 0.35
WB_REQUEST_TIMEOUT = 60
WB_MAX_RETRIES = 5


def wb_headers():
    return {
        "Authorization": "Bearer eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg2MDUyMTMxLCJpZCI6IjAxOWMyZDI4LTI0MzMtNzY2MC1iZDU4LTRlNjVhYzMwM2E0YiIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.fZu3j3YZBrIIEAZ6KtuWjTZ7HfPS3sR8Z6vOdmfT5L8hpQmjvVq3zf9Io-2wXTifmda46JEKhCZafyUlTUfpdA",
        "Content-Type": "application/json",
    }


def request_with_retry(session, method, url, **kwargs):
    for attempt in range(1, WB_MAX_RETRIES + 1):
        try:
            response = session.request(method, url, timeout=WB_REQUEST_TIMEOUT, **kwargs)
            if response.status_code < 500 and response.status_code != 429:
                return response
            print(f"   HTTP {response.status_code}, attempt {attempt}/{WB_MAX_RETRIES}")
            print(f"   Response: {response.text[:500]}")
        except requests.RequestException as exc:
            print(f"   Request error, attempt {attempt}/{WB_MAX_RETRIES}: {exc}")

        if attempt < WB_MAX_RETRIES:
            sleep_for = (2 ** attempt) * 1.5
            print(f"   Sleep {sleep_for:.1f}s before retry...")
            time.sleep(sleep_for)

    return None


def fetch_all_wb_cards():
    session = requests.Session()
    session.headers.update(wb_headers())

    all_cards = []
    cursor = None
    page = 0

    while True:
        page += 1
        payload = {
            "settings": {
                "sort": {"ascending": True},
                "cursor": {"limit": WB_PAGE_LIMIT},
            },
            "filter": {
                "withPhoto": -1,
            },
        }

        if cursor and cursor.get("updatedAt") and (cursor.get("nmID") or cursor.get("nmId")):
            payload["settings"]["cursor"] = {
                "limit": WB_PAGE_LIMIT,
                "updatedAt": cursor.get("updatedAt"),
                "nmID": cursor.get("nmID") or cursor.get("nmId"),
            }

        response = request_with_retry(
            session,
            "POST",
            f"{WB_CONTENT_BASE_URL}/content/v2/get/cards/list",
            json=payload,
        )

        if response is None:
            raise RuntimeError(f"WB Content API failed on page {page}")

        if response.status_code != 200:
            raise RuntimeError(f"WB Content API returned {response.status_code}: {response.text[:1000]}")

        data = response.json()
        cards = data.get("cards") or []
        if not cards:
            print(f"Page {page}: no cards, stop")
            break

        all_cards.extend(cards)
        print(f"Page {page}: +{len(cards)} cards, total {len(all_cards)}")

        next_cursor = data.get("cursor") or {}
        next_updated_at = next_cursor.get("updatedAt")
        next_nm_id = next_cursor.get("nmID") or next_cursor.get("nmId")

        if not next_updated_at or not next_nm_id:
            break

        if cursor and str(cursor.get("updatedAt")) == str(next_updated_at) and str(cursor.get("nmID") or cursor.get("nmId")) == str(next_nm_id):
            print("Cursor stopped moving, stop pagination")
            break

        cursor = next_cursor
        time.sleep(WB_SLEEP_SECONDS)

        if page >= 2000:
            raise RuntimeError("Safety limit reached while fetching WB cards")

    return all_cards


def build_rows(cards):
    rows = []
    seen = set()
    without_sizes = 0

    for card in cards:
        vendor_code = str(card.get("vendorCode") or "").strip()
        nm_id = card.get("nmID") or card.get("nmId")
        sizes = card.get("sizes") or []

        if not vendor_code or not nm_id:
            continue

        if not sizes:
            without_sizes += 1
            key = (vendor_code, "", str(nm_id))
            if key not in seen:
                seen.add(key)
                rows.append([vendor_code, "", str(nm_id)])
            continue

        for size in sizes:
            chrt_id = size.get("chrtID") or size.get("chrtId") or ""
            key = (vendor_code, str(chrt_id), str(nm_id))
            if key in seen:
                continue
            seen.add(key)
            rows.append([vendor_code, str(chrt_id) if chrt_id else "", str(nm_id)])

    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    return rows, without_sizes


def replace_sheet_contents(worksheet, rows):
    values = [["Артикул продавца", "Код размера (chrt_id)", "Артикул WB"]] + rows

    print(f"Clearing worksheet '{WB_TECH_SHEET_NAME}'...")
    worksheet.clear()

    chunk_size = 5000
    total_rows = len(values)
    total_chunks = (total_rows + chunk_size - 1) // chunk_size

    for idx in range(0, total_rows, chunk_size):
        chunk = values[idx: idx + chunk_size]
        start_row = idx + 1
        end_row = idx + len(chunk)
        range_label = f"A{start_row}:C{end_row}"
        chunk_num = idx // chunk_size + 1
        print(f"Updating chunk {chunk_num}/{total_chunks}: {range_label}")
        worksheet.update(range_label, chunk, value_input_option="RAW")
        time.sleep(0.4)



def sync_wb_tech_data():
    print("Starting WB tech data local sync...")

    worksheet = gsheets_utils.get_worksheet(WB_TECH_SHEET_NAME)
    cards = fetch_all_wb_cards()
    print(f"Fetched cards: {len(cards)}")

    rows, without_sizes = build_rows(cards)
    print(f"Prepared rows: {len(rows)}")
    print(f"Cards without sizes: {without_sizes}")

    replace_sheet_contents(worksheet, rows)

    print("WB tech data sync completed successfully!")
    print(f"Sheet: {WB_TECH_SHEET_NAME}")
    print(f"Rows written: {len(rows)}")


if __name__ == "__main__":
    sync_wb_tech_data()
