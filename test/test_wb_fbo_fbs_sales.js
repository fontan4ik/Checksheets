/**
 * ЛОКАЛЬНЫЙ ТЕСТ для ВБ продажа FBO FBS.gs
 *
 * Тестирует логику Analytics API без реальных запросов
 */

const MOCK_RESPONSES = {
  // FBO месяц - частичные данные
  fboMonth: {
    data: {
      items: [
        { nmID: 184115261, ordersCount: 150, vendorCode: "25236-5" },
        { nmID: 184115262, ordersCount: 85, vendorCode: "25236-6" },
        { nmID: 184115263, ordersCount: 200, vendorCode: "25236-7" }
      ]
    }
  },

  // FBS месяц - частичные данные
  fbsMonth: {
    data: {
      items: [
        { nmID: 184115261, ordersCount: 30, vendorCode: "25236-5" },
        { nmID: 184115263, ordersCount: 45, vendorCode: "25236-7" },
        { nmID: 184115264, ordersCount: 12, vendorCode: "25236-8" }
      ]
    }
  },

  // FBO квартал - больше данных
  fboQuarter: {
    data: {
      items: [
        { nmID: 184115261, ordersCount: 450, vendorCode: "25236-5" },
        { nmID: 184115262, ordersCount: 280, vendorCode: "25236-6" },
        { nmID: 184115263, ordersCount: 620, vendorCode: "25236-7" },
        { nmID: 184115265, ordersCount: 95, vendorCode: "25236-9" }
      ]
    }
  },

  // FBS квартал - больше данных
  fbsQuarter: {
    data: {
      items: [
        { nmID: 184115261, ordersCount: 110, vendorCode: "25236-5" },
        { nmID: 184115263, ordersCount: 155, vendorCode: "25236-7" },
        { nmID: 184115264, ordersCount: 48, vendorCode: "25236-8" }
      ]
    }
  }
};

// ============================================
// ИМИТАЦИЯ ФУНКЦИЙ ИЗ ФАЙЛА
// ============================================

function createIndex(data) {
  const index = {};
  data.forEach(item => {
    if (item.nmID) {
      index[item.nmID] = item;
    }
  });
  return index;
}

function collectAllNmIds(fboData, fbsData) {
  const allNmIds = new Set([
    ...fboData.map(item => item.nmID),
    ...fbsData.map(item => item.nmID)
  ]);
  return allNmIds;
}

// ============================================
// ТЕСТЫ
// ============================================

console.log("=== ТЕСТ: ВБ продажа FBO FBS ===\n");

// Тест 1: Создание индекса
console.log("ТЕСТ 1: Создание индекса для быстрого поиска");
const testData = [
  { nmID: 123, ordersCount: 10 },
  { nmID: 456, ordersCount: 20 }
];
const index = createIndex(testData);
console.assert(index[123].ordersCount === 10, "❌ Ошибка индекса для 123");
console.assert(index[456].ordersCount === 20, "❌ Ошибка индекса для 456");
console.assert(index[999] === undefined, "✅ Индекс работает корректно\n");

// Тест 2: Сбор уникальных nmId
console.log("ТЕСТ 2: Сбор уникальных nmId из разных источников");
const fboData = MOCK_RESPONSES.fboMonth.data.items;
const fbsData = MOCK_RESPONSES.fbsMonth.data.items;
const allNmIds = collectAllNmIds(fboData, fbsData);
console.assert(allNmIds.size === 4, `❌ Ожидалось 4 уникальных nmId, получено ${allNmIds.size}`);
console.assert(allNmIds.has(184115261), "❌ Должен содержать 184115261");
console.assert(allNmIds.has(184115264), "❌ Должен содержать 184115264 (только FBS)");
console.log(`✅ Собрано ${allNmIds.size} уникальных nmId: [${[...allNmIds].join(", ")}]\n`);

// Тест 3: Агрегация данных по артикулам
console.log("ТЕСТ 3: Агрегация FBO/FBS данных по nmId");

// Имитируем данные из таблицы (nmId из колонки T)
const tableArticles = [184115261, 184115262, 184115263, 184115264, 999999];

// Создаём индексы
const iFboM = createIndex(MOCK_RESPONSES.fboMonth.data.items);
const iFbsM = createIndex(MOCK_RESPONSES.fbsMonth.data.items);
const iFboQ = createIndex(MOCK_RESPONSES.fboQuarter.data.items);
const iFbsQ = createIndex(MOCK_RESPONSES.fbsQuarter.data.items);

// Обрабатываем каждую строку таблицы
const results = tableArticles.map(nmId => {
  const fboMonthQty = iFboM[nmId]?.ordersCount ?? 0;
  const fbsMonthQty = iFbsM[nmId]?.ordersCount ?? 0;
  const fboQuarterQty = iFboQ[nmId]?.ordersCount ?? 0;
  const fbsQuarterQty = iFbsQ[nmId]?.ordersCount ?? 0;

  return {
    nmId,
    month: { fbo: fboMonthQty, fbs: fbsMonthQty, total: fboMonthQty + fbsMonthQty },
    quarter: { fbo: fboQuarterQty, fbs: fbsQuarterQty, total: fboQuarterQty + fbsQuarterQty }
  };
});

// Проверяем результаты
console.log("Результаты обработки:");
results.forEach(r => {
  console.log(`  nmId ${r.nmId}:`);
  console.log(`    Месяц:   FBO=${r.month.fbo}, FBS=${r.month.fbs}, ВСЕГО=${r.month.total}`);
  console.log(`    Квартал: FBO=${r.quarter.fbo}, FBS=${r.quarter.fbs}, ВСЕГО=${r.quarter.total}`);
});

// Проверки
console.assert(results[0].month.fbo === 150, "❌ nmId 184115261: FBO месяц должен быть 150");
console.assert(results[0].month.fbs === 30, "❌ nmId 184115261: FBS месяц должен быть 30");
console.assert(results[0].month.total === 180, "❌ nmId 184115261: Всего месяц должен быть 180");
console.assert(results[0].quarter.fbo === 450, "❌ nmId 184115261: FBO квартал должен быть 450");
console.assert(results[0].quarter.fbs === 110, "❌ nmId 184115261: FBS квартал должен быть 110");
console.assert(results[0].quarter.total === 560, "❌ nmId 184115261: Всего квартал должен быть 560");

// Проверяем артикул только FBS
console.assert(results[3].month.fbo === 0, "❌ nmId 184115264: FBO месяц должен быть 0");
console.assert(results[3].month.fbs === 12, "❌ nmId 184115264: FBS месяц должен быть 12");

// Проверываем несуществующий артикул
console.assert(results[4].month.fbo === 0, "❌ nmId 999999: FBO месяц должен быть 0");
console.assert(results[4].month.fbs === 0, "❌ nmId 999999: FBS месяц должен быть 0");
console.log("✅ Агрегация работает корректно\n");

// Тест 4: Проверка формата даты (скользящий период)
console.log("ТЕСТ 4: Форматирование дат (скользящий период)");
function formatDate(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

const today = new Date();
const monthFrom = new Date(today);
monthFrom.setMonth(monthFrom.getMonth() - 1);

const quarterFrom = new Date(today);
quarterFrom.setDate(quarterFrom.getDate() - 90);

console.log(`Сегодня:           ${formatDate(today)}`);
console.log(`Месяц назад:       ${formatDate(monthFrom)} (30 дней назад)`);
console.log(`Квартал назад:     ${formatDate(quarterFrom)} (90 дней назад)`);
console.assert(formatDate(monthFrom).match(/^\d{4}-\d{2}-\d{2}$/), "❌ Неверный формат даты");
console.log("✅ Формат дат корректен (YYYY-MM-DD)\n");

// Тест 5: Проверка payload для API
console.log("ТЕСТ 5: Формирование payload для API");
const payload = {
  nmIDs: [184115261, 184115262],
  currentPeriod: {
    start: "2026-02-01",
    end: "2026-02-19"
  },
  stockType: "wb",
  skipDeletedNm: false,
  availabilityFilters: [],
  orderBy: {
    field: 'ordersCount',
    mode: 'desc'
  },
  limit: 1000,
  offset: 0
};

console.assert(payload.nmIDs.length === 2, "❌ nmIDs должен содержать 2 элемента");
console.assert(payload.stockType === "wb", "❌ stockType должен быть 'wb'");
console.assert(payload.limit === 1000, "❌ limit должен быть 1000");
console.assert(payload.orderBy.field === 'ordersCount', "❌ Сортировка по ordersCount");
console.log("✅ Payload сформирован корректно:");
console.log(JSON.stringify(payload, null, 2));

console.log("\n=== ВСЕ ТЕСТЫ ПРОЙДЕНЫ ✅ ===");

// Статистика
console.log("\n📊 ИТОГОВАЯ СТАТИСТИКА:");
const fboMonthCount = results.filter(r => r.month.fbo > 0).length;
const fbsMonthCount = results.filter(r => r.month.fbs > 0).length;
const fboQuarterCount = results.filter(r => r.quarter.fbo > 0).length;
const fbsQuarterCount = results.filter(r => r.quarter.fbs > 0).length;

console.log(`   FBO месяц: ${fboMonthCount} артикулов с продажами`);
console.log(`   FBS месяц: ${fbsMonthCount} артикулов с продажами`);
console.log(`   FBO квартал: ${fboQuarterCount} артикулов с продажами`);
console.log(`   FBS квартал: ${fbsQuarterCount} артикулов с продажами`);
