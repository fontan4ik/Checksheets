"""
Тест работы с реальным ETM API для проверки исправления
Проверяем проблемные артикулы: LLA-G45-10-230-30-E27, 1029089, LDBA0-3924-07-K01
"""

import sys
sys.path.insert(0, '.')

import requests
import config
from etm_sync_local import get_etm_session, fetch_etm_stock, _extract_samara_stock, _build_article_variants


def get_raw_api_response(article, session_id, request_type="cli"):
    """Получаем сырой ответ от ETM API для отладки"""
    url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(article)}/remains?type={request_type}&session-id={session_id}"
    headers = {"Accept": "application/json"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"  Error: {e}")
    return None


def print_store_details(info_stores, request_store_name=""):
    """Детальная информация по каждому складу"""
    print(f"  RequestStoreName: {request_store_name}")
    print(f"  Stores found: {len(info_stores)}")
    
    for i, store in enumerate(info_stores):
        store_name = store.get("StoreName", "")
        store_type = store.get("StoreType", "")
        
        # Проверяем все возможные поля с количеством
        qty1 = store.get("StoreQuantRem")
        qty2 = store.get("StockRem")
        qty3 = store.get("QuantRem")
        
        print(f"  Store {i+1}:")
        print(f"    Name: '{store_name}'")
        print(f"    Type: '{store_type}'")
        print(f"    StoreQuantRem: {qty1}")
        print(f"    StockRem: {qty2}")
        print(f"    QuantRem: {qty3}")
        
        # Проверяем является ли склад Samara
        is_samara = any(k in (store_name or "").lower() for k in ["стройкерамика", "самар"])
        print(f"    Is Samara: {is_samara}")


def test_article(article, session_id, expected=None):
    """Тестируем один артикул через реальное API"""
    print(f"\n{'='*60}")
    print(f"Testing article: {article}")
    if expected:
        print(f"Expected stock: {expected}")
    print(f"{'='*60}")
    
    # Показываем варианты артикула
    variants = _build_article_variants(article)
    print(f"Article variants: {variants}")
    
    # Пробуем разные типы запросов
    request_types = ["cli", "mnf", "etm"]
    
    for variant in variants:
        for req_type in request_types:
            data = get_raw_api_response(variant, session_id, req_type)
            if data and data.get("status", {}).get("code") != 404:
                print(f"\n  SUCCESS with variant='{variant}', type='{req_type}'")
                
                info_stores = data.get("data", {}).get("InfoStores", [])
                request_store_name = data.get("data", {}).get("RequestStoreName", "")
                
                # Показываем детали
                print_store_details(info_stores, request_store_name)
                
                # Считаем остатки
                stock = _extract_samara_stock(info_stores, request_store_name)
                print(f"\n  Calculated stock (SUM): {stock}")
                
                # Сравниваем с ожидаемым
                if expected:
                    if stock == expected:
                        print(f"  [PASS] Stock matches expected: {expected}")
                    else:
                        print(f"  [WARN] Stock does NOT match! Expected {expected}, got {stock}")
                
                return stock
    
    print(f"\n  [FAIL] Article not found or error")
    return 0


def main():
    print("="*60)
    print("ETM REAL API TEST")
    print("="*60)
    
    # Получаем сессию
    print("\nGetting ETM session...")
    session_id = get_etm_session()
    if not session_id:
        print("Failed to get session!")
        return
    
    print(f"Session: {session_id[:20]}...")
    
    # Тестируем проблемные артикулы
    test_cases = [
        # (артикул, ожидаемое_значение)
        ("LLA-G45-10-230-30-E27", 11),
        ("1029089", 1221),
        ("LDBA0-3924-07-K01", 4),
    ]
    
    results = []
    for article, expected in test_cases:
        stock = test_article(article, session_id, expected)
        results.append((article, expected, stock))
    
    # Итоговый отчет
    print(f"\n\n{'='*60}")
    print("FINAL RESULTS")
    print(f"{'='*60}")
    print(f"{'Article':<30} {'Expected':>10} {'Got':>10} {'Status':>10}")
    print("-"*60)
    
    for article, expected, got in results:
        status = "PASS" if got == expected else "FAIL"
        print(f"{article:<30} {expected:>10} {got:>10} {status:>10}")


if __name__ == "__main__":
    main()