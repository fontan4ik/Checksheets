/**
 * ИТОГОВАЯ ФУНКЦИЯ - ОБНОВЛЕНИЕ ВСЕХ НОВЫХ КОЛОНОК
 *
 * Запускает все функции обновления для новых колонок:
 *
 * Ozon:
 * - AQ (43): Продажи штуки месяц FBO ОЗОН
 * - AR (44): Продажи штуки месяц FBS ОЗОН
 * - AS (45): Продажи штуки квартал FBO ОЗОН
 * - AT (46): Продажи штуки квартал FBS ОЗОН
 * - AU (47): Расход по рекламе по ску ОЗОН
 *
 * Wildberries:
 * - AV (48): Продажи штуки месяц FBO ВБ
 * - AW (49): Продажи штуки месяц FBS ВБ
 * - AX (50): Продажи штуки квартал FBO ВБ
 * - AY (51): Продажи штуки квартал FBS ВБ
 */

/**
 * Обновить все новые колонки (Ozon + WB)
 */
function updateAllNewColumns() {
  Logger.log('');
  Logger.log('='.repeat(80));
  Logger.log('ОБНОВЛЕНИЕ ВСЕХ НОВЫХ КОЛОНОК');
  Logger.log('='.repeat(80));
  Logger.log('');

  // Ozon продажи FBO/FBS
  Logger.log('');
  Logger.log('--- ШАГ 1/3: OZON FBO/FBS ПРОДАЖИ ---');
  updateOzonSalesFBOFBS();

  Utilities.sleep(2000);

  // Ozon реклама
  Logger.log('');
  Logger.log('--- ШАГ 2/3: OZON РЕКЛАМА ---');
  updateOzonAds();

  Utilities.sleep(2000);

  // WB продажи FBO/FBS
  Logger.log('');
  Logger.log('--- ШАГ 3/3: WB FBO/FBS ПРОДАЖИ ---');
  updateWBSalesFBOFBS();

  Logger.log('');
  Logger.log('='.repeat(80));
  Logger.log('✅ ВСЕ НОВЫЕ КОЛОНКИ ОБНОВЛЕНЫ');
  Logger.log('='.repeat(80));
  Logger.log('');
}

/**
 * Обновить только Ozon (FBO/FBS + реклама)
 */
function updateOzonAllNew() {
  Logger.log('');
  Logger.log('='.repeat(80));
  Logger.log('ОБНОВЛЕНИЕ OZON (FBO/FBS + РЕКЛАМА)');
  Logger.log('='.repeat(80));
  Logger.log('');

  // Ozon продажи FBO/FBS
  Logger.log('');
  Logger.log('--- ШАГ 1/2: OZON FBO/FBS ПРОДАЖИ ---');
  updateOzonSalesFBOFBS();

  Utilities.sleep(2000);

  // Ozon реклама
  Logger.log('');
  Logger.log('--- ШАГ 2/2: OZON РЕКЛАМА ---');
  updateOzonAds();

  Logger.log('');
  Logger.log('='.repeat(80));
  Logger.log('✅ OZON ОБНОВЛЕН');
  Logger.log('='.repeat(80));
  Logger.log('');
}

/**
 * Обновить только WB (FBO/FBS)
 */
function updateWBAllNew() {
  Logger.log('');
  Logger.log('='.repeat(80));
  Logger.log('ОБНОВЛЕНИЕ WB (FBO/FBS ПРОДАЖИ)');
  Logger.log('='.repeat(80));
  Logger.log('');

  // WB продажи FBO/FBS
  updateWBSalesFBOFBS();

  Logger.log('');
  Logger.log('='.repeat(80));
  Logger.log('✅ WB ОБНОВЛЕН');
  Logger.log('='.repeat(80));
  Logger.log('');
}

/**
 * Обновить Ozon рекламу
 */
function updateOzonAds() {
  updateOzonAdExpenses();
}
