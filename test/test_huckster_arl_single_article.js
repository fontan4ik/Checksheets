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

const rows = [Array(24).fill(''), Array(24).fill('')];
rows[0][0] = '032431-1';
rows[0][20] = 1000;
rows[0][22] = 1500;
rows[0][23] = 1200;
rows[1][0] = 'OTHER-ARTICLE';
rows[1][20] = 2000;
rows[1][22] = 2500;
rows[1][23] = 2200;
const writes = [];

const sheet = {
  getLastRow: () => 3,
  getRange: (startRow, startColumn, numRows, numColumns) => {
    assert.strictEqual(startColumn, 1);
    assert.strictEqual(numColumns, 24);
    assert.strictEqual(numRows, startRow === 1 ? 1 : 2);
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
            { uid: 'uid-target', sku: '032431-1', enabled: true, card_control: true, max_discount: 5, min_price: 900 },
            { uid: 'uid-other', sku: 'OTHER-ARTICLE', enabled: true, card_control: true, max_discount: 5, min_price: 1900 }
          ],
          cursor: { total: 2, offset: 0 }
        }));
      }
      if (url.endsWith('/catalog_get')) {
        const payload = JSON.parse(options.payload);
        assert.strictEqual(payload.contact, 'mock-user');
        return response(200, JSON.stringify({ retval: { catalog: [
          { uid: 'uid-target', price: 500, retail_price: 1400 },
          { uid: 'uid-other', price: 600, retail_price: 2400 }
        ] } }));
      }
      if (url.endsWith('/markets/price_types/list')) {
        return response(200, JSON.stringify({ result: [
          { price_type_id: 'rrc-id', price_type: 'Мой дополнительный прайс' }
        ] }));
      }
      if (url.endsWith('/markets/integrations/repricer/items/set')) {
        writes.push({ path: 'repricer', payload: JSON.parse(options.payload) });
        return response(200, JSON.stringify({ result: [{ result: 'OK' }] }));
      }
      if (url.endsWith('/catalog_updatePrice')) {
        writes.push({ path: 'catalog', payload: JSON.parse(options.payload) });
        return response(200, '');
      }
      if (url.endsWith('/markets/items/prices/update')) {
        writes.push({ path: 'rrc', payload: JSON.parse(options.payload) });
        return response(200, '');
      }
      throw new Error(`Unexpected URL: ${url}`);
    }
  }
};

vm.createContext(context);
vm.runInContext(source, context, { filename: sourcePath });
const report = context.testSyncHucksterPricesFromArlTr_032431_1();

assert.strictEqual(report.articleFilter, '032431-1');
assert.strictEqual(report.sourceRows, 1);
assert.strictEqual(report.matchedItems, 1);
assert.strictEqual(report.unmatchedRows, 0);
assert.strictEqual(report.minPriceItems, 1);
assert.strictEqual(report.listedPriceItems, 1);
assert.strictEqual(report.rrcPriceItems, 1);
assert.strictEqual(report.written, 3);

const repricer = writes.find((write) => write.path === 'repricer');
assert.deepStrictEqual(repricer.payload.item_list.map((item) => item.uid), ['uid-target']);
assert.strictEqual(repricer.payload.item_list[0].min_price, 1000);

const catalog = writes.find((write) => write.path === 'catalog');
assert.deepStrictEqual(catalog.payload.items, [
  { uid: 'uid-target', price: 500, retail_price: 1500 }
]);

const rrc = writes.find((write) => write.path === 'rrc');
assert.deepStrictEqual(rrc.payload.items, [
  { uid: 'uid-target', price_type_id: 'rrc-id', retail_price: 1200 }
]);

console.log('test_huckster_arl_single_article: PASS');
