/**
 * ЗАНУЛЕНИЕ ОСТАТКОВ RS НА OZON (ФЕРОН ФБС)
 *
 * Отдельная функция, которая обнуляет остатки на складе ФЕРОН ФБС (Ozon)
 * для всех товаров из листа "StreamSupps".
 *
 * Для работы требует, чтобы в проекте были загружены:
 *   - Синхронизация остатков RS.gs (функции readRSStocksFromSheet, updateRSStocksOzon, rateLimitRPS, RPS, ozonHeaders, retryFetch)
 *   - settings.gs (RPS, ozonHeaders, retryFetch)
 *
 * ЗАПУСК:
 *   zeroRSStocksOnOzon()  — обнулить остатки всех товаров из таблицы
 */

const ZERO_LOG_PREFIX = "🔴 [ЗАНУЛЕНИЕ]";

/**
 * ═══════════════════════════════════════════════
 * ГЛАВНАЯ ФУНКЦИЯ
 * ═══════════════════════════════════════════════
 *
 * Читает товары из листа "StreamSupps" и отправляет stock=0
 * на склад ФЕРОН ФБС через Ozon API.
 *
 * Запускать: zeroRSStocksOnOzon()
 */
function zeroRSStocksOnOzon() {
  const startTime = new Date();

  Logger.log("═══════════════════════════════════════════════");
  Logger.log(`${ZERO_LOG_PREFIX} ЗАНУЛЕНИЕ ОСТАТКОВ НА OZON (ФЕРОН ФБС)`);
  Logger.log("═══════════════════════════════════════════════");

  // ─── Шаг 1: Читаем товары из листа ───
  Logger.log(`${ZERO_LOG_PREFIX} Шаг 1/3: Чтение товаров из листа "${RS_SHEET_NAME}"...`);

  const stocks = readRSStocksFromSheet();

  if (!stocks || stocks.length === 0) {
    Logger.log(`${ZERO_LOG_PREFIX} ❌ Нет товаров для обнуления. Лист "${RS_SHEET_NAME}" пуст или не найден.`);
    return;
  }

  Logger.log(`${ZERO_LOG_PREFIX} ✅ Прочитано ${stocks.length} товаров`);

  // ─── Шаг 2: Принудительно обнуляем остатки ───
  Logger.log(`${ZERO_LOG_PREFIX} Шаг 2/3: Принудительное обнуление остатков...`);

  const zeroStocks = stocks.map(item => ({
    offer_id: item.offer_id,
    chrt_id: item.chrt_id,
    stock: 0,
    original_stock: item.original_stock || item.stock
  }));

  const withOfferId = zeroStocks.filter(s => s.offer_id);
  const withoutOfferId = zeroStocks.filter(s => !s.offer_id);

  Logger.log(`${ZERO_LOG_PREFIX}    - С offer_id: ${withOfferId.length} (будут обнулены)`);
  Logger.log(`${ZERO_LOG_PREFIX}    - Без offer_id: ${withoutOfferId.length} (пропущены)`);

  if (withOfferId.length === 0) {
    Logger.log(`${ZERO_LOG_PREFIX} ❌ Нет товаров с offer_id для отправки на Ozon`);
    return;
  }

  // Показываем несколько примеров для проверки
  Logger.log(`${ZERO_LOG_PREFIX}    Примеры (первые 5):`);
  withOfferId.slice(0, 5).forEach(s => {
    Logger.log(`${ZERO_LOG_PREFIX}      - ${s.offer_id}: ${s.original_stock} → 0`);
  });

  // ─── Шаг 3: Отправляем нули на Ozon ───
  Logger.log(`${ZERO_LOG_PREFIX} Шаг 3/3: Отправка stock=0 на Ozon (склад: ${RS_OZON_WAREHOUSE_ID})...`);

  updateRSStocksOzon(zeroStocks, RS_OZON_WAREHOUSE_ID);

  // ─── Итог ───
  const duration = Math.round((new Date() - startTime) / 1000);
  Logger.log("───────────────────────────────────────────");
  Logger.log(`${ZERO_LOG_PREFIX} ✅ Обнуление завершено за ${duration} сек.`);
  Logger.log(`${ZERO_LOG_PREFIX}    Отправлено запросов: ~${Math.ceil(withOfferId.length / 100)}`);
  Logger.log(`${ZERO_LOG_PREFIX}    Все offer_id отправлены со stock=0`);
  Logger.log("───────────────────────────────────────────");
}

/**
 * ═══════════════════════════════════════════════
 * ТОЛЬКО ПРОВЕРКА (БЕЗ ОТПРАВКИ)
 * ═══════════════════════════════════════════════
 *
 * Показывает, сколько товаров будет обнулено,
 * но НЕ отправляет запросы к API.
 *
 * Запускать: dryRunZeroRSStocksOnOzon()
 */
function dryRunZeroRSStocksOnOzon() {
  Logger.log(`${ZERO_LOG_PREFIX} СУХОЙ ПРОГОН: проверка без отправки`);

  const stocks = readRSStocksFromSheet();

  if (!stocks || stocks.length === 0) {
    Logger.log(`${ZERO_LOG_PREFIX} ❌ Нет товаров`);
    return;
  }

  const withOfferId = stocks.filter(s => s.offer_id);
  const belowThreshold = stocks.filter(s => Number(s.original_stock || s.stock) > 0 && Number(s.original_stock || s.stock) < RS_MIN_STOCK_THRESHOLD);

  Logger.log(`${ZERO_LOG_PREFIX} 📊 Статистика по листу "${RS_SHEET_NAME}":`);
  Logger.log(`${ZERO_LOG_PREFIX}    - Всего товаров: ${stocks.length}`);
  Logger.log(`${ZERO_LOG_PREFIX}    - С offer_id (будут обнулены): ${withOfferId.length}`);
  Logger.log(`${ZERO_LOG_PREFIX}    - Уже с остатком 0: ${stocks.filter(s => Number(s.stock) === 0).length}`);
  Logger.log(`${ZERO_LOG_PREFIX}    - С остатком < ${RS_MIN_STOCK_THRESHOLD}: ${belowThreshold.length}`);
  Logger.log(`${ZERO_LOG_PREFIX}    - С ненулевым остатком: ${stocks.filter(s => Number(s.stock) > 0).length}`);
  Logger.log(`${ZERO_LOG_PREFIX}    - Склад Ozon: ${RS_OZON_WAREHOUSE_ID} (ФЕРОН ФБС)`);
  Logger.log("");
  Logger.log(`${ZERO_LOG_PREFIX} ✅ Это сухой прогон. Запросы к API НЕ отправлялись.`);
  Logger.log(`${ZERO_LOG_PREFIX}    Для реального обнуления запустите: zeroRSStocksOnOzon()`);
}
