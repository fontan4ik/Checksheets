#!/bin/bash

# ============================================
# ТЕСТ ETM API - Склад Стройкерамика
# ============================================

LOGIN="160119919fik"
PASSWORD="Ibs30Rh2"
BASE_URL="https://ipro.etm.ru/api/v1"

echo "=========================================="
echo "ТЕСТ ETM API (Стройкерамика)"
echo "=========================================="
echo ""

# Шаг 1: Авторизация
echo "🔐 Авторизация..."
AUTH_RESPONSE=$(curl -s -X GET \
  "${BASE_URL}/user/login?log=${LOGIN}&pwd=${PASSWORD}" \
  -H "Accept: application/json")

# Извлекаем session-id
SESSION_ID=$(echo "$AUTH_RESPONSE" | sed -n 's/.*"session":"\([^"]*\)".*/\1/p')

if [ -z "$SESSION_ID" ]; then
  echo "❌ Ошибка авторизации"
  exit 1
fi

echo "✅ Session ID: $SESSION_ID"
echo ""

echo "=========================================="
echo "Проверка остатков (артикулы БЕЗ суффикса -1)"
echo "=========================================="
echo ""

# Тестовые артикулы (БЕЗ -1)
# Мы будем удалять суффикс -1 перед запросом
declare -a TEST_ARTICLES=(
  "41580"
  "MKP42-N-02-30-20"
  "MAD22-5-016-C-30"
  "UZA-11-D01-D10"
  "RBD-80"
  "YND10-4-15-125"
)

declare -A EXPECTED_STOCKS
EXPECTED_STOCKS["41580"]=190
EXPECTED_STOCKS["MKP42-N-02-30-20"]=1362
EXPECTED_STOCKS["MAD22-5-016-C-30"]=6027
EXPECTED_STOCKS["UZA-11-D01-D10"]=8980
EXPECTED_STOCKS["RBD-80"]=703
EXPECTED_STOCKS["YND10-4-15-125"]=444

TOTAL_COUNT=${#TEST_ARTICLES[@]}
FOUND_COUNT=0
STOCK_COUNT=0

for ARTICLE in "${TEST_ARTICLES[@]}"; do
  EXPECTED=${EXPECTED_STOCKS[$ARTICLE]}

  echo "──────────────────────────────────────"
  echo "Артикул: $ARTICLE"
  echo "Ожидается: ~$EXPECTED"
  echo ""

  # Запрос к API
  RESPONSE=$(curl -s -X GET \
    "${BASE_URL}/goods/${ARTICLE}/remains?type=mnf&session-id=${SESSION_ID}" \
    -H "Accept: application/json")

  # Сохраняем ответ для отладки
  echo "$RESPONSE" > "/tmp/etm_${ARTICLE}.json"

  # Проверяем HTTP код
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X GET \
    "${BASE_URL}/goods/${ARTICLE}/remains?type=mnf&session-id=${SESSION_ID}" \
    -H "Accept: application/json")

  if [ "$HTTP_CODE" != "200" ]; then
    echo "❌ HTTP $HTTP_CODE"
    # Показываем ответ для диагностики
    echo "$RESPONSE" | head -c 200
    echo ""
    continue
  fi

  FOUND_COUNT=$((FOUND_COUNT + 1))

  # Парсим JSON для получения:
  # 1. RequestStoreName (название склада)
  # 2. InfoStores (массив складов с остатками)
  python3 << PYTHON_SCRIPT
import json

# Читаем файл
with open('/tmp/etm_${ARTICLE}.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

if 'data' not in data:
    print("❌ Нет поля data")
else:
    d = data['data']

    # Показываем RequestStoreName
    request_store = d.get('RequestStoreName', 'N/A')
    print(f"RequestStoreName: {request_store}")

    # Показываем InfoStores
    info_stores = d.get('InfoStores', [])
    print(f"InfoStores записей: {len(info_stores)}")

    for store in info_stores:
        store_name = store.get('StoreName', 'N/A')
        store_code = store.get('StoreCode', 'N/A')
        store_quant = store.get('StoreQuantRem', store.get('StockRem', 0))
        store_type = store.get('StoreType', 'N/A')
        print(f"  - {store_name} (код: {store_code}, тип: {store_type}): {store_quant}")

    # Ищем остаток на любом складе с 'стройкерамика' в названии
    stock = 0
    for store in info_stores:
        store_name = store.get('StoreName', '').lower()
        if 'стройкерамика' in store_name:
            stock += store.get('StoreQuantRem', store.get('StockRem', 0))

    if stock > 0:
        print(f"✅ Остаток на Стройкерамике: {stock}")
    else:
        print("⚠️  Не найден на складе Стройкерамика")
        # Показываем rc_address для диагностики
        rc_addr = d.get('rc_address', '')
        if rc_addr:
            print(f"Адрес склада: {rc_addr}")
PYTHON_SCRIPT

  echo ""
  sleep 0.5
done

echo "=========================================="
echo "📊 ИТОГИ:"
echo "   Всего артикулов: $TOTAL_COUNT"
echo "   Найдено в ETM: $FOUND_COUNT"
echo ""
