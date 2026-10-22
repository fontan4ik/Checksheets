'use strict';
const fs = require('node:fs');
const {google} = require('googleapis');
const rs = require('../sync-rs-stocks');
const {resolveStreamSuppsColumns} = require('../stream_supps_schema');
const spreadsheetId='15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const prefix='test/new_stream_broadcast_20261020';
const save=(name,value)=>fs.writeFileSync(`${prefix}_${name}.json`,JSON.stringify(value,(_k,v)=>v instanceof Set?[...v]:v,2));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const targets=JSON.parse(fs.readFileSync('test/new_stream_targets_20261020.json'));
const lock='/tmp/checksheets_locks/marketplace_ozon.lock';
async function main(){
  const write=process.argv.includes('--apply');
  if(write){fs.mkdirSync(lock);fs.writeFileSync(`${lock}/pid`,String(process.pid));}
  try {
    const sheets=google.sheets({version:'v4',auth:new google.auth.GoogleAuth({keyFile:'nomadic-bedrock-485314-b0-d7624dedd83c.json',scopes:['https://www.googleapis.com/auth/spreadsheets.readonly']})});
    const data=(await sheets.spreadsheets.values.batchGet({spreadsheetId,ranges:["'StreamSupps'!A1:AE1","'StreamSupps'!A21999:AE22487"],valueRenderOption:'UNFORMATTED_VALUE'},{timeout:90000})).data;
    const cols=resolveStreamSuppsColumns(data.valueRanges[0].values[0],{offer:'Артикул продавца',brand:'brand',pack:'Х',code:'CODES',etm:'ЭТМ САМАРА',etmRaw:'ETM SMR',rs:'РЕЗЕРВ',rsRaw:'RS SMR',rsMoscow:{header:'РУССКИЙ СВЕТ МОСКВА',occurrence:1},chrt:'chrlid',wb:'WB ВОЛЬТМИР ИТОГ',wbMoscow:'ФБС ФЕРОН МОСКВА'});
    const rows=data.valueRanges[1].values;
    const snapshotReadAt=new Date().toISOString();
    const stocks=targets.map((t,i)=>{
      const r=rows[i];if(t.row!==21999+i||r[cols.offer-1]!==t.v[0])throw Error('Target offer moved '+t.v[0]);
      for(const f of ['etm','etmRaw','rs','rsRaw','rsMoscow','wb','wbMoscow','pack'])if(r[cols[f]-1]===''||r[cols[f]-1]===undefined||!Number.isFinite(Number(r[cols[f]-1])))throw Error(`Incomplete source ${f}: ${t.v[0]}`);
      if(Number(r[cols.rsMoscow-1])!==0)throw Error('RS Moscow must stay disabled');
      return {offer_id:t.v[0],brand:r[cols.brand-1],chrt_id:r[cols.chrt-1]||null,etm:rs.normalizeMarketplaceStock(r[cols.etm-1],r[cols.brand-1]),rs:rs.normalizeMarketplaceStock(r[cols.rs-1],r[cols.brand-1]),code:r[cols.code-1]||null};
    });
    save('snapshot',{snapshotReadAt,cols,stocks});
    console.log('Snapshot',JSON.stringify({count:stocks.length,withCode:stocks.filter(s=>s.code).length,etmPositive:stocks.filter(s=>s.etm>0).length,rsPositive:stocks.filter(s=>s.rs>0).length,wbIds:stocks.filter(s=>s.chrt_id).length}));
    if(!write)return;
    const reports=[];
    for(const [field,warehouseId] of [['etm',1020005000689690],['rs',rs.RS_OZON_WAREHOUSE_ID]]){
      const payload=stocks.map(s=>({...s,stock:s[field]}));
      const result=await rs.updateRsStocksOzon(payload,{warehouseId,label:`New489 ${field}`});
      save(`${field}_write`,result);
      reports.push({field,warehouseId,result,payload});
    }
    await sleep(30000);
    for(const report of reports){
      let check;
      for(let attempt=0;attempt<3;attempt++){
        const actual=await rs.fetchOzonStocksByOfferIds(stocks.map(s=>s.offer_id),report.warehouseId);
        const mismatches=report.payload.filter(s=>!report.result.skippedOfferIds.has(s.offer_id)&&(actual.get(s.offer_id)?.freeStock??0)!==s.stock).map(s=>({offer_id:s.offer_id,expected:s.stock,actual:actual.get(s.offer_id)||null}));
        check={at:new Date().toISOString(),warehouseId:report.warehouseId,attempted:report.result.attemptedSku,accepted:report.result.acceptedSku,skipped:report.result.skippedSku,errors:report.result.errorSku,actual:[...actual],mismatches};
        save(`${report.field}_verification`,check);
        if(!mismatches.length)break;
        if(attempt<2)await sleep(30000);
      }
      report.verification=check;
      delete report.payload;
      console.log('Verified',report.field,JSON.stringify({accepted:check.accepted,skipped:check.skipped,errors:check.errors,mismatches:check.mismatches.length}));
    }
    save('result',{snapshotReadAt,reports,moscow:'disabled by user',wb:'No chrtId; no WB payload prepared'});
    if(reports.some(r=>r.result.errorSku||r.verification.mismatches.length))process.exitCode=1;
  } finally {
    if(write&&fs.existsSync(`${lock}/pid`)&&fs.readFileSync(`${lock}/pid`,'utf8')===String(process.pid)){fs.unlinkSync(`${lock}/pid`);fs.rmdirSync(lock);}
  }
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
