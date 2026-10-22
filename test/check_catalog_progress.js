const fs = require('node:fs');
const {google} = require('googleapis');
(async () => {
  const api = google.sheets({version: 'v4', auth: new google.auth.GoogleAuth({
    keyFile: 'nomadic-bedrock-485314-b0-d7624dedd83c.json',
    scopes: ['https://www.googleapis.com/auth/spreadsheets.readonly']
  })});
  const response = await api.spreadsheets.values.batchGet({
    spreadsheetId: '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI',
    ranges: ["'_CATALOG_STATUS'!A1:B10", "'_WB_TECH_CATALOG_STAGE'!A1:A30000"],
    valueRenderOption: 'FORMULA'
  }, {timeout: 20000, retry: false});
  const [status, stage] = response.data.valueRanges;
  const result = {
    at: new Date().toISOString(),
    status: Object.fromEntries((status.values || []).slice(1).filter(r => r[0] !== 'ownedTriggers')),
    stagedRows: (stage.values || []).filter(r => r[0]).length
  };
  fs.writeFileSync('test/catalog_progress_latest_20261016.json', JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
})().catch(error => {console.error(error.message); process.exit(1);});
