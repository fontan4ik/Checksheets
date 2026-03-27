# Тестирование логики синхронизации
import unittest
from unittest.mock import patch, MagicMock
from test_api_mock import MockRSAPI

def test_sync_logic():
    print("Тестируем логику синхронизации...")

    # Имитируем работу основного скрипта
    mock_api = MockRSAPI()

    # Тест 1: Проверка получения карты кодов
    print("\n1. Тест получения карты кодов:")
    catalog_data = mock_api.get_catalog_response()
    code_map = {}

    for item in catalog_data["items"]:
        v_code = str(item.get("VENDOR_CODE", "")).strip()
        if v_code:
            code_map[v_code] = item.get("CODE")

    print(f"Карта кодов: {code_map}")

    # Проверяем, что коды соответствуют ожидаемым
    expected_codes = {
        "61950": "100000001",
        "71650": "100000002",
        "12345": "100000003"
    }

    for vendor_code, expected_code in expected_codes.items():
        actual_code = code_map.get(vendor_code)
        assert actual_code == expected_code, f"Ожидаемый код {expected_code}, получили {actual_code}"

    print("✓ Карта кодов работает корректно")

    # Тест 2: Проверка получения остатков
    print("\n2. Тест получения остатков:")
    stock_data = mock_api.get_stock_response()
    stock_map = {}

    for item in stock_data["residues"]:
        code = item.get("CODE")
        if code:
            stock_map[code] = item.get("RESIDUE", 0)

    print(f"Карта остатков: {stock_map}")

    # Проверяем, что остатки соответствуют ожидаемым
    expected_stocks = {
        "100000001": 25,  # для 61950
        "100000002": 1097, # для 71650
        "100000003": 50    # для 12345
    }

    for code, expected_stock in expected_stocks.items():
        actual_stock = stock_map.get(code)
        assert actual_stock == expected_stock, f"Ожидаемый остаток {expected_stock}, получили {actual_stock}"

    print("✓ Карта остатков работает корректно")

    # Тест 3: Проверка сопоставления моделей с остатками
    print("\n3. Тест сопоставления моделей с остатками:")
    models = ["61950", "71650", "12345", "NONEXISTENT"]

    results_stock = []
    for model in models:
        stock = 0
        if model:
            rs_code = code_map.get(model)
            if rs_code:
                stock = stock_map.get(rs_code, 0)

        results_stock.append([stock])
        print(f"Модель {model}: код={code_map.get(model)}, остаток={stock}")

    # Проверяем результаты
    expected_results = [[25], [1097], [50], [0]]
    assert results_stock == expected_results, f"Ожидаемые результаты {expected_results}, получили {results_stock}"

    print("✓ Сопоставление моделей с остатками работает корректно")

    print("\n✓ Все тесты пройдены успешно!")

if __name__ == "__main__":
    test_sync_logic()
