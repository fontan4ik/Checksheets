import time

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
    """
    Extract stock for Samara (Стройкерамика) from ETM API response.
    Returns the MAXIMUM available stock across all relevant stores.
    """
    samara_stocks = []  # Collect all Samara-related stocks
    aggregate_stock = 0

    # Check if the overall request is for Samara
    is_request_for_samara = (
        "самар" in request_store_name.lower()
        or "стройкерамика" in request_store_name.lower()
    )

    for store in info_stores:
        store_name = (store.get("StoreName") or "").lower()
        store_type = (store.get("StoreType") or "").lower()

        # Check various possible fields that might contain stock information
        qty = store.get("StoreQuantRem")
        if qty is None:
            qty = store.get("StockRem")
        if qty is None:
            qty = store.get("QuantRem", 0)
        if qty is None:
            qty = 0

        # Convert to int to ensure numeric comparison
        try:
            qty = int(qty)
        except (ValueError, TypeError):
            qty = 0

        # Check if this store is Samara-related
        is_samara = any(k in store_name for k in ["стройкерамика", "самар"])

        # Collect stocks from Samara stores (rc, op, crs)
        if is_samara and store_type in ["rc", "op", "crs"]:
            if qty > 0:
                samara_stocks.append(qty)
            continue

        # Handle aggregate rows
        if not store_name and store_type == "all" and is_request_for_samara:
            aggregate_stock = max(aggregate_stock, qty)
            continue

        # Fallback: some ETM responses expose the available quantity only in aggregate rows
        if store_type in ["rc2sum", "all"]:
            aggregate_stock = max(aggregate_stock, qty)

    # Return the MAXIMUM stock found
    # Priority: max of individual Samara stores, then aggregate
    if samara_stocks:
        return max(samara_stocks)

    return aggregate_stock


def fetch_etm_stock(article, session_id, retry_count=0):
    """
    Fetch stock for a single article from ETM API.
    Implements exponential backoff for rate limiting.
    """
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
                    # Exponential backoff: 2, 4, 8 seconds
                    wait_time = min(2 ** (retry_count + 1), 10)
                    print(
                        f"Rate limit hit for article {variant}, waiting {wait_time}s..."
                    )
                    time.sleep(wait_time)

                    if retry_count < 3:
                        return fetch_etm_stock(article, session_id, retry_count + 1)
                    else:
                        print(f"Max retries reached for article {variant}")
                        continue

                if response.status_code == 403:  # Session expired
                    print(
                        f"Session expired for article {variant}, session needs renewal"
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
                    print(f"  {article} -> {stock} units")
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
    """
    Sync ETM stock data to Google Sheets.
    Uses sequential processing with rate limiting to respect ETM API limits (1 req/sec).
    """
    print("Starting ETM Local Sync (Sequential with Rate Limiting)...")
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

    # ETM API limit: 1 request per second
    # We use 1.1 seconds to be safe
    request_delay = 1.1
    last_request_time = 0

    # Process sequentially with rate limiting
    chunk_size = 50
    for i in range(0, len(articles), chunk_size):
        chunk = articles[i : i + chunk_size]
        chunk_end = min(i + chunk_size, len(articles))
        print(
            f"\n=== Processing chunk {i // chunk_size + 1}/{(len(articles) - 1) // chunk_size + 1} "
            f"(articles {i + 1}-{chunk_end}/{len(articles)}) ==="
        )

        for j, article in enumerate(chunk):
            # Rate limiting: ensure at least 1.1 seconds between requests
            elapsed = time.time() - last_request_time
            if elapsed < request_delay:
                time.sleep(request_delay - elapsed)

            last_request_time = time.time()

            # Fetch stock for this article
            stock = fetch_etm_stock(article, session_id)
            stock_results[i + j] = stock

            # Progress indicator every 10 items
            if (j + 1) % 10 == 0:
                print(f"  Progress: {j + 1}/{len(chunk)} articles in current chunk")

    print(f"\n=== Updating Google Sheet '{config.ETM_SHEET_NAME}' column AL ===")

    # Ensure all values are integers and wrap in single-element lists for Google Sheets API
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
        print("\n=== ETM Sync completed successfully! ===")

        # Summary statistics
        non_zero_count = sum(1 for r in stock_results if r > 0)
        print(f"Summary: {non_zero_count}/{len(stock_results)} articles have stock > 0")
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
