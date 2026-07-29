import os
import re
import time
from typing import Dict, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

import config
import gsheets_utils


MIC_PRICE_TYPE_NAME = "МИЦ Маркетплейсы"
TARGET_SHEET_NAME = "ТЕСТ"
ARTICLE_HEADER = "МОДЕЛЬ"
TARGET_HEADER = "Миц ферон"
PRICE_SCALE = 100


class SourceAddressAdapter(HTTPAdapter):
    def __init__(self, source_ip, **kwargs):
        self._source_address = (source_ip, 0)
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["source_address"] = self._source_address
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs,
        )


def get_active_interface_ip():
    preferred_interface = os.getenv("CHECKSHEETS_BYPASS_INTERFACE", "").strip()

    if preferred_interface:
        output = os.popen(f"ifconfig {preferred_interface}").read()
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", output)
        if match:
            return preferred_interface, match.group(1)

    for interface in ("en1", "en0"):
        output = os.popen(f"ifconfig {interface}").read()
        if "status: active" not in output:
            continue
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", output)
        if match:
            return interface, match.group(1)

    raise RuntimeError(
        "No active LAN/Wi-Fi interface found for Feron bypass. "
        "Set CHECKSHEETS_BYPASS_INTERFACE explicitly."
    )


def create_feron_session():
    interface, source_ip = get_active_interface_ip()
    session = requests.Session()
    adapter = SourceAddressAdapter(source_ip)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    print(f"Feron bypass interface: {interface} ({source_ip})")
    return session


def feron_request_with_retry(http, method, url, headers, *, payload=None, timeout=60, label="", attempts=4):
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            if method == "GET":
                response = http.get(url, headers=headers, timeout=timeout)
            else:
                response = http.post(url, json=payload, headers=headers, timeout=timeout)

            if response.status_code == 429:
                wait_seconds = min(10 * attempt, 30)
                print(f"{label}: rate limit hit, retry {attempt}/{attempts} in {wait_seconds}s...")
                time.sleep(wait_seconds)
                continue

            return response
        except requests.exceptions.Timeout as e:
            last_error = e
            if attempt == attempts:
                break
            wait_seconds = min(5 * attempt, 20)
            print(f"{label}: timeout, retry {attempt}/{attempts} in {wait_seconds}s...")
            time.sleep(wait_seconds)
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt == attempts:
                break
            wait_seconds = min(3 * attempt, 15)
            print(f"{label}: network error, retry {attempt}/{attempts} in {wait_seconds}s...")
            time.sleep(wait_seconds)

    raise RuntimeError(f"{label} failed after {attempts} attempts: {last_error}")


def fetch_product_ids_by_article(http, headers, articles: List[str]) -> Dict[str, str]:
    base_url = getattr(config, "FERON_BASE_URL", "https://api.feron.ru").rstrip("/")
    product_ids: Dict[str, str] = {}
    search_token = None

    for page in range(1, 101):
        payload = {"search_token": search_token} if search_token else {"size": 3000}
        response = feron_request_with_retry(
            http,
            "POST",
            f"{base_url}/offers/products/search",
            headers,
            payload=payload,
            timeout=30,
            label=f"Product search page {page}",
        )

        if response.status_code != 200:
            raise RuntimeError(f"Product search failed: {response.status_code} {response.text[:500]}")

        data = response.json()
        items = data.get("items", [])

        for item in items:
            vendor_code = str(item.get("vendor_code") or "").strip()
            product_id = str(item.get("product_id") or "").strip()
            if vendor_code and product_id and vendor_code in articles and vendor_code not in product_ids:
                product_ids[vendor_code] = product_id

        if len(product_ids) == len(articles):
            break

        next_token = data.get("search_token")
        if not next_token or next_token == search_token or not items:
            break
        search_token = next_token

    return product_ids


def fetch_mic_prices(http, headers, product_ids_by_article: Dict[str, str]) -> Dict[str, int]:
    base_url = getattr(config, "FERON_BASE_URL", "https://api.feron.ru").rstrip("/")
    article_by_product_id = {product_id: article for article, product_id in product_ids_by_article.items()}
    product_ids = list(article_by_product_id.keys())
    mic_prices: Dict[str, int] = {}

    for idx in range(0, len(product_ids), 100):
        chunk = product_ids[idx:idx + 100]
        response = feron_request_with_retry(
            http,
            "POST",
            f"{base_url}/prices/search",
            headers,
            payload={"products_id": chunk},
            timeout=30,
            label=f"Price fetch chunk {idx // 100 + 1}",
        )

        if response.status_code != 200:
            raise RuntimeError(f"Price fetch failed: {response.status_code} {response.text[:500]}")

        data = response.json()
        for item in data.get("items", []):
            if item.get("price_type_name") != MIC_PRICE_TYPE_NAME:
                continue

            product_id = str(item.get("product_id") or "").strip()
            article = article_by_product_id.get(product_id)
            value = item.get("value")
            if article and value is not None:
                mic_prices[article] = value / PRICE_SCALE

    return mic_prices


def sync_feron_mic():
    api_key = getattr(config, "FERON_API_KEY", None)
    if not api_key:
        raise RuntimeError("FERON_API_KEY is not configured")

    worksheet = gsheets_utils.get_worksheet(TARGET_SHEET_NAME)
    columns = gsheets_utils.get_header_columns(
        worksheet,
        {"article": ARTICLE_HEADER, "mic_price": TARGET_HEADER},
        TARGET_SHEET_NAME,
    )
    article_values = worksheet.col_values(columns["article"])[1:]
    normalized_articles = [str(value).strip() for value in article_values]
    articles = sorted({article for article in normalized_articles if article})

    print(f"Loaded {len(normalized_articles)} rows from column B")
    print(f"Unique non-empty articles: {len(articles)}")

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": api_key,
    }
    http = create_feron_session()

    product_ids_by_article = fetch_product_ids_by_article(http, headers, articles)
    print(f"Resolved product_id for {len(product_ids_by_article)}/{len(articles)} articles")

    mic_prices = fetch_mic_prices(http, headers, product_ids_by_article)
    print(f"Fetched MIC prices for {len(mic_prices)} articles")

    values = [[mic_prices.get(article, "")] for article in normalized_articles]
    gsheets_utils.update_column(worksheet, columns["mic_price"], values, start_row=2)

    filled = sum(1 for value in values if value[0] != "")
    print(f"Updated sheet '{TARGET_SHEET_NAME}' header '{TARGET_HEADER}' with {filled} MIC values")


if __name__ == "__main__":
    sync_feron_mic()
