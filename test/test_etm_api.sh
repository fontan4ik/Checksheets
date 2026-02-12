#!/bin/bash

# ============================================
# ТЕСТ ETM API - Склад Стройкерамика
# ============================================

LOGIN="160119919fik"
PASSWORD="Ibs30Rh2"
BASE_URL="https://ipro.etm.ru/api/v1"

echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║   ТЕСТ ETM API                                                        ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""

# Тест 1: Авторизация
echo "=== ТЕСТ 1: Авторизация ==="
echo "URL: ${BASE_URL}/user/login"
echo ""

AUTH_RESPONSE=$(curl -s -X 'POST' \
  "${BASE_URL}/user/login?log=${LOGIN}&pwd=${PASSWORD}" \
  -H 'Accept: application/json' \
  -H 'Content-Type: application/json')

echo "$AUTH_RESPONSE" | jq '.'

# Извлекаем session-id
SESSION_ID=$(echo "$AUTH_RESPONSE" | jq -r '.data.session // empty')

if [ -z "$SESSION_ID" ] || [ "$SESSION_ID" = "null" ]; then
  echo ""
  echo "❌ ОШИБКА: Не удалось получить session-id"
  echo "Проверьте логин и пароль"
  exit 1
fi

echo ""
echo "✅ Успешная авторизация!"
echo "Session ID: ${SESSION_ID}"
echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo ""

# Тест 2: Проверка остатков на складе Стройкерамика
echo "=== ТЕСТ 2: Остатки на складе Стройкерамика ==="
echo "Используем артикулы производителя (type=mnf)"
echo ""

# Тестовые артикулы с ожидаемыми остатками
declare -A TEST_ARTICLES=(
  ["41580-1"]="190"
  ["MKP42-N-02-30-20-1"]="1362"
  ["MAD22-5-016-C-30-1"]="6027"
  ["UZA-11-D01-D10-1"]="8980"
  ["RBD-80-1"]="703"
  ["YND10-4-15-125-1"]="444"
)

TOTAL_COUNT=0
FOUND_COUNT=0
STOCK_COUNT=0

for ARTICLE in "${!TEST_ARTICLES[@]}"; do
  EXPECTED=${TEST_ARTICLES[$ARTICLE]}
  TOTAL_COUNT=$((TOTAL_COUNT + 1))

  echo "──────────────────────────────────────────────"
  echo "Артикул: $ARTICLE"
  echo "Ожидается: ~$EXPECTED"
  echo ""

  # Запрос к API
  RESPONSE=$(curl -s -X 'GET' \
    "${BASE_URL}/goods/${ARTICLE}/remains?type=mnf&session-id=${SESSION_ID}" \
    -H 'Accept: application/json')

  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X 'GET' \
    "${BASE_URL}/goods/${ARTICLE}/remains?type=mnf&session-id=${SESSION_ID}" \
    -H 'Accept: application/json')

  if [ "$HTTP_CODE" != "200" ]; then
    echo "❌ Товар не найден (HTTP $HTTP_CODE)"
    echo ""
    continue
  fi

  FOUND_COUNT=$((FOUND_COUNT + 1))

  # Парсим JSON и ищем склад Стройкерамика
  STOCK=$(echo "$RESPONSE" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if 'data' not in data or 'InfoStores' not in data['data']:
        print('0')
        sys.exit(0)

    stock = 0
    warehouses = []
    for store in data['data']['InfoStores']:
        store_name = store.get('StoreName', '')
        warehouses.append(store_name)
        if 'стройкерамика' in store_name.lower():
            stock += store.get('StoreQuantRem', store.get('StockRem', 0))

    print(stock)
except Exception as e:
    print('0')
" 2>/dev/null)

  if [ -z "$STOCK" ]; then
    STOCK="0"
  fi

  # Показываем все доступные склады для диагностики
  echo "Доступные склады:"
  echo "$RESPONSE" | jq -r '.data.InfoStores[]? | "  - \(.StoreName): \(.StoreQuantRem // .StockRem // 0)"' 2>/dev/null || echo "  (список складов недоступен)"
  echo ""

  if [ "$STOCK" != "0" ]; then
    STOCK_COUNT=$((STOCK_COUNT + 1))
    echo "✅ Остаток на Стройкерамике: $STOCK"

    # Проверяем совпадение
    DIFF=$(( ($STOCK - $EXPECTED) * 100 / $EXPECTED ))
    DIFF=${DIFF#-}  # Абсолютное значение

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
done

echo "════════════════════════════════════════════════════════════════════════"
echo ""
echo "📊 ИТОГИ ТЕСТА:"
echo "   Всего артикулов: $TOTAL_COUNT"
echo "   Найдено в ETM: $FOUND_COUNT"
echo "   С остатком на Стройкерамике: $STOCK_COUNT"
echo ""
