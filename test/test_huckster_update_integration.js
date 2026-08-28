const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const sourcePath = path.join(__dirname, '..', 'Huckster цены.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const headers = Array(69).fill('');
headers[0] = 'Артикул';
headers[21] = 'SKU Ozon';
headers[65] = 'Текущая цена';
headers[66] = 'РЦ для удержания';
headers[67] = 'Цена на витрине с картой Х';
headers[68] = 'Мин цена продажи Х';

const row = Array(69).fill('');
row[0] = '024339(2)-1';
row[21] = '024339(2)-1';
row[65] = 6573;
row[66] = 4141.2;
row[67] = 0;
row[68] = 0;
const writes = {};

function columnValues(column) {
  return [[row[column - 1]]];
}

const sheet = {
  getLastRow: () => 2,
  getLastColumn: () => 69,
  getRange: (startRow, startColumn, numRows, numColumns) => {
    if (startRow === 1) {
      assert.strictEqual(startColumn, 1);
      assert.strictEqual(numRows, 1);
      assert.strictEqual(numColumns, headers.length);
      return { getDisplayValues: () => [headers] };
    }
    assert.strictEqual(numColumns, 1, `unexpected multi-column range at ${startRow}:${startColumn}`);
    return {
      getDisplayValues: () => columnValues(startColumn),
      getValues: () => columnValues(startColumn),
      setValues: (values) => { writes[startColumn] = values; }
    };
  }
};

const context = {
  Array,
  JSON,
  Number,
  String,
  Math,
  isFinite,
  PropertiesService: {
    getScriptProperties: () => ({
      getProperty: (name) => ({
        HUCKSTER_USER_NAME: 'mock-user',
        HUCKSTER_PASSWORD: 'mock-password',
        HUCKSTER_SHOP_ID: 'mock-shop'
      }[name] || '')
    })
  },
  SpreadsheetApp: {
    getActiveSpreadsheet: () => ({ getSheetByName: () => sheet })
  },
  LockService: {
    getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} })
  },
  Logger: { log: () => {} },
  Utilities: { sleep: () => {} },
  UrlFetchApp: {
    fetch: (url, options) => {
      if (url.endsWith('/md5')) {
        return { getResponseCode: () => 200, getContentText: () => '0123456789abcdef0123456789abcdef' };
      }
      if (url.endsWith('/auth/credentials')) {
        return { getResponseCode: () => 200, getContentText: () => JSON.stringify({ SessionId: 'mock-session' }) };
      }
      if (url.endsWith('/markets/integrations/repricer/items/list')) {
        assert.strictEqual(options.headers.Cookie, 'ss-id=mock-session');
        return {
          getResponseCode: () => 200,
          getContentText: () => JSON.stringify({
            result: [{
              sku: '024339(2)-1',
              upload_price: 6573,
              market_price: 4601,
              market_card_price: 4141.2,
              market_card_discount: 5.08,
              min_price: 5398
            }],
            cursor: { total: 1, offset: 0 }
          })
        };
      }
      throw new Error(`Unexpected URL: ${url}`);
    }
  }
};

vm.createContext(context);
vm.runInContext(source, context, { filename: sourcePath });
const report = context.updateHucksterPrices();

assert.strictEqual(report.matchedItems, 1);
assert.strictEqual(report.updatedRows, 1);
assert.deepStrictEqual(writes[66], [[6573]]);
assert.deepStrictEqual(writes[67], [[4141.2]]);
assert.deepStrictEqual(writes[68], [[4141.2]], 'target column must receive market_card_price, not market_card_discount');
assert.deepStrictEqual(writes[69], [[5398]]);
console.log('test_huckster_update_integration: PASS');
