import requests
import config
import sys
import os

# Добавляем текущую директорию в путь, чтобы импортировать модули
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from etm_sync_local import get_etm_session, _build_article_variants, _extract_samara_stock

def debug_etm_stock(article):
    print(f"=== Отладка получения остатков для артикула {article} ===")

    # Получаем сессию ETM
    session_id = get_etm_session()
    if not session_id:
        print("Ошибка: Не удалось получить сессию ETM")
        return

    # Проверяем все варианты артикула
    variants = _build_article_variants(article)
    print(f"Варианты артикула для проверки: {variants}")

    headers = {"Accept": "application/json"}

    for variant in variants:
        print(f"\n--- Проверяем вариант: {variant} ---")

        url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(variant)}/remains?type=mnf&session-id={session_id}"
        print(f"URL запроса: {url}")

        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"Код ответа: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print("JSON ответа:")
                print(data)

                info_stores = data.get("data", {}).get("InfoStores", [])
                print(f"\nInfoStores из ответа: {info_stores}")

                # Проверяем каждый магазин отдельно
                print("\nДетализация по магазинам:")
                for idx, store in enumerate(info_stores):
                    store_name = store.get("StoreName", "")
                    store_type = store.get("StoreType", "")
                    store_code = store.get("StoreCode", "")
                    qty1 = store.get("StoreQuantRem", "отсутствует")
                    qty2 = store.get("StockRem", "отсутствует")

                    print(f"  [{idx}] Имя: '{store_name}', Тип: '{store_type}', Код: {store_code}, Остаток1: {qty1}, Остаток2: {qty2}")

                    # Проверяем условия, соответствующие логике _extract_samara_stock
                    is_samara = any(k in store_name.lower() for k in ["стройкерамика", "самар"])
                    print(f"      -> Это Самара/Стройкерамика: {is_samara}")
                    if is_samara:
                        print(f"      -> Тип магазина входит в ('rc', 'op'): {store_type.lower() in ['rc', 'op']}")

                # Вызываем _extract_samara_stock и смотрим результат
                extracted_stock = _extract_samara_stock(info_stores)
                print(f"\nРезультат из _extract_samara_stock: {extracted_stock}")

                # Попробуем воспроизвести логику _extract_samara_stock вручную
                print("\n=== Ручной анализ логики _extract_samara_stock ===")
                regional_stock = 0
                aggregate_stock = 0

                for store in info_stores:
                    store_name = (store.get("StoreName") or "").lower()
                    store_type = (store.get("StoreType") or "").lower()
                    qty = store.get("StoreQuantRem") or store.get("StockRem") or 0

                    print(f"Обработка магазина: '{store_name}', тип: '{store_type}', кол-во: {qty}")

                    is_samara = any(k in store_name for k in ["стройкерамика", "самар"])

                    if is_samara and store_type in ["rc", "op"]:
                        regional_stock += qty
                        print(f"  -> Добавлено к региональному остатку: {qty}, всего: {regional_stock}")
                        continue

                    if store_type == "rc2sum":
                        aggregate_stock = max(aggregate_stock, qty)
                        print(f"  -> Обновлен агрегатный остаток (rc2sum): {aggregate_stock}")
                    elif store_type == "all":
                        aggregate_stock = max(aggregate_stock, qty)
                        print(f"  -> Обновлен агрегатный остаток (all): {aggregate_stock}")

                print(f"Итоговый региональный остаток: {regional_stock}")
                print(f"Итоговый агрегатный остаток: {aggregate_stock}")

                if regional_stock > 0:
                    print(f"Будет возвращен региональный остаток: {regional_stock}")
                else:
                    print(f"Будет возвращен агрегатный остаток: {aggregate_stock}")

                if extracted_stock > 0:
                    print(f"\n*** Найден положительный остаток: {extracted_stock} для варианта {variant} ***")
                    return extracted_stock

            else:
                print(f"Запрос вернул код ошибки: {response.status_code}")
                print(f"Текст ошибки: {response.text}")

        except Exception as e:
            print(f"Произошла ошибка при выполнении запроса: {e}")
            import traceback
            traceback.print_exc()

    print(f"\nНе найдено положительных остатков ни для одного варианта артикула {article}")
    return 0

def manual_check_article():
    """Ручная проверка конкретного артикула"""
    article = "33126"
    debug_etm_stock(article)

if __name__ == "__main__":
    print("Запуск отладки получения остатков из ETM")
    manual_check_article()
