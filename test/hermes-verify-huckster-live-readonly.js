const assert = require('assert');
const fs = require('fs');
const https = require('https');
const path = require('path');
const readline = require('readline');
const vm = require('vm');
const { google } = require('googleapis');

const sourcePath = path.join(__dirname, '..', 'Huckster цены.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const spreadsheetId = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const serviceAccountPath = path.join(__dirname, '..', 'nomadic-bedrock-485314-b0-d7624dedd83c.json');
const shopId = '142355_FBO';
const article = '032431-1';

function ask(question) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question(question, (answer) => {
      rl.close();
      resolve(answer);
    });
  });
}

async function askHidden(question) {
  process.stdout.write(question);
  const isTty = Boolean(process.stdin.isTTY);
  if (isTty) process.stdin.setRawMode(true);
  let value = '';
  return new Promise((resolve) => {
    const onData = (chunk) => {
      const text = String(chunk);
      for (const char of text) {
        if (char === '\u0003') process.exit(130);
        if (char === '\r' || char === '\n') {
          process.stdin.off('data', onData);
          if (isTty) process.stdin.setRawMode(false);
          process.stdout.write('\n');
          resolve(value);
          return;
        }
        if (char === '\u007f') value = value.slice(0, -1);
        else value += char;
      }
    };
    process.stdin.on('data', onData);
    process.stdin.resume();
  });
}

function httpJson(apiPath, payload, cookie) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(payload || {});
    const request = https.request({
      hostname: 'wbs.e-teleport.ru',
      path: apiPath,
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
        ...(cookie ? { Cookie: `ss-id=${cookie}` } : {})
      }
    }, (response) => {
      let text = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => { text += chunk; });
      response.on('end', () => resolve({
        getResponseCode: () => response.statusCode,
        getContentText: () => text
      }));
    });
    request.on('error', reject);
    request.write(body);
    request.end();
  });
}

async function readSheetRows() {
  const auth = new google.auth.GoogleAuth({
    keyFile: serviceAccountPath,
    scopes: ['https://www.googleapis.com/auth/spreadsheets.readonly']
  });
  const sheets = google.sheets({ version: 'v4', auth });
  const result = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: "'ARL TR'!A:U",
    majorDimension: 'ROWS'
  });
  return result.data.values || [];
}

(async () => {
  const userName = await ask('Huckster login: ');
  const password = await askHidden('Huckster password: ');
  const values = await readSheetRows();
  const rows = values.slice(1);
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
          HUCKSTER_USER_NAME: userName,
          HUCKSTER_PASSWORD: password,
          HUCKSTER_SHOP_ID: shopId
        }[name] || '')
      })
    },
    SpreadsheetApp: {
      getActiveSpreadsheet: () => ({
        getSheetByName: (name) => name === 'ARL TR' ? {
          getLastRow: () => values.length,
          getRange: (startRow, startColumn, numRows, numColumns) => {
            assert.strictEqual(startRow, 2);
            assert.strictEqual(startColumn, 1);
            assert.strictEqual(numColumns, 21);
            assert.strictEqual(numRows, rows.length);
            return { getValues: () => rows };
          }
        } : null
      })
    },
    LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
    Logger: { log: () => {} },
    Utilities: { sleep: () => {} },
    UrlFetchApp: { fetch: (url, options) => {
      const apiPath = new URL(url).pathname;
      return httpJson(apiPath, JSON.parse(options.payload || '{}'), options.headers && options.headers.Cookie ? options.headers.Cookie.replace(/^ss-id=/, '') : null);
    }}
  };
  vm.createContext(context);
  vm.runInContext(source, context, { filename: sourcePath });

  const sourceRows = context.hucksterReadArlPriceRows_(context.SpreadsheetApp.getActiveSpreadsheet().getSheetByName('ARL TR'), article);
  const session = context.hucksterCreateSession_();
  const items = context.hucksterLoadRepricerItems_(session, shopId);
  const index = context.hucksterIndexItemsByKey_(items);
  const matches = index[article.toLowerCase()] || [];
  const payload = matches.length === 1 && sourceRows.length === 1
    ? context.hucksterBuildRepricerUpdate_(matches[0], sourceRows[0].minPrice)
    : null;

  console.log(JSON.stringify({
    mode: 'live-read-only',
    googleSheetRowsIncludingHeader: values.length,
    sourceRowsForArticle: sourceRows.length,
    sourceMinPrice: sourceRows.length === 1 ? sourceRows[0].minPrice : null,
    hucksterItems: items.length,
    hucksterMatchesForArticle: matches.length,
    hucksterMatch: matches.length === 1 ? {
      uid: matches[0].uid,
      sku: matches[0].sku,
      currentMinPrice: context.hucksterToPrice_(matches[0].min_price)
    } : null,
    wouldWrite: payload ? {
      itemKeys: Object.keys(payload).sort(),
      min_price: payload.min_price,
      uid: payload.uid
    } : null,
    writeEndpointCalled: false
  }, null, 2));
})().catch((error) => {
  console.error(JSON.stringify({ error: String(error && error.message || error) }));
  process.exitCode = 1;
});
