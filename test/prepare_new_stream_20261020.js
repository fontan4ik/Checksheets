'use strict';
const fs = require('node:fs');
const {google} = require('googleapis');
const {resolveStreamSuppsColumns} = require('../stream_supps_schema');
const spreadsheetId = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const targets = JSON.parse(fs.readFileSync('test/new_stream_targets_20261020.json'));
const sheets = google.sheets({version:'v4',auth:new google.auth.GoogleAuth({
  keyFile:'nomadic-bedrock-485314-b0-d7624dedd83c.json',scopes:['https://www.googleapis.com/auth/spreadsheets']
})});
async function main() {
  const metadata = (await sheets.spreadsheets.get({spreadsheetId,fields:'sheets.properties'})).data;
  const sheetId = metadata.sheets.find(s => s.properties.title === 'StreamSupps').properties.sheetId;
  const response = (await sheets.spreadsheets.values.batchGet({spreadsheetId,
    ranges:["'StreamSupps'!A1:AE3","'StreamSupps'!A21998:AE22487"],valueRenderOption:'FORMULA'}, {timeout:90000})).data;
  fs.writeFileSync('test/new_stream_formula_repair_before_20261020.json',JSON.stringify(response));
  const headers = response.valueRanges[0].values[0];
  const columns = resolveStreamSuppsColumns(headers, {
    offer:'Артикул продавца',samara:'ФЕРОН ФБС',moscow:'ПОДОРОЖНИК ФБС',
    etm:'ЭТМ САМАРА',rs:'РЕЗЕРВ',wb:'WB ВОЛЬТМИР ИТОГ',wbMoscow:'ФБС ФЕРОН МОСКВА',
  });
  const rows = response.valueRanges[1].values;
  if (targets.length !== 489 || targets[0].row !== 21999 || targets.at(-1).row !== 22487) throw Error('Target manifest changed');
  for (const t of targets) if (rows[t.row - 21998]?.[columns.offer-1] !== t.v[0]) throw Error('Offer moved: '+t.v[0]);
  const requests = [];
  const counts = {};
  for (const [field, templateRow] of Object.entries({samara:21998,moscow:21998,wb:2,wbMoscow:2})) {
    const col = columns[field]-1;
    const template = templateRow === 2 ? response.valueRanges[0].values[1][col] : rows[0][col];
    if (!String(template).startsWith('=')) throw Error('Missing template '+field);
    const missing = targets.filter(t => !rows[t.row-21998]?.[col]);
    counts[field] = missing.length;
    for (const t of missing) requests.push({copyPaste:{
      source:{sheetId,startRowIndex:templateRow-1,endRowIndex:templateRow,startColumnIndex:col,endColumnIndex:col+1},
      destination:{sheetId,startRowIndex:t.row-1,endRowIndex:t.row,startColumnIndex:col,endColumnIndex:col+1},
      pasteType:'PASTE_FORMULA',pasteOrientation:'NORMAL'
    }});
  }
  // S and V already have the established per-pack formulas. Never overwrite them.
  for (const t of targets) for (const field of ['etm','rs']) {
    if (!String(rows[t.row-21998]?.[columns[field]-1] || '').startsWith('=')) throw Error('Missing existing '+field+' formula '+t.row);
  }
  fs.writeFileSync('test/new_stream_formula_plan_20261020.json',JSON.stringify({sheetId,columns,counts,requests}));
  console.log('Formula plan',counts);
  if (!process.argv.includes('--apply')) return;
  // Formula-only updates preserve formatting, validation and all source cells.
  if (requests.length) await sheets.spreadsheets.batchUpdate({spreadsheetId,requestBody:{requests}}, {timeout:180000,retry:false});
  console.log('Applied',requests.length,'missing formulas');
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
