import sys
from unittest.mock import MagicMock
from urllib.parse import quote as urllib_quote

# ----- Mock requests module -----
class MockResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data

class MockRequests:
    def __init__(self):
        self.calls = []
        self._configure = None

    def configure(self, responses_by_variant):
        """responses_by_variant: dict mapping variant string -> (status_code, json_data or None)"""
        self._configure = responses_by_variant

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("get", url))
        # extract variant from URL .../goods/{variant}/remains?...
        import re
        m = re.search(r"/goods/([^/]+)/remains", url)
        variant = m.group(1) if m else None
        if self._configure and variant in self._configure:
            status, json_data = self._configure[variant]
            return MockResponse(status, json_data)
        # default: not found
        return MockResponse(404, {}, "Not Found")

    @staticmethod
    def utils_quote(s):
        return urllib_quote(s)

# Create a singleton mock_requests
mock_requests = MockRequests()

# ----- Functions from etm_sync_local.py (copied) -----
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
        url = f"https://ipro.etm.ru/api/v1/goods/{mock_requests.utils_quote(variant)}/remains?type=mnf&session-id={session_id}"

        try:
            response = mock_requests.get(url, headers=headers, timeout=10)
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

# ----- Tests -----
def test_build_variants():
    assert _build_article_variants("33110-5") == ["33110-5", "33110"]
    assert _build_article_variants("613100230-1") == ["613100230-1", "613100230"]
    assert _build_article_variants("MVA20-1-016-C") == ["MVA20-1-016-C"]
    assert _build_article_variants("  33110-5  ") == ["33110-5", "33110"]
    print("Variant tests OK")

def test_fetch_etm_stock_33110_5():
    # Simulate: 33110-5 -> 404, 33110 -> 200 with stock aggregate = 300
    mock_requests.configure({
        "33110-5": (404, None),
        "33110": (200, {
            "data": {
                "InfoStores": [
                    {"StoreName": "Стройкерамика", "StoreType": "rc", "StoreQuantRem": 0},
                    {"StoreName": "Самара склад", "StoreType": "op", "StoreQuantRem": 0},
                    {"StoreName": "Другие склады", "StoreType": "rc2sum", "StoreQuantRem": 300},
                    {"StoreName": "All", "StoreType": "all", "StoreQuantRem": 300},
                ]
            }
        })
    })
    stock = fetch_etm_stock("33110-5", "dummy-session")
    assert stock == 300, f"Expected 300, got {stock}"
    # Check that both variants were tried
    assert any("33110-5" in url for _, url in mock_requests.calls)
    assert any("33110" in url for _, url in mock_requests.calls)
    print("Fetch test OK")

if __name__ == "__main__":
    test_build_variants()
    test_fetch_etm_stock_33110_5()
    print("All tests passed; fix should work for 33110-5.")
