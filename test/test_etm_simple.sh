#!/bin/bash

# ============================================
# ТЕСТ ETM API - Склад Стройкерамика (без jq)
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

# Проверяем авторизацию по наличию "session" в ответе
if echo "$AUTH_RESPONSE" | grep -q '"session"'; then
  # Извлекаем session-id используя sed
  SESSION_ID=$(echo "$AUTH_RESPONSE" | sed -n 's/.*"session":"\([^"]*\)".*/\1/p')

  if [ -z "$SESSION_ID" ]; then
    echo "❌ Ошибка извлечения session-id"
    echo "Ответ: $AUTH_RESPONSE"
    exit 1
  fi

  echo "✅ Авторизация успешна"
  echo "Session ID: $SESSION_ID"
else
  echo "❌ Ошибка авторизации"
  echo "Ответ: $AUTH_RESPONSE"
  exit 1
fi

echo ""
echo "=========================================="
echo "Проверка остатков на складе Стройкерамика"
echo "=========================================="
echo ""

# Тестовые артикулы с ожидаемыми остатками
TOTAL_COUNT=0
FOUND_COUNT=0
STOCK_COUNT=0

test_articles() {
  # Article | Expected Stock
  echo "41580-1|190"
  echo "MKP42-N-02-30-20-1|1362"
  echo "MAD22-5-016-C-30-1|6027"
  echo "UZA-11-D01-D10-1|8980"
  echo "RBD-80-1|703"
  echo "YND10-4-15-125-1|444"
}

# Обрабатываем каждый артикул
while IFS='|' read -r ARTICLE EXPECTED; do
  TOTAL_COUNT=$((TOTAL_COUNT + 1))

  echo "──────────────────────────────────────"
  echo "Артикул: $ARTICLE"
  echo "Ожидается: ~$EXPECTED"
  echo ""

  # Запрос к API
  RESPONSE=$(curl -s -X GET \
    "${BASE_URL}/goods/${ARTICLE}/remains?type=mnf&session-id=${SESSION_ID}" \
    -H "Accept: application/json")

  # Проверяем HTTP код
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X GET \
    "${BASE_URL}/goods/${ARTICLE}/remains?type=mnf&session-id=${SESSION_ID}" \
    -H "Accept: application/json")

  if [ "$HTTP_CODE" != "200" ]; then
    echo "❌ Товар не найден (HTTP $HTTP_CODE)"
    echo ""
    continue
  fi

  FOUND_COUNT=$((FOUND_COUNT + 1))

  # Парсим JSON с помощью Python (должен быть установлен)
  STOCK=$(echo "$RESPONSE" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if 'data' not in data or 'InfoStores' not in data['data']:
        print('0')
        sys.exit(0)

    stock = 0
    for store in data['data']['InfoStores']:
        store_name = store.get('StoreName', '').lower()
        if 'стройкерамика' in store_name:
            stock += store.get('StoreQuantRem', store.get('StockRem', 0))

    print(stock)
except Exception as e:
    print('0')
" 2>/dev/null)

  if [ -z "$STOCK" ]; then
    STOCK="0"
  fi

  # Показываем все склады из ответа
  echo "Доступные склады:"
  echo "$RESPONSE" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if 'data' in data and 'InfoStores' in data['data']:
        for store in data['data']['InfoStores']:
            name = store.get('StoreName', 'N/A')
            qty = store.get('StoreQuantRem', store.get('StockRem', 0))
            print(f'  - {name}: {qty}')
except:
    print('  (ошибка парсинга)')
" 2>/dev/null || echo "  (ошибка парсинга)"
  echo ""

  if [ "$STOCK" != "0" ]; then
    STOCK_COUNT=$((STOCK_COUNT + 1))
    echo "✅ Остаток на Стройкерамике: $STOCK"

    # Проверяем совпадение (допускаем 10% отклонение)
    DIFF=$(( ($STOCK - $EXPECTED) * 100 / $EXPECTED ))
    if [ $DIFF -lt 0 ]; then
      DIFF=$((-DIFF))
    fi

    if [ $DIFF -lt 10 ]; then
      echo "   ✓ Совпадение с ожиданием!"
    elif [ $DIFF -lt 30 ]; then
      echo "   ⚠ Небольшое отклонение: $DIFF%"
    else
      echo "   ⚠ Значительное отклонение: $DIFF%"
    fi
  else
    echo "⚠️  Не найден на складе Стройкерамика"
  fi

  echo ""
  # Небольшая пауза между запросами
  sleep 0.5

done < <(test_articles)

echo "=========================================="
echo "📊 ИТОГИ:"
echo "   Всего артикулов: $TOTAL_COUNT"
echo "   Найдено в ETM: $FOUND_COUNT"
echo "   С остатком на Стройкерамике: $STOCK_COUNT"
echo ""
