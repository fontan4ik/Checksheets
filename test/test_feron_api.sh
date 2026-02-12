#!/bin/bash

# ============================================
# ТЕСТ FERON API - Полное тестирование
# ============================================

API_KEY="MzZjNGMzNzMtYWNiMS00MzNhLTk2NTQtNjc4NjM0ZDIwYzYx"
BASE_URL="https://clientapi.shop.feron.ru"

echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║   ТЕСТ FERON API                                                        ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Base URL: $BASE_URL"
echo "API-KEY: ${API_KEY:0:10}..."
echo ""

# ============================================
# ТЕСТ 1: Остатки (Stocks)
# ============================================

echo "════════════════════════════════════════════════════════════════════════"
echo "ТЕСТ 1: Остатки по складам (POST /v1/stocks/list)"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

ARTICLES=("48546" "38269")

for ARTICLE in "${ARTICLES[@]}"; do
  echo "Артикул: $ARTICLE"

  RESPONSE=$(curl -s -X POST "$BASE_URL/v1/stocks/list" \
    -H "API-KEY: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"filter\": [\"$ARTICLE\"]}")

  # Проверяем HTTP код
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/v1/stocks/list" \
    -H "API-KEY: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"filter\": [\"$ARTICLE\"]}")

  if [ "$HTTP_CODE" != "200" ]; then
    echo "  ❌ HTTP $HTTP_CODE"
    continue
  fi

  # Извлекаем остатки по складам с помощью Python
  echo "$RESPONSE" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if not isinstance(data, list):
        print('  ❌ Неверный формат ответа')
        sys.exit(0)

    for item in data:
        code = item.get('code', 'N/A')
        stocks = item.get('stocks', [])
        if not stocks:
            print(f'  Артикул {code}: нет данных об остатках')
            continue

        for stock in stocks:
            warehouse = stock.get('warehouse', 'N/A')
            quantity = stock.get('stock', 0)
            over_limit = stock.get('overLimit', False)
            over_limit_str = ' (больше указанного)' if over_limit else ''
            print(f'  {warehouse}: {quantity}{over_limit_str}')
except Exception as e:
    print(f'  ❌ Ошибка парсинга: {e}')
" 2>/dev/null

  echo ""
done

# ============================================
# ТЕСТ 2: Цены (Prices)
# ============================================

echo "════════════════════════════════════════════════════════════════════════"
echo "ТЕСТ 2: Цены товаров (POST /v1/prices/list)"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

for ARTICLE in "${ARTICLES[@]}"; do
  echo "Артикул: $ARTICLE"

  RESPONSE=$(curl -s -X POST "$BASE_URL/v1/prices/list" \
    -H "API-KEY: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"filter\": [\"$ARTICLE\"]}")

  # Проверяем HTTP код
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/v1/prices/list" \
    -H "API-KEY: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"filter\": [\"$ARTICLE\"]}")

  if [ "$HTTP_CODE" != "200" ]; then
    echo "  ❌ HTTP $HTTP_CODE"
    continue
  fi

  # Извлекаем цены
  echo "$RESPONSE" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if not isinstance(data, list):
        print('  ❌ Неверный формат ответа')
        sys.exit(0)

    for item in data:
        code = item.get('code', 'N/A')
        prices = item.get('prices', [])
        if not prices:
            print(f'  Артикул {code}: нет данных о ценах')
            continue

        for price in prices:
            type_ = price.get('type', 'N/A')
            value = price.get('price', 0)
            print(f'  {type_}: {value} руб.')
except Exception as e:
    print(f'  ❌ Ошибка парсинга: {e}')
" 2>/dev/null

  echo ""
done

# ============================================
# ТЕСТ 3: Товары (Products)
# ============================================

echo "════════════════════════════════════════════════════════════════════════"
echo "ТЕСТ 3: Данные товаров (POST /v1/products/list)"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

for ARTICLE in "${ARTICLES[@]}"; do
  echo "Артикул: $ARTICLE"

  RESPONSE=$(curl -s -X POST "$BASE_URL/v1/products/list" \
    -H "API-KEY: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"filter\": [\"$ARTICLE\"]}")

  # Проверяем HTTP код
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/v1/products/list" \
    -H "API-KEY: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"filter\": [\"$ARTICLE\"]}")

  if [ "$HTTP_CODE" != "200" ]; then
    echo "  ❌ HTTP $HTTP_CODE"
    continue
  fi

  # Извлекаем основные данные
  echo "$RESPONSE" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if not isinstance(data, list):
        print('  ❌ Неверный формат ответа')
        sys.exit(0)

    for item in data:
        code = item.get('code', 'N/A')
        brand = item.get('brand', 'N/A')
        model = item.get('model', 'N/A')
        name = item.get('name', 'N/A')

        # Обрезаем длинное название
        if len(name) > 60:
            name = name[:60] + '...'

        print(f'  Бренд: {brand}')
        print(f'  Модель: {model}')
        print(f'  Название: {name}')

        # Свойства
        properties = item.get('properties', [])
        if properties:
            print(f'  Свойства ({len(properties)} шт.):')
            for prop in properties[:3]:  # Показываем первые 3
                prop_name = prop.get('name', 'N/A')
                prop_value = prop.get('value', 'N/A')
                print(f'    - {prop_name}: {prop_value}')
            if len(properties) > 3:
                print(f'    ... и ещё {len(properties) - 3} свойств')

        # Изображения
        images = item.get('images', [])
        if images:
            print(f'  Изображений: {len(images)}')
            print(f'  Первое: {images[0]}')

        # Файлы
        files = item.get('files', [])
        if files:
            print(f'  Файлов: {len(files)}')
            for f in files:
                f_type = f.get('type', 'N/A')
                print(f'    - {f_type}')

except Exception as e:
    print(f'  ❌ Ошибка парсинга: {e}')
" 2>/dev/null

  echo ""
done

# ============================================
# ТЕСТ 4: Получить один товар по коду
# ============================================

echo "════════════════════════════════════════════════════════════════════════"
echo "ТЕСТ 4: Товар по коду (GET /v1/products/{code})"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

ARTICLE="48546"
echo "Артикул: $ARTICLE"

RESPONSE=$(curl -s -X GET "$BASE_URL/v1/products/$ARTICLE" \
  -H "API-KEY: $API_KEY")

# Проверяем HTTP код
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X GET "$BASE_URL/v1/products/$ARTICLE" \
  -H "API-KEY: $API_KEY")

if [ "$HTTP_CODE" != "200" ]; then
  echo "  ❌ HTTP $HTTP_CODE"
else
  echo "$RESPONSE" | python3 -c "
import json, sys
try:
    item = json.load(sys.stdin)
    print(f'  ✅ Товар найден:')
    print(f'  Код: {item.get(\"code\", \"N/A\")}')
    print(f'  Бренд: {item.get(\"brand\", \"N/A\")}')
    print(f'  Модель: {item.get(\"model\", \"N/A\")}')
    print(f'  Название: {item.get(\"name\", \"N/A\")[:60]}...')
except Exception as e:
    print(f'  ❌ Ошибка парсинга: {e}')
" 2>/dev/null
fi

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ"
echo "════════════════════════════════════════════════════════════════════════"
