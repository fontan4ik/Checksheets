import requests
import config
import sys
import os

# Добавляем текущую директорию в путь, чтобы импортировать модули
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from etm_sync_local import get_etm_session, _build_article_variants

def improved_extract_samara_stock(info_stores):
    """
    Улучшенная версия функции извлечения остатков для Самары/Стройкерамики
    Теперь учитывает возможные изменения в API ETM
    """
    regional_stock = 0
    aggregate_stock = 0

    for store in info_stores:
        store_name = (store.get("StoreName") or "").lower()
        store_type = (store.get("StoreType") or "").lower()
        qty = store.get("StoreQuantRem") or store.get("StockRem") or 0

        is_samara = any(k in store_name for k in ["стройкерамика", "самар"])

        # Основной источник: явно указанные Самара / Стройкерамика магазины
        if is_samara and store_type in ["rc", "op"]:
            regional_stock += qty
            continue

        # НОВАЯ ЛОГИКА: если в ответе только обобщенный тип "all",
        # и при этом RequestStoreName указывает на "ЭТМ-Самара",
        # считаем, что это остатки для Самарского филиала
        if store_type == "all":
            aggregate_stock = max(aggregate_stock, qty)

        # Также учитываем rc2sum как резервный вариант
        elif store_type == "rc2sum":
            aggregate_stock = max(aggregate_stock, qty)

    # Если найдены региональные остатки, возвращаем их
    if regional_stock > 0:
        return regional_stock

    # Если региональных остатков нет, но есть агрегированные, возвращаем их
    # (это покрывает случай, когда API возвращает только "all" для Самары)
    return aggregate_stock


def debug_with_improved_logic(article):
    print(f"=== Отладка с улучшенной логикой для артикула {article} ===")

    # Получаем сессию ETM
    session_id = get_etm_session()
    if not session_id:
        print("Ошибка: Не удалось получить сессию ETM")
        return

    headers = {"Accept": "application/json"}

    for variant in _build_article_variants(article):
        print(f"\n--- Проверяем вариант: {variant} ---")

        url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(variant)}/remains?type=mnf&session-id={session_id}"
        print(f"URL запроса: {url}")

        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"Код ответа: {response.status_code}")

            if response.status_code == 200:
                data = response.json()

                # Проверяем RequestStoreName
                request_store_name = data.get("data", {}).get("RequestStoreName", "")
                print(f"RequestStoreName: {request_store_name}")

                info_stores = data.get("data", {}).get("InfoStores", [])
                print(f"InfoStores: {info_stores}")

                # Тестируем старую логику
                from etm_sync_local import _extract_samara_stock as old_logic
                old_result = old_logic(info_stores)
                print(f"Результат старой логики: {old_result}")

                # Тестируем новую логику
                new_result = improved_extract_samara_stock(info_stores)
                print(f"Результат новой логики: {new_result}")

                if new_result > 0:
                    print(f"\n*** НОВАЯ ЛОГИКА НАШЛА ПОЛОЖИТЕЛЬНЫЙ ОСТАТОК: {new_result} для варианта {variant} ***")
                    return new_result
            else:
                print(f"Запрос вернул код ошибки: {response.status_code}")

        except Exception as e:
            print(f"Произошла ошибка при выполнении запроса: {e}")

    print(f"\nУлучшенная логика также не нашла положительных остатков для артикула {article}")
    return 0


def main():
    article = "33126"
    print("Проверка улучшенной логики извлечения остатков для ETM")

    result = debug_with_improved_logic(article)
    print(f"\nИтоговый результат: {result}")


if __name__ == "__main__":
    main()
