#!/usr/bin/env node
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const handlers = [
  'updateProductsV2', 'OzonMain', 'WbMain', 'syncOzonNtcStocksToUnitYnx',
  'updateOzonCancellationsAndReturns', 'updateOzonNTCSalesYesterday',
  'updateOzonReviewCountBL', 'fetchAndUpdateAll', 'maintainArticleColumn',
  'updateOzonFBOSales', 'updateWBFBOFBSSales', 'updateAllFBSStocks',
  'updateOzonPriceIndexBK', 'startFetchAndWriteAnalytics',
  'updateOzonBuyoutOrdersUnitApi', 'updateStockFBO',
  'getOzonPricesOptimized', 'OzonSKUAndAnalytic', 'syncOfferIdWithProductId',
  'getStocksByWarehouseFBS', 'updateOborSummary',
  'syncUnitYnxNtcStocksToYandex', 'updateHucksterPrices',
];
const sources = fs.readdirSync(root).filter(name => name.endsWith('.js'))
  .map(name => ({ name, source: fs.readFileSync(path.join(root, name), 'utf8') }));

for (const handler of handlers) {
  const escaped = handler.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(`^function\\s+${escaped}\\s*\\([^)]*\\)\\s*\\{`, 'm');
  const matches = sources.filter(({ source }) => pattern.test(source));
  assert.strictEqual(matches.length, 1, `${handler}: expected one definition`);
  const { name, source } = matches[0];
  const match = pattern.exec(source);
  assert.ok(source.slice(match.index, match.index + 450).includes('runWithTelegramAlertGAS_'),
    `${handler} in ${name}: no Telegram alert wrapper`);
}
console.log(`PASS ${handlers.length} trigger handlers have Telegram alert wrappers`);
