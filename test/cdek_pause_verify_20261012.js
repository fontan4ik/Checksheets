const fs = require('fs');
const path = require('path');
const { google } = require('googleapis');
const sync = require('../sync-cdek-ozon-stocks');

(async () => {
  const auth = new google.auth.GoogleAuth({
    keyFile: path.resolve(__dirname, '../nomadic-bedrock-485314-b0-d7624dedd83c.json'),
    scopes: ['https://www.googleapis.com/auth/spreadsheets'],
  });
  const sheets = google.sheets({ version: 'v4', auth: await auth.getClient() });
  const stocks = await sync.readCdekStocks(sheets);
  const settings = fs.readFileSync(path.resolve(__dirname, '../Shared_Настройки.js'), 'utf8');
  const apiKey = process.env.YANDEX_MARKET_API_KEY || settings.match(/const YANDEX_MARKET_API_KEY_VALUE\s*=\s*['"]([^'"]+)['"]/)?.[1];
  if (!apiKey) throw Error('Missing Yandex credentials');
  const response = await sync.postWithRetry(
    'https://api.partner.market.yandex.ru/v3/businesses/813165/offers/stocks',
    { partnerWarehouseId: 2456454, offerIds: stocks.map(s => s.offer_id) },
    { 'Api-Key': apiKey, 'Content-Type': 'application/json' },
  );
  if (response.data?.status !== 'OK' || response.data?.result?.partnerWarehouseId !== 2456454 || !Array.isArray(response.data.result.offers)) {
    throw Error('Unexpected Yandex stock response');
  }
  const offers = response.data.result.offers;
  const positive = offers.filter(o => o.stocks.some(s => ['FIT', 'AVAILABLE'].includes(s.type) && s.count > 0));
  const missing = stocks.filter(s => !offers.some(o => o.offerId === s.offer_id));
  const report = { time: new Date().toISOString(), requested: stocks.length, returned: offers.length, positive: positive.length, missing: missing.length, offers };
  fs.writeFileSync(path.resolve(__dirname, 'cdek_pause_yandex_result_20261012.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ ...report, offers: undefined }));
  if (positive.length || missing.length) process.exitCode = 2;
})().catch(e => { console.error(e.message); process.exitCode = 1; });
