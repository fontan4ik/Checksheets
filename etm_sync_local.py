import time
from concurrent.futures import ThreadPoolExecutor

import requests

import config
import gsheets_utils


def get_etm_session():
    url = f"https://ipro.etm.ru/api/v1/user/login?log={config.ETM_LOGIN}&pwd={config.ETM_PASSWORD}"
    headers = {"Accept": "application/json"}
    try:
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            session_id = data.get("data", {}).get("session")
            if session_id:
                print(f"ETM Session obtained: {session_id}")
                return session_id
        print(f"ETM Login failed: {response.status_code} {response.text}")
    except Exception as e:
        print(f"ETM Login error: {e}")
    return None


def _build_article_variants(article):
    article = str(article).strip()
    if not article:
        return []

    variants = [article]

    # Keep the original article first because some ETM articles legitimately include dashes.
    # If the sheet stores marketplace-specific suffixes like "-1" / "-5", also try the
    # base article without the trailing numeric suffix.
    if "-" in article:
        base_article = article.rsplit("-", 1)[0]
        suffix = article.rsplit("-", 1)[1]
        if base_article and suffix.isdigit():
            variants.append(base_article)

    return list(dict.fromkeys(v for v in variants if v))


def _extract_samara_stock(info_stores, request_store_name=""):

    rc_stock = 0  # Stock from regional center (rc)
    op_stock_sum = 0  # Sum of stocks from offices of sales (op)

    aggregate_stock = 0

    for store in info_stores:
        store_name = (store.get("StoreName") or "").lower()

        store_type = (store.get("StoreType") or "").lower()

        # Check various possible fields that might contain stock information

        qty = store.get("StoreQuantRem")

        if qty is None:
            qty = store.get("StockRem")

        if qty is None:
            # Check for other possible field names that might contain quantity

            qty = store.get("QuantRem", 0)  # Additional potential field

        if qty is None:
            qty = 0

        is_samara = any(k in store_name for k in ["стройкерамика", "самар"])

        # Check if the overall request is for Samara

        is_request_for_samara = (
            "самар" in request_store_name.lower()
            or "стройкерамика" in request_store_name.lower()
        )

        # Separate handling for RC and OP stores
        if is_samara and store_type == "rc":
            rc_stock += qty
            continue
        elif is_samara and store_type == "op":
            op_stock_sum += qty
            continue

        # NEW: If we have an 'all' type with empty store name but request is for Samara, treat it as Samara stock

        if not store_name and store_type == "all" and is_request_for_samara:
            aggregate_stock = max(aggregate_stock, qty)

            continue

        # Fallback: some ETM responses expose the available quantity only in aggregate rows.

        if store_type == "rc2sum":
            aggregate_stock = max(aggregate_stock, qty)

        elif store_type == "all":
            aggregate_stock = max(aggregate_stock, qty)

    # If RC stock exists, return it; otherwise return sum of OP stocks; if both are zero, return aggregate
    if rc_stock > 0:
        return rc_stock
    elif op_stock_sum > 0:
        return op_stock_sum

    return aggregate_stock


def fetch_etm_stock(article, session_id):
    article = str(article).strip()
    if not article:
        return 0

    headers = {"Accept": "application/json"}

    # Try different request types in order of preference
    request_types = ["cli", "mnf", "etm"]

    for variant in _build_article_variants(article):
        for request_type in request_types:
            url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(variant)}/remains?type={request_type}&session-id={session_id}"

            try:
                response = requests.get(url, headers=headers, timeout=10)

                if response.status_code == 429:  # Too Many Requests
                    print(
                        f"Rate limit hit for article {variant}, sleeping before retry..."
                    )
                    time.sleep(5)  # Wait before retry
                    response = requests.get(url, headers=headers, timeout=10)

                if response.status_code == 403:  # Session expired
                    print(
                        f"Session expired for article {variant}, please renew session"
                    )
                    return 0

                if response.status_code != 200:
                    continue

                data = response.json()

                # Check if the product was not found (status code 404 in the response body)
                status_code = data.get("status", {}).get("code")
                if status_code == 404:
                    continue

                info_stores = data.get("data", {}).get("InfoStores", [])
                request_store_name = data.get("data", {}).get("RequestStoreName", "")
                stock = _extract_samara_stock(info_stores, request_store_name)

                if stock > 0:
                    return stock

            except requests.exceptions.RequestException as e:
                print(
                    f"Request error for article {variant} with type {request_type}: {e}"
                )
                continue
            except Exception as e:
                print(
                    f"Unexpected error for article {variant} with type {request_type}: {e}"
                )
                continue

    return 0


def sync_etm():
    print("Starting ETM Local Sync (Parallelized)...")
    session_id = get_etm_session()
    if not session_id:
        return

    try:
        ws = gsheets_utils.get_worksheet(config.ETM_SHEET_NAME)
    except Exception as e:
        print(f"Error accessing Google Sheet: {e}")
        return

    articles = ws.col_values(2)[1:]  # Skip header (колонка B - Модель)
    print(f"Found {len(articles)} articles in column B")

    stock_results = [0] * len(articles)

    # Process in chunks to avoid overwhelming the server and show progress
    chunk_size = 50
    for i in range(0, len(articles), chunk_size):
        chunk = articles[i : i + chunk_size]
        print(
            f"   Processing chunk {i // chunk_size + 1}/{(len(articles) - 1) // chunk_size + 1} ({i}/{len(articles)})..."
        )

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(fetch_etm_stock, art, session_id) for art in chunk
            ]
            for j, future in enumerate(futures):
                stock_results[i + j] = future.result()

        # Small sleep between chunks to stay safe
        time.sleep(0.5)

    print(f"Updating Google Sheet '{config.ETM_SHEET_NAME}' column AL...")

    # Ensure all values are integers and wrap in single-element lists for Google Sheets API
    # Also add validation to prevent any unexpected types from reaching the API
    formatted_results = []
    for idx, val in enumerate(stock_results):
        if val is None or (
            not isinstance(val, (int, float)) and not str(val).isdigit()
        ):
            formatted_results.append([0])
        else:
            try:
                # Convert to int and ensure it's non-negative
                int_val = int(val)
                formatted_results.append([max(0, int_val)])
            except (ValueError, TypeError):
                formatted_results.append([0])  # fallback to 0 if conversion fails

    print(
        f"Successfully formatted {len(formatted_results)} values for Google Sheets API"
    )

    try:
        gsheets_utils.clear_column(ws, "ЭТМ Стройкерамика")
        gsheets_utils.update_column_by_header(
            ws, "ЭТМ Стройкерамика", formatted_results
        )
        print("ETM Sync completed successfully!")
    except Exception as e:
        print(f"Error updating sheet: {e}")
        print("Debugging information:")
        print(f"Type of formatted_results: {type(formatted_results)}")
        print(f"Length of formatted_results: {len(formatted_results)}")
        print(f"First few values: {formatted_results[:5]}")
        for i, val in enumerate(formatted_results[:5]):
            print(f"  Value {i}: {val} of type {type(val)}")


if __name__ == "__main__":
    sync_etm()
