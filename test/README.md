# 📁 ПАПКА TEST - Тестирование API и парсинга

## 📋 Содержимое

### 📄 JSON файлы с примерами ответов API:

1. **ozon_api_v4_attributes_response.json** - Ozon v4/product/info/attributes
   - Пример ответа с брендом и моделью
   - Атрибуты: id=85 (Бренд), id=9048 (Модель)

2. **ozon_api_v4_stocks_response.json** - Ozon v4/product/info/stocks
   - FBO и FBS остатки
   - Остатки по складам

3. **ozon_api_v5_prices_response.json** - Ozon v5/product/info/prices
   - Цены товаров
   - Старые цены и premium цены

4. **ozon_api_v3_product_info_response.json** - Ozon v3/product/info/list
   - product_id, sku, sources
   - Для функции updateSkuByProductId()

5. **ozon_api_v1_analytics_response.json** - Ozon v1/analytics/data
   - Уход (количество заказов)
   - Выручка

6. **wb_api_stocks_response.json** - Wildberries stocks
   - supplierArticle (артикул)
   - quantity (остаток)
   - nmId, barcode

7. **wb_api_orders_response.json** - Wildberries orders
   - Заказы с ценами
   - Статус отмены

8. **wb_api_prices_response.json** - Wildberries prices
   - Цены по артикулам
   - Старые цены

9. **table_structure_example.json** - Пример структуры таблицы
   - Все 25 колонок с примерами значений
   - Для проверки правильности заполнения

---

### 📜 .gs файлы для тестирования:

1. **test_api.gs** - Основные тестовые функции
   - `testAllColumns()` - проверка всех колонок таблицы
   - `testOzonAPI()` - тест Ozon API
   - `testWBAPI()` - тест WB API

2. **test_json_parsing.gs** - Тест парсинга JSON
   - `testParseOzonAttributes()` - тест парсинга атрибутов Ozon
   - `testParseOzonStocks()` - тест парсинга остатков Ozon
   - `testParseOzonPrices()` - тест парсинга цен Ozon
   - `testParseWBStocks()` - тест парсинга остатков WB
   - `testParseWBOrders()` - тест парсинга заказов WB

---

## 🚀 Как использовать

### Вариант 1: В Apps Script (с встроенными mock-данными)

1. Загрузите `test_json_parsing.gs` в Apps Script
2. Запустите функции для тестирования парсинга:
   ```javascript
   testParseOzonAttributes();
   testParseOzonStocks();
   testParseWBOrders();
   ```

### Вариант 2: Локально (чтение JSON файлов)

Для локального тестирования можно использовать Node.js:

```javascript
// Пример для локального тестирования
const fs = require('fs');

function testParseOzonAttributes() {
  const json = JSON.parse(fs.readFileSync('test/ozon_api_v4_attributes_response.json', 'utf8'));
  const items = json.result;

  items.forEach(item => {
    const brand = extractAttribute(item, 85);
    const model = extractAttribute(item, 9048);
    console.log(`offer_id: ${item.offer_id}, Бренд: ${brand}, Модель: ${model}`);
  });
}
```

---

## 📊 Структура ответов API

### Ozon v4/product/info/attributes

```json
{
  "result": [
    {
      "offer_id": "52065-1",
      "product_id": 123456789,
      "sku": 12345,
      "name": "Название товара",
      "primary_image": "https://...",
      "attributes": [
        {
          "id": 85,
          "values": [{"value": "Бренд"}]
        },
        {
          "id": 9048,
          "values": [{"value": "Модель"}]
        }
      ]
    }
  ]
}
```

**Ключевые моменты:**
- `data.result` - массив товаров (НЕ `data.items`!)
- `attributes[i].id` - числовой ID атрибута
- `attributes[i].values[0].value` - значение

### Ozon v4/product/info/stocks

```json
{
  "items": [
    {
      "product_id": 123456789,
      "stocks": [
        {"type": "fbo", "present": 15, "reserved": 2},
        {"type": "fbs", "present": 8, "reserved": 1}
      ]
    }
  ]
}
```

### WB stocks

```json
[
  {
    "supplierArticle": "52065-1",
    "quantity": 25,
    "nmId": 12345678,
    "barcode": "4601234567890"
  }
]
```

---

## 🧪 Запуск тестов

### В Apps Script:

```
Выберите функцию → test_json_parsing → testParseOzonAttributes
Нажмите "Выполнить"
Смотрите результат в "View → Logs"
```

### Все тесты сразу:

```javascript
function runAllTests() {
  Logger.log("========================================");
  Logger.log("🧪 ЗАПУСК ВСЕХ ТЕСТОВ");
  Logger.log("========================================");

  testParseOzonAttributes();
  testParseOzonStocks();
  testParseOzonPrices();
  testParseWBStocks();
  testParseWBOrders();

  Logger.log("\n========================================");
  Logger.log("✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ");
  Logger.log("========================================");
}
```

---

## 📝 Ожидаемые результаты

### testParseOzonAttributes:
```
offer_id: 52065-1
product_id: 123456789
sku: 12345
Бренд (id=85): КВТ
Модель (id=9048): 52065
Картинка: Есть
```

### testParseWBOrders:
```
Всех заказов: 3
Валидных заказов (не отменены): 2

Статистика по артикулам:
  52065-1:
    Заказов: 1
    Сумма: 13990
  TR089-1:
    Заказов: 1
    Сумма: 7500
```

---

## ⚠️ Важно

1. **Mock-данные встроены в код** для тестирования без API
2. **В реальном Apps Script** JSON нужно загружать из Drive или встраивать в код
3. **Для реальных API запросов** используйте функции из основных .gs файлов
4. **Проверяйте логи** после каждого теста
