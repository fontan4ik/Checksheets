'use strict';
const fs=require('fs'),path=require('path'),{google}=require('googleapis'),axios=require('axios');
const root=path.resolve(__dirname,'../..');require('dotenv').config({path:path.join(root,'.env'),quiet:true});
const rs=require('../../sync-rs-stocks');
const {sendFeronWBStocksBatch}=require('../../sync-feron-stocks');
const {createWbStockAudit}=require('../../wb_stock_audit');
const {createWbStockRateLimiter}=require('../../wb_stock_rate_limiter');
const {resolveStreamSuppsColumns}=require('../../stream_supps_schema');
const id='15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI', wh=rs.RS_OZON_MOSCOW_WAREHOUSE_ID, wbWh=1449484;
const save=(n,v)=>fs.writeFileSync(path.join(__dirname,n+'.json'),JSON.stringify(v,null,2));
const read=n=>JSON.parse(fs.readFileSync(path.join(__dirname,n+'.json'),'utf8'));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const normalize=(n,brand)=>rs.normalizeMarketplaceStock(n,brand);
async function main(){
 const auth=new google.auth.GoogleAuth({keyFile:path.join(root,'nomadic-bedrock-485314-b0-d7624dedd83c.json'),scopes:['https://www.googleapis.com/auth/spreadsheets']});
 const sheets=google.sheets({version:'v4',auth});
 const before=read('sheet.before').valueRanges[0].values;
 const cols=resolveStreamSuppsColumns(before[0],{offer:'Артикул продавца',x:{header:'РУССКИЙ СВЕТ МОСКВА',occurrence:1},brand:'brand',chrt:'chrlid',total:'ФБС ФЕРОН МОСКВА',other:'ПОДОРОЖНИК ФБС'});
 const rows=before.slice(1);
 const phase=process.argv[2];
 if(phase==='disable'){
  if(cols.x!==24)throw Error('X moved; inspect before writing');
  const response=await sheets.spreadsheets.values.update({spreadsheetId:id,range:`StreamSupps!X2:X${before.length}`,valueInputOption:'RAW',requestBody:{values:rows.map(()=>[0])}});
  save('disable.result',response.data);
  const after=await sheets.spreadsheets.values.get({spreadsheetId:id,range:'StreamSupps!A:AG',valueRenderOption:'UNFORMATTED_VALUE'});
  save('sheet.after',after.data);
  const positive=after.data.values.slice(1).filter(r=>Number(r[cols.x-1])!==0&&r[cols.x-1]!==undefined);
  if(positive.length)throw Error('Nonzero X after disabling');
  console.log('Source disabled; X verified zero for '+rows.length+' rows');
 }
 if(phase==='ozon'){
  // Include every current catalog offer, even products absent from StreamSupps.
  const headers=rs.ozonHeaders();
  if(!headers['Api-Key'])throw Error('OZON_API_KEY missing');
  const ids=new Set(rows.map(r=>String(r[cols.offer-1]||'').trim()).filter(Boolean));let cursor='';
  do{const r=await axios.post('https://api-seller.ozon.ru/v3/product/list',{filter:{visibility:'ALL'},last_id:cursor,limit:1000},{headers,timeout:30000});
   for(const p of r.data.result?.items||[])if(p.offer_id)ids.add(String(p.offer_id));
   const next=r.data.result?.last_id; if(!(r.data.result?.items||[]).length||!next||next===cursor)break;cursor=next;
  }while(true);
  const all=[...ids];save('ozon.offers',all);console.log('Ozon catalog+sheet offers: '+all.length);
  const actual=await rs.fetchOzonStocksByOfferIds(all,wh);save('ozon.before',[...actual]);
  const targets=[...actual].filter(([,v])=>v.freeStock>0).map(([offer_id])=>({offer_id,stock_moscow:0}));
  console.log('Ozon positive offers to zero: '+targets.length);
  const result=await rs.updateRsStocksOzon(targets,{warehouseId:wh,stockField:'stock_moscow',label:'RS Moscow disabled'});
  save('ozon.write',{...result,skippedOfferIds:[...result.skippedOfferIds]});
  await sleep(30000);
  const check=await rs.fetchOzonStocksByOfferIds(all,wh);save('ozon.after',[...check]);
  const remaining=[...check].filter(([,v])=>v.freeStock>0);save('ozon.verification',{offers:all.length,warehouseRows:check.size,positive:remaining.length,remaining,accepted:result.acceptedSku,errors:result.errorSku});
  console.log('Ozon verification: '+remaining.length+' positive offers');if(remaining.length||result.errorSku)throw Error('Ozon verification/write failures');
 }
 if(phase==='wb'){
  const now=await sheets.spreadsheets.values.get({spreadsheetId:id,range:'StreamSupps!A:AG',valueRenderOption:'UNFORMATTED_VALUE'});
  const fresh=now.data.values.slice(1);const snapshotReadAt=new Date().toISOString();
  const changed=new Set(rows.filter(r=>Number(r[cols.x-1])>0||String(r[cols.x-1]||'').startsWith('#')).map(r=>String(r[cols.offer-1])));
  const targets=fresh.filter(r=>changed.has(String(r[cols.offer-1]))&&rs.normalizeChrtId(r[cols.chrt-1])).map(r=>{
   const x=Number(r[cols.x-1]||0);if(x!==0)throw Error('X is no longer zero');
   const raw=r[cols.total-1];if(raw!==''&&raw!==undefined&&!Number.isFinite(Number(raw)))throw Error('Invalid pooled stock '+r[0]);
   if(Number(raw||0)!==Math.round(Number(r[cols.other-1]||0)))throw Error('Pooled WB differs from remaining supplier stock '+r[0]);
   return {offerId:String(r[cols.offer-1]),chrtId:rs.normalizeChrtId(r[cols.chrt-1]),amount:normalize(raw,r[cols.brand-1])};
  });
  if(new Set(targets.map(x=>x.chrtId)).size!==targets.length)throw Error('Duplicate chrtIds');
  const token=process.env.WB_API_TOKEN||fs.readFileSync(process.env.WB_API_TOKEN_FILE||path.join(process.env.HOME,'AI agents/secrets/wb_api_token'),'utf8').trim();
  const headers={Authorization:token.toLowerCase().startsWith('bearer ')?token:'Bearer '+token};
  const limiter=createWbStockRateLimiter({requestsPerSecond:2});
  async function fetchActual(){const result=new Map();for(let i=0;i<targets.length;i+=250){await limiter.waitTurn();const r=await axios.post(`https://marketplace-api.wildberries.ru/api/v3/stocks/${wbWh}`,{chrtIds:targets.slice(i,i+250).map(t=>t.chrtId)},{headers,timeout:30000});for(const s of r.data.stocks||[])result.set(Number(s.chrtId),Number(s.amount));}return result;}
  const actual=await fetchActual();save('wb.before',[...actual]);save('wb.targets',targets);
  // Missing WB records with a zero target are already absent from sale; positive targets must exist after writing.
  const pending=targets.filter(t=>(actual.get(t.chrtId)??0)!==t.amount);save('wb.pending',pending);console.log('WB affected='+targets.length+', writes needed='+pending.length);
  const audit=createWbStockAudit({scriptName:'sync-feron-stocks-rs-moscow-disable',sheetName:'StreamSupps',sourceReadAt:snapshotReadAt});
  const failures=[];let accepted=0;
  for(let i=0;i<pending.length;i+=100){const batch=pending.slice(i,i+100),batchIndex=i/100+1;
   const payload=audit.recordPayload({warehouseId:wbWh,warehouseName:'ФБС ФЕРОН МОСКВА',sourceColumn:'AC:ФБС ФЕРОН МОСКВА (M + disabled X=0)',batchIndex,totalBatches:Math.ceil(pending.length/100),items:batch});
   if(payload.shouldWarn)console.log('WB STALE SNAPSHOT '+payload.ageSeconds+' seconds');
   const result=await sendFeronWBStocksBatch(batch.map(({chrtId,amount})=>({chrtId,amount})),wbWh);
   if(result.ok)accepted+=batch.length;
   else if(result.cargoRestriction){for(const t of batch){const one=await sendFeronWBStocksBatch([{chrtId:t.chrtId,amount:t.amount}],wbWh);audit.recordItemResult({warehouseId:wbWh,batchIndex,checksum:payload.checksum,...t,status:one.ok?'success':'error',code:one.code,responseText:one.text});if(one.ok)accepted++;else failures.push({...t,result:one});}}
   else failures.push(...batch.map(t=>({...t,result})));
   audit.recordBatchResult({warehouseId:wbWh,batchIndex,checksum:payload.checksum,status:result.ok?'success':result.cargoRestriction?'individual_fallback':'error',code:result.code,successCount:result.ok?batch.length:0});
   save('wb.write',{accepted,failures,runId:audit.runId});console.log('WB processed '+Math.min(i+100,pending.length)+'/'+pending.length+', accepted='+accepted+', failures='+failures.length);
  }
  await sleep(5000);const after=await fetchActual();save('wb.after',[...after]);
  const mismatch=targets.filter(t=>(after.get(t.chrtId)??0)!==t.amount);
  save('wb.verification',{affected:targets.length,attempted:pending.length,accepted,failures,mismatch,runId:audit.runId});console.log('WB verification mismatches='+mismatch.length);if(mismatch.length)throw Error('WB mismatches');
 }
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
