import requests
import time
import config
import gsheets_utils
from concurrent.futures import ThreadPoolExecutor


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

    # Keep the original article first. ETM articles with suffixes like -5 can be valid.
    # Only try a stripped fallback for the legacy -1 suffix used in the sheet.
    if article.endswith("-1"):
        variants.append(article[:-2])

    return list(dict.fromkeys(v for v in variants if v))


def _extract_samara_stock(info_stores):
    regional_stock = 0
    aggregate_stock = 0

    for store in info_stores:
        store_name = (store.get("StoreName") or "").lower()
        store_type = (store.get("StoreType") or "").lower()
        qty = store.get("StoreQuantRem") or store.get("StockRem") or 0

        is_samara = any(k in store_name for k in ["стройкерамика", "самар"])

        # Primary source: explicit Samara / Stroykeramika rows.
        if is_samara and store_type in ["rc", "op"]:
            regional_stock += qty
            continue

        # Fallback: some ETM responses expose the available quantity only in aggregate rows.
        if store_type == "rc2sum":
            aggregate_stock = max(aggregate_stock, qty)
        elif store_type == "all":
            aggregate_stock = max(aggregate_stock, qty)

    if regional_stock > 0:
        return regional_stock

    return aggregate_stock


def fetch_etm_stock(article, session_id):
    article = str(article).strip()
    if not article:
        return 0

    headers = {"Accept": "application/json"}

    for variant in _build_article_variants(article):
        url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(variant)}/remains?type=mnf&session-id={session_id}"

        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                continue

            data = response.json()
            info_stores = data.get("data", {}).get("InfoStores", [])
            stock = _extract_samara_stock(info_stores)

            if stock > 0:
                return stock
        except Exception:
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
    print(f"Found {len(articles)} articles in column A")

    stock_results = [0] * len(articles)

    # Process in chunks to avoid overwhelming the server and show progress
    chunk_size = 50
    for i in range(0, len(articles), chunk_size):
        chunk = articles[i:i + chunk_size]
        print(f"   Processing chunk {i // chunk_size + 1}/{(len(articles) - 1) // chunk_size + 1} ({i}/{len(articles)})...")

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(fetch_etm_stock, art, session_id) for art in chunk]
            for j, future in enumerate(futures):
                stock_results[i + j] = [future.result()]

        # Small sleep between chunks to stay safe
        time.sleep(0.5)

    print(f"Updating Google Sheet '{config.ETM_SHEET_NAME}' column AL...")
    try:
        gsheets_utils.clear_column(ws, "ЭТМ Стройкерамика")
        gsheets_utils.update_column_by_header(ws, "ЭТМ Стройкерамика", stock_results)
        print("ETM Sync completed successfully!")
    except Exception as e:
        print(f"Error updating sheet: {e}")


if __name__ == "__main__":
    sync_etm()
