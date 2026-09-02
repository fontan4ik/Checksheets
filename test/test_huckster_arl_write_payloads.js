const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const sourcePath = path.join(__dirname, '..', 'Huckster цены.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const headers = Array(24).fill('');
headers[0] = 'Артикул';
headers[20] = 'МИНИМАЛЬНАЯ ХАКСТЕР';
headers[22] = 'ВЫСТАВЛЯЕМАЯ ХАКСТЕР';
headers[23] = 'РЦ ХАКСТЕР';

const rows = [Array(24).fill(''), Array(24).fill(''), Array(24).fill('')];
rows[0][0] = 'ART-1';
rows[0][20] = 1000;
rows[0][22] = 1500;
rows[0][23] = 1200;
rows[1][0] = 'ART-2';
rows[1][22] = 2000;
rows[2][0] = 'ART-EMPTY';
const writes = [];
let currentMinPrice = 900;

const sheet = {
  getLastRow: () => 4,
  getLastColumn: () => 24,
  getRange: (startRow, startColumn, numRows, numColumns) => {
    assert.strictEqual(startColumn, 1);
    assert.strictEqual(numColumns, 21);
    assert.strictEqual(numRows, startRow === 1 ? 1 : 3);
    return {
      getValues: () => startRow === 1 ? [headers] : rows
    };
  }
};

function response(code, body) {
  return {
    getResponseCode: () => code,
    getContentText: () => body || ''
  };
}

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
    getActiveSpreadsheet: () => ({ getSheetByName: (name) => name === 'ARL TR' ? sheet : null })
  },
  LockService: {
    getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} })
  },
  Logger: { log: () => {} },
  Utilities: { sleep: () => {} },
  UrlFetchApp: {
    fetch: (url, options) => {
      if (url.endsWith('/md5')) {
        return response(200, '0123456789abcdef0123456789abcdef');
      }
      if (url.endsWith('/auth/credentials')) {
        return response(200, JSON.stringify({ SessionId: 'mock-session' }));
      }
      if (url.endsWith('/markets/integrations/repricer/items/list')) {
        assert.strictEqual(options.headers.Cookie, 'ss-id=mock-session');
        return response(200, JSON.stringify({
          result: [
            { uid: 'uid-1', sku: 'ART-1', enabled: true, card_control: true, max_discount: 5, min_price: currentMinPrice },
            { uid: 'uid-2', sku: 'ART-2', enabled: false, card_control: false, max_discount: 0, min_price: 0 }
          ],
          cursor: { total: 2, offset: 0 }
        }));
      }
      if (url.endsWith('/markets/integrations/repricer/items/set')) {
        const payload = JSON.parse(options.payload);
        currentMinPrice = payload.item_list[0].min_price;
        writes.push({ path: 'repricer', payload });
        return response(200, JSON.stringify({ result: [{ result: 'OK' }] }));
      }
      throw new Error(`Unexpected URL: ${url}`);
    }
  }
};

vm.createContext(context);
vm.runInContext(source, context, { filename: sourcePath });
const report = context.syncHucksterPricesFromArlTr();

assert.strictEqual(report.sourceRows, 1);
assert.strictEqual(report.matchedItems, 1);
assert.strictEqual(report.unmatchedRows, 0);
assert.strictEqual(report.minPriceItems, 1);
assert.strictEqual(report.written, 1);
assert.strictEqual(report.verified, 1);

const repricer = writes.find((write) => write.path === 'repricer');
assert.deepStrictEqual(repricer.payload, {
  marketplace: 'ozon',
  shop_id: 'mock-shop',
  item_list: [{
    uid: 'uid-1',
    enabled: true,
    card_control: true,
    max_discount: 5,
    min_price: 1000,
    sku: 'ART-1'
  }]
});

assert.strictEqual(writes.length, 1);

console.log('test_huckster_arl_write_payloads: PASS');
