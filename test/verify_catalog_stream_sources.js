const fs=require('node:fs');
const {google}=require('googleapis');
(async()=>{
  const sheets=google.sheets({version:'v4',auth:new google.auth.GoogleAuth({
    keyFile:'nomadic-bedrock-485314-b0-d7624dedd83c.json',scopes:['https://www.googleapis.com/auth/spreadsheets.readonly']
  })});
  const ranges=["'ТЕСТ'!A1:A25000","'ТЕХ данные wb'!A1:C26000","'StreamSupps'!A1:A22864","'StreamSupps'!D1:E22864","'StreamSupps'!G1:G22864"];
  const data=(await sheets.spreadsheets.values.batchGet({spreadsheetId:'15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI',ranges,valueRenderOption:'UNFORMATTED_VALUE'},{timeout:90000,retry:false})).data.valueRanges.map(x=>x.values||[]);
  const [a,wb,offers,fields,chrt]=data;
  const stream=offers.map((x,k)=>[x[0],null,null,fields[k]?.[0],fields[k]?.[1],null,chrt[k]?.[0]]);
  let status=[];
  try {status=(await sheets.spreadsheets.values.get({spreadsheetId:'15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI',range:"'_CATALOG_STATUS'!A1:B10"})).data.values||[];}
  catch(e) {if(e.response?.status!==400)throw e;}
  const test=new Set(a.slice(1).map(x=>String(x[0]||'').trim()));
  const wbMap=new Map(wb.slice(1).map(x=>[String(x[0]||'').trim(),x[1]]));
  const result={at:new Date().toISOString(),testArticles:a.slice(1).filter(x=>x[0]).length,wbRows:wb.length-1,streamArticles:0,missingTestRows:0,blankBrand:0,blankSku:0,missingWbRows:0,blankChrtId:0,status:Object.fromEntries(status.slice(1))};
  for(const row of stream.slice(1)){if(!row[0])continue;result.streamArticles++;const id=String(row[0]).trim();if(!test.has(id))result.missingTestRows++;if(!row[3])result.blankBrand++;if(!row[4])result.blankSku++;if(!wbMap.has(id))result.missingWbRows++;if(!row[6])result.blankChrtId++;}
  fs.writeFileSync('test/catalog_stream_verification_20261016.json',JSON.stringify(result,null,2));
  console.log(JSON.stringify({...result,status:Object.fromEntries(Object.entries(result.status).filter(([key])=>key!=='ownedTriggers'))}));
})().catch(e=>{console.error(e.message);process.exit(1);});
