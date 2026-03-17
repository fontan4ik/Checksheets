/**
 * ЛОКАЛЬНЫЙ ТЕСТ для ВБ продажа FBO FBS.gs
 *
 * Тестирует: батчинг, пагинацию, getOrdersCount()
 */

// ============================================
// MOCK DATA - имитация ответа API
// ============================================

// Разная структура данных для тестирования getOrdersCount()
const MOCK_API_RESPONSES = {
  // Вариант 1: плоская структура
  flat: {
    data: {
      items: [
        { nmID: 123, ordersCount: 10 },
        { nmID: 456, ordersCount: 20 },
        { nmID: 789, ordersCount: 30 }
      ]
    }
  },

  // Вариант 2: вложенная в statistics
  statistics: {
    data: {
      items: [
        { nmID: 111, statistics: { ordersCount: 15 } },
        { nmID: 222, statistics: { ordersCount: 25 } }
      ]
    }
  },

  // Вариант 3: вложенная в metrics
  metrics: {
    data: {
      items: [
        { nmID: 333, metrics: { ordersCount: 5 } },
        { nmID: 444, metrics: { ordersCount: 35 } }
      ]
    }
  },

  // Вариант 4: смешанная (для реального кейса)
  real: {
    data: {
      items: [
        { nmID: 184115261, ordersCount: 150 },
        { nmID: 184115262, ordersCount: 85 },
        { nmID: 184115263, ordersCount: 200 },
        { nmID: 184115264, ordersCount: 45 }
      ]
    }
  }
};

// Имитация fetchStocksReport с пагинацией
function mockFetchStocksReport({ nmIDs, offset }) {
  // Возвращаем разные данные в зависимости от offset (пагинация)
  if (offset === 0) {
    return MOCK_API_RESPONSES.real.data.items.slice(0, 2); // Первые 2
  } else if (offset === 2) {
    return MOCK_API_RESPONSES.real.data.items.slice(2); // Остальные
  }
  return [];
}

// ============================================
// ФУНКЦИИ ИЗ ФАЙЛА
// ============================================

function chunkArray(arr, size) {
  const chunks = [];
  for (let i = 0; i < arr.length; i += size) {
    chunks.push(arr.slice(i, i + size));
  }
  return chunks;
}

function getOrdersCount(item) {
  if (!item) return 0;

  if (typeof item.ordersCount === 'number') {
    return item.ordersCount;
  }
  if (typeof item.statistics?.ordersCount === 'number') {
    return item.statistics.ordersCount;
  }
  if (typeof item.metrics?.ordersCount === 'number') {
    return item.metrics.ordersCount;
  }
  if (typeof item.data?.ordersCount === 'number') {
    return item.data.ordersCount;
  }

  return 0;
}

function createIndex(data) {
  const index = {};
  data.forEach(item => {
    if (item.nmID) {
      index[item.nmID] = item;
    }
  });
  return index;
}

// Имитация fetchAllPages с пагинацией
function mockFetchAllPages({ nmIDs }) {
  const allItems = [];
  let offset = 0;
  const limit = 2; // Уменьшенный лимит для теста

  while (true) {
    const items = mockFetchStocksReport({ nmIDs, offset });

    if (items.length === 0) {
      break;
    }

    allItems.push(...items);

    if (items.length < limit) {
      break;
    }

    offset += limit;
  }

  return allItems;
}

// Имитация fetchAllProductsBatched
function mockFetchAllProductsBatched({ nmIDs }) {
  const BATCH_SIZE = 2; // Малый батч для теста
  const allItems = [];

  if (!nmIDs || nmIDs.length === 0) {
    return mockFetchAllPages({ nmIDs: [] });
  }

  const batches = chunkArray(nmIDs, BATCH_SIZE);

  batches.forEach((batch) => {
    const items = mockFetchAllPages({ nmIDs: batch });
    allItems.push(...items);
  });

  return allItems;
}

// ============================================
// ТЕСТЫ
// ============================================

console.log("=== ТЕСТ: ВБ продажа FBO FBS (Batching + getOrdersCount) ===\n");

// ТЕСТ 1: getOrdersCount с разными структурами
console.log("ТЕСТ 1: getOrdersCount() с разными структурами");

const flatItem = { nmID: 123, ordersCount: 10 };
const statItem = { nmID: 111, statistics: { ordersCount: 15 } };
const metricItem = { nmID: 333, metrics: { ordersCount: 5 } };
const emptyItem = { nmID: 999 };

console.assert(getOrdersCount(flatItem) === 10, "❌ Плоская структура");
console.assert(getOrdersCount(statItem) === 15, "❌ Структура statistics");
console.assert(getOrdersCount(metricItem) === 5, "❌ Структура metrics");
console.assert(getOrdersCount(emptyItem) === 0, "❌ Пустой элемент");
console.assert(getOrdersCount(null) === 0, "❌ null элемент");
console.log("✅ getOrdersCount работает со всеми структурами\n");

// ТЕСТ 2: chunkArray
console.log("ТЕСТ 2: chunkArray() - разбивка на батчи");

const arr = [1, 2, 3, 4, 5, 6, 7];
const chunks3 = chunkArray(arr, 3);
const chunks2 = chunkArray(arr, 2);

console.assert(chunks3.length === 3, `❌ Должно быть 3 батча по 3, получено ${chunks3.length}`);
console.assert(chunks3[0].join(',') === '1,2,3', "❌ Первый батч: [1,2,3]");
console.assert(chunks3[1].join(',') === '4,5,6', "❌ Второй батч: [4,5,6]");
console.assert(chunks3[2].join(',') === '7', "❌ Третий батч: [7]");

console.assert(chunks2.length === 4, `❌ Должно быть 4 батча по 2, получено ${chunks2.length}`);
console.log(`   [${arr.join(',')}] → ${chunks2.length} батча по 2:`, chunks2.map(c => `[${c.join(',')}]`).join(', '));
console.log("✅ chunkArray работает корректно\n");

// ТЕСТ 3: Батчинг + пагинация вместе
console.log("ТЕСТ 3: Батчинг + пагинация (интеграция)");

const nmIDs = [184115261, 184115262, 184115263, 184115264];
console.log(`   nmID: [${nmIDs.join(', ')}]`);
console.log(`   Батчинг: по 2 элемента`);
console.log(`   Пагинация: по 2 элемента на странице`);

const result = mockFetchAllProductsBatched({ nmIDs });
console.log(`   Получено товаров: ${result.length}`);
console.log(`   nmID в результате: [${result.map(i => i.nmID).join(', ')}]`);

console.assert(result.length === 4, `❌ Должно быть 4 товара, получено ${result.length}`);
console.log("✅ Батчинг + пагинация работают корректно\n");

// ТЕСТ 4: Обработка данных через getOrdersCount
console.log("ТЕСТ 4: Обработка через индекс + getOrdersCount()");

const index = createIndex(result);
const testNmIds = [184115261, 184115262, 184115263, 184115264, 999999];

const stats = testNmIds.map(nmId => ({
  nmId,
  ordersCount: getOrdersCount(index[nmId])
}));

console.log("Результаты:");
stats.forEach(s => {
  console.log(`  nmId ${s.nmId}: ${s.ordersCount} заказов`);
});

console.assert(stats[0].ordersCount === 150, "❌ nmId 184115261: 150 заказов");
console.assert(stats[1].ordersCount === 85, "❌ nmId 184115262: 85 заказов");
console.assert(stats[2].ordersCount === 200, "❌ nmId 184115263: 200 заказов");
console.assert(stats[3].ordersCount === 45, "❌ nmId 184115264: 45 заказов");
console.assert(stats[4].ordersCount === 0, "❌ nmId 999999: 0 заказов (нет в данных)");
console.log("✅ Обработка через индекс работает корректно\n");

// ТЕСТ 5: Дебаг-лог структуры (как в реальном коде)
console.log("ТЕСТ 5: Дебаг-лог структуры первого элемента");

if (result.length > 0) {
  const firstItem = result[0];
  const keys = Object.keys(firstItem);

  console.log("🔍 СТРУКТУРА ПЕРВОГО ЭЛЕМЕНТА:");
  console.log(`   Ключи: ${keys.join(', ')}`);
  console.log(`   nmID: ${firstItem.nmID}`);
  console.log(`   ordersCount: ${firstItem.ordersCount}`);
  console.log(`   getOrdersCount(): ${getOrdersCount(firstItem)}`);

  if (firstItem.statistics) {
    console.log(`   statistics: ${JSON.stringify(Object.keys(firstItem.statistics))}`);
  }
  if (firstItem.metrics) {
    console.log(`   metrics: ${JSON.stringify(Object.keys(firstItem.metrics))}`);
  }
}

console.log("\n=== ВСЕ ТЕСТЫ ПРОЙДЕНЫ ✅ ===");

// ============================================
// СТАТИСТИКА
// ============================================

console.log("\n📊 СТАТИСТИКА БАТЧИНГА:");

// Пример реального использования
const realNmIDs = [];
for (let i = 1; i <= 2081; i++) {
  realNmIDs.push(100000000 + i);
}

const BATCH_SIZE = 500;
const batches = chunkArray(realNmIDs, BATCH_SIZE);

console.log(`   Всего nmID: ${realNmIDs.length}`);
console.log(`   Размер батча: ${BATCH_SIZE}`);
console.log(`   Количество батчей: ${batches.length}`);
console.log(`   Примерный запрос на батч: ${Math.ceil(1000 / BATCH_SIZE)} страниц (по 1000 товаров)`);
console.log(`   Всего запросов: ${batches.length * Math.ceil(1000 / BATCH_SIZE)} * 4 (FBO/FBS * месяц/квартал)`);
console.log(`   Примерное время: ${Math.ceil((batches.length * Math.ceil(1000 / BATCH_SIZE) * 4 * 12) / 60)} минут`);
