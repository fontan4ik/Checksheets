/**
 * ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ ВСЕХ ФУНКЦИЙ
 * Node.js
 */

const fs = require('fs');
const path = require('path');

// ============================================
// MOCK ДАННЫЕ
// ============================================

const OZON_ATTRIBUTES_MOCK = {
  "result": [
    {
      "offer_id": "52065-1",
      "product_id": 123456789,
      "sku": 12345,
      "name": "Пресс гидравлический ручной КВТ ПГР-70",
      "primary_image": "https://cdn-image.ozon.ru/...",
      "description_category_id": 17035473,
      "attributes": [
        {
          "id": 85,
          "values": [{"value": "КВТ"}]
        },
        {
          "id": 9048,
          "values": [{"value": "52065"}]
        }
      ]
    },
    {
      "offer_id": "TR089-1",
      "product_id": 987654321,
      "sku": 54321,
      "name": "Светильник трековый Gauss",
      "primary_image": "https://cdn-image.ozon.ru/...",
      "description_category_id": 17035473,
      "attributes": [
        {
          "id": 85,
          "values": [{"value": "Gauss"}]
        },
        {
          "id": 9048,
          "values": [{"value": "019ab5dc91b07999b68acf91328614ab"}]
        }
      ]
    }
  ]
};

// ============================================
// ФУНКЦИИ ПАРСИНГА (копии из .gs файлов)
// ============================================

function extractAttribute(item, attributeId) {
  if (!item.attributes || !Array.isArray(item.attributes)) {
    return "";
  }

  const attr = item.attributes.find(a => a.id === attributeId);

  if (!attr || !attr.values || attr.values.length === 0) {
    return "";
  }

  const value = attr.values[0];
  return typeof value === "string" ? value : (value.value || "");
}

function extractBrand(item) {
  return extractAttribute(item, 85);
}

function extractModelAttribute(item) {
  const modelIds = [9048, 22390];

  for (const id of modelIds) {
    const value = extractAttribute(item, id);
    if (value) {
      return value;
    }
  }

  return "";
}

// ============================================
// ТЕСТЫ
// ============================================

function testAllParsing() {
  console.log("========================================");
  console.log("🧪 ТЕСТИРОВАНИЕ ПАРСИНГА JSON");
  console.log("========================================\n");

  // Тест 1: Ozon Attributes
  console.log("1️⃣ ТЕСТ: Ozon v4/product/info/attributes");
  console.log("----------------------------------------");
  testParseOzonAttributes();

  // Тест 2: Ozon Stocks
  console.log("\n2️⃣ ТЕСТ: Ozon v4/product/info/stocks");
  console.log("----------------------------------------");
  testParseOzonStocks();

  // Тест 3: Ozon Prices
  console.log("\n3️⃣ ТЕСТ: Ozon v5/product/info/prices");
  console.log("----------------------------------------");
  testParseOzonPrices();

  // Тест 4: WB Stocks
  console.log("\n4️⃣ ТЕСТ: WB stocks");
  console.log("----------------------------------------");
  testParseWBStocks();

  // Тест 5: WB Orders
  console.log("\n5️⃣ ТЕСТ: WB orders");
  console.log("----------------------------------------");
  testParseWBOrders();

  // Тест 6: WB Prices
  console.log("\n6️⃣ ТЕСТ: WB prices");
  console.log("----------------------------------------");
  testParseWBPrices();

  console.log("\n========================================");
  console.log("✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ");
  console.log("========================================");
}

function testParseOzonAttributes() {
  const items = OZON_ATTRIBUTES_MOCK.result;

  console.log(`📦 Получено товаров: ${items.length}\n`);

  items.forEach((item, index) => {
    console.log(`--- Товар ${index + 1}: ${item.offer_id} ---`);
    console.log(`  offer_id:      ${item.offer_id}`);
    console.log(`  product_id:    ${item.product_id}`);
    console.log(`  sku:           ${item.sku}`);
    console.log(`  name:          ${item.name.substring(0, 50)}...`);

    const brand = extractBrand(item);
    console.log(`  Бренд (id=85):  ${brand || "НЕ НАЙДЕН"}`);

    const model = extractModelAttribute(item);
    console.log(`  Модель (9048):  ${model || "НЕ НАЙДЕН"}`);

    console.log(`  Картинка:      ${item.primary_image ? "✅ Есть" : "❌ Нет"}`);
    console.log(`  Attributes:    ${item.attributes.length} шт`);
  });
}

function testParseOzonStocks() {
  const json = JSON.parse(fs.readFileSync('./ozon_api_v4_stocks_response.json', 'utf8'));
  const items = json.items;

  console.log(`📦 Получено товаров: ${items.length}\n`);

  items.forEach((item, index) => {
    console.log(`--- Товар ${index + 1} ---`);
    console.log(`  product_id: ${item.product_id}`);

    const fbo = item.stocks.find(s => s.type === "fbo");
    console.log(`  FBO остаток:  ${fbo ? fbo.present : 0} (зарезервировано: ${fbo ? fbo.reserved : 0})`);

    const fbs = item.stocks.filter(s => s.type === "fbs");
    const totalFBS = fbs.reduce((sum, s) => sum + (s.present || 0), 0);
    console.log(`  FBS остаток:  ${totalFBS}`);

    const warehouse = item.stocks.find(s => s.warehouse_name === "Склад Москва");
    console.log(`  Склад Москва: ${warehouse ? warehouse.present : 0}`);
  });
}

function testParseOzonPrices() {
  const json = JSON.parse(fs.readFileSync('./ozon_api_v5_prices_response.json', 'utf8'));
  const items = json.items;

  console.log(`📦 Получено товаров: ${items.length}\n`);

  items.forEach((item, index) => {
    console.log(`--- Товар ${index + 1} ---`);
    console.log(`  product_id:    ${item.product_id}`);
    console.log(`  ЦЕНА:          ${item.price.price || "НЕТ"} копеек`);
    console.log(`  Старая цена:   ${item.price.old_price || "НЕТ"}`);
    console.log(`  Premium цена:  ${item.price.premium_price || "НЕТ"}`);
  });
}

function testParseWBStocks() {
  const data = JSON.parse(fs.readFileSync('./wb_api_stocks_response.json', 'utf8'));

  console.log(`📦 Получено товаров: ${data.length}\n`);

  data.forEach((item, index) => {
    console.log(`--- Товар ${index + 1} ---`);
    console.log(`  supplierArticle: ${item.supplierArticle}`);
    console.log(`  quantity:        ${item.quantity}`);
    console.log(`  nmId:            ${item.nmId}`);
    console.log(`  barcode:         ${item.barcode}`);
    console.log(`  on site:         ${item.is_on_site_stocks ? "✅ Да" : "❌ Нет"}`);
  });
}

function testParseWBOrders() {
  const data = JSON.parse(fs.readFileSync('./wb_api_orders_response.json', 'utf8'));

  const validOrders = data.filter(o => !o.isCancel);

  console.log(`📦 Всех заказов: ${data.length}`);
  console.log(`📦 Валидных (не отменены): ${validOrders.length}\n`);

  const stats = {};
  validOrders.forEach(order => {
    const art = order.supplierArticle;
    if (!stats[art]) {
      stats[art] = { count: 0, sum: 0 };
    }
    stats[art].count++;
    stats[art].sum += order.priceWithDisc;
  });

  console.log("📊 Статистика по артикулам:");
  Object.entries(stats).forEach(([art, stat]) => {
    console.log(`  ${art}:`);
    console.log(`    Заказов: ${stat.count}`);
    console.log(`    Сумма:   ${stat.sum} руб`);
  });
}

function testParseWBPrices() {
  const json = JSON.parse(fs.readFileSync('./wb_api_prices_response.json', 'utf8'));
  const goods = json.data.listGoods;

  console.log(`📦 Получено товаров: ${goods.length}\n`);

  goods.forEach((item, index) => {
    const price = item.sizes[0]?.price;
    const oldPrice = item.sizes[0]?.oldPrice;

    console.log(`--- Товар ${index + 1} ---`);
    console.log(`  vendorCode:  ${item.vendorCode}`);
    console.log(`  Цена:        ${price || "НЕТ"} копеек`);
    console.log(`  Старая цена: ${oldPrice || "НЕТ"}`);
  });
}

// ============================================
// ТЕСТ СТРУКТУРЫ ТАБЛИЦЫ
// ============================================

function testTableStructure() {
  console.log("\n========================================");
  console.log("📊 ТЕСТ СТРУКТУРЫ ТАБЛИЦЫ");
  console.log("========================================\n");

  const example = JSON.parse(fs.readFileSync('./table_structure_example.json', 'utf8'));

  console.log("Проверка колонок:\n");

  example.table_structure.columns.forEach(col => {
    const hasValue = col.value !== "" && col.value !== null && col.value !== undefined;
    const status = hasValue ? "✅" : "❌";
    const valueDisplay = String(col.value || "").substring(0, 30);

    console.log(`  ${status} ${col.letter} (${col.index}): ${col.name.padEnd(25)} = "${valueDisplay}"`);
  });

  console.log("\n📋 Заполнено колонок:");
  const filled = example.table_structure.columns.filter(c => c.value !== "" && c.value !== null).length;
  console.log(`  ${filled}/${example.table_structure.columns.length} (${(filled / example.table_structure.columns.length * 100).toFixed(1)}%)`);
}

// ============================================
// ЗАПУСК ВСЕХ ТЕСТОВ
// ============================================

function runAllTests() {
  console.log("╔══════════════════════════════════════════╗");
  console.log("║   🧪 ПОЛНОЕ ТЕСТИРОВАНИЕ СИСТЕМЫ      ║");
  console.log("╚══════════════════════════════════════════╝\n");

  testAllParsing();
  testTableStructure();

  console.log("\n╔══════════════════════════════════════════╗");
  console.log("║   ✅ ВСЕ ТЕСТЫ УСПЕШНО ЗАВЕРШЕНЫ      ║");
  console.log("╚══════════════════════════════════════════╝");
}

// Запуск
runAllTests();
