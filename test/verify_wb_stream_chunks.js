const fs = require('node:fs');
const {google} = require('googleapis');
(async () => {
  const api = google.sheets({version:'v4', auth:new google.auth.GoogleAuth({
    keyFile:'nomadic-bedrock-485314-b0-d7624dedd83c.json',
    scopes:['https://www.googleapis.com/auth/spreadsheets.readonly']
  })});
  const spreadsheetId = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
  const sources = (await api.spreadsheets.values.batchGet({spreadsheetId,
    ranges:["'StreamSupps'!A1:A22864", "'ТЕХ данные wb'!A1:C26000"],
    valueRenderOption:'FORMULA'}, {timeout:30000,retry:false})).data.valueRanges;
  const results = await Promise.allSettled(Array.from({length:5}, async (_, index) => {
    const first = 2 + index*5000, last = Math.min(first+4999,22864);
    const response = await api.spreadsheets.values.get({spreadsheetId,
      range:`'StreamSupps'!G${first}:G${last}`, valueRenderOption:'UNFORMATTED_VALUE'},
      {timeout:60000,retry:false});
    return {first, values:response.data.values || []};
  }));
  const cells = new Map(), errors=[];
  results.forEach((result,index) => {
    if(result.status==='rejected') errors.push({chunk:index,error:result.reason.message});
    else result.value.values.forEach((row,index) => cells.set(result.value.first+index,row[0]));
  });
  const wb = new Map();
  (sources[1].values||[]).slice(1).forEach(row=>{
    const offer=String(row[0]||'').trim();
    if(!wb.has(offer))wb.set(offer,String(row[1]||''));
  });
  const offers = sources[0].values||[];
  const report = {at:new Date().toISOString(),wbRows:(sources[1].values||[]).length-1,
    streamArticles:0,blankChrtId:0,missingWbRows:0,sourceHasIdButStreamBlank:0,
    mismatchedIds:0,errors};
  offers.slice(1).forEach((row,index) => {
    if(!row[0])return;
    report.streamArticles++;
    const expected=wb.get(String(row[0]).trim()), actual=String(cells.get(index+2)||'');
    if(!wb.has(String(row[0]).trim()))report.missingWbRows++;
    if(!actual)report.blankChrtId++;
    if(expected&&!actual)report.sourceHasIdButStreamBlank++;
    if(expected&&actual&&expected!==actual)report.mismatchedIds++;
  });
  fs.writeFileSync('test/wb_stream_final_verification_20261016.json',JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
  if(errors.length)process.exitCode=1;
})().catch(error=>{console.error(error.message);process.exit(1);});
