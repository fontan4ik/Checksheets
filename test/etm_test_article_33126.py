import requests
import config
from etm_sync_local import get_etm_session, fetch_etm_stock, _build_article_variants, _extract_samara_stock


def test_article_33126():
    print("Testing article 33126...")

    # Получаем сессию ETM
    session_id = get_etm_session()
    if not session_id:
        print("Failed to get ETM session")
        return

    article = "33126"

    # Протестируем все варианты артикула
    variants = _build_article_variants(article)
    print(f"Testing variants: {variants}")

    headers = {"Accept": "application/json"}

    for variant in variants:
        url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(variant)}/remains?type=mnf&session-id={session_id}"

        try:
            print(f"Trying URL: {url}")
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                print(f"Response for {variant}: {data}")

                info_stores = data.get("data", {}).get("InfoStores", [])
                stock = _extract_samara_stock(info_stores)

                print(f"Stock for {variant}: {stock}")

                if stock > 0:
                    print(f"Found positive stock for variant {variant}: {stock}")
                    return stock
            else:
                print(f"Request for {variant} failed with status {response.status_code}")

        except Exception as e:
            print(f"Exception while processing {variant}: {e}")

    print("No positive stock found for any variant")
    return 0


def detailed_test():
    print("=== Detailed Test for Article 33126 ===")

    session_id = get_etm_session()
    if not session_id:
        return

    article = "33126"

    # Прямой вызов функции получения остатков
    result = fetch_etm_stock(article, session_id)
    print(f"Result from fetch_etm_stock({article}): {result}")

    # Проверим все возможные варианты
    variants = _build_article_variants(article)
    print(f"All variants: {variants}")

    headers = {"Accept": "application/json"}

    for variant in variants:
        url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(variant)}/remains?type=mnf&session-id={session_id}"
        print(f"\nTesting variant: {variant}")
        print(f"URL: {url}")

        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"Status code: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"Full response: {data}")

                info_stores = data.get("data", {}).get("InfoStores", [])
                print(f"InfoStores: {info_stores}")

                stock = _extract_samara_stock(info_stores)
                print(f"Extracted stock: {stock}")

                # Проверим подробнее, какие именно магазины и остатки есть
                for store in info_stores:
                    store_name = store.get("StoreName", "")
                    store_type = store.get("StoreType", "")
                    qty = store.get("StoreQuantRem") or store.get("StockRem") or 0
                    print(f"  Store: {store_name}, Type: {store_type}, Qty: {qty}")

        except Exception as e:
            print(f"Error testing variant {variant}: {e}")


if __name__ == "__main__":
    # Простой тест
    print("Simple test:")
    test_article_33126()

    print("\n" + "="*50 + "\n")

    # Подробный тест
    print("Detailed test:")
    detailed_test()
