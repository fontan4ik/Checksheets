'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const disconnectedOwnership = require('../ntc_wb_ownership');
// Retain coverage for the explicitly resumable live mode in an isolated module.
const liveModule = {exports:{}};
vm.runInNewContext(fs.readFileSync('ntc_wb_ownership.js','utf8').replace(
 'const NTC_LIVE_CATALOG_SYNC_ENABLED = false;', 'const NTC_LIVE_CATALOG_SYNC_ENABLED = true;'
), {module:liveModule});
const {NTC_CLOUD_OFFERS,refreshNtcCloudWbOwnership,isNtcCloudWbOwned,filterLocalWbOwned} = liveModule.exports;
async function main() {
let ntcReads = 0;
const disconnected = await disconnectedOwnership.refreshNtcCloudWbOwnership({spreadsheets:{values:{get:async()=>{
 ntcReads++; throw new Error('NTC access must stay disabled');
}}}});
assert.equal(ntcReads,0);
assert.equal(disconnected.liveSyncEnabled,false);
assert.equal(disconnected.offers,24);
assert.equal(disconnected.chrtIds,24);
assert.equal(disconnectedOwnership.isNtcCloudWbOwned(798761,'1029089-3'),true);
assert.equal(disconnectedOwnership.isNtcCloudWbOwned(798761,'ALIAS',348088279),true);
assert.equal(disconnectedOwnership.isNtcCloudWbOwned(798761,'55189-20'),true);
assert.equal(disconnectedOwnership.isNtcCloudWbOwned(798761,'OTHER'),false);
assert.equal(disconnectedOwnership.isNtcCloudWbOwned(1449484,'1029089-3'),false);
console.log('NTC disconnected ownership: zero NTC reads, 24 protected offers/chrtIds');
assert.throws(() => filterLocalWbOwned([],798761), /not been verified/);
const liveRows = [['Артикул продавца','chrlid'],['55189-20',987654]];
const sheets = {spreadsheets:{values:{get:async request => {
 assert.equal(request.spreadsheetId,'1i35SfWZljNR63GEkPuwgU2zVSU_Y2CWoxcRK-LcpjUo');
 return {data:{values:liveRows}};
}}}};
await refreshNtcCloudWbOwnership(sheets);
assert.equal(isNtcCloudWbOwned(798761,'55189-20'),true);
assert.equal(isNtcCloudWbOwned(798761,'OTHER_ALIAS',987654),true);
assert.equal(isNtcCloudWbOwned(1449484,'55189-20'),false);
liveRows.push(['NEXT-3','']);
await refreshNtcCloudWbOwnership(sheets);
assert.equal(isNtcCloudWbOwned(798761,'NEXT-3'),true,'new incomplete offers protected before enrichment');
liveRows[liveRows.length-1][1]=765432;
await refreshNtcCloudWbOwnership(sheets);
assert.equal(isNtcCloudWbOwned(798761,'ALIAS',765432),true,'newly enriched chrtId reread before next write');
assert.equal(NTC_CLOUD_OFFERS.length,21);
const ctx = vm.createContext({});
vm.runInContext(fs.readFileSync('ntc-cloud/Shared_Seed.js','utf8')+'; globalThis.seed = NTC_SEED;',ctx);
assert.deepEqual(Array.from(NTC_CLOUD_OFFERS).sort(),Object.keys(ctx.seed.engine.manual_k).sort(),'ownership matches migrated ledger');
const owned={offer_id:NTC_CLOUD_OFFERS[0],chrlid:123,amount:0}, other={offer_id:'OTHER',chrlid:321,amount:5};
assert.equal(isNtcCloudWbOwned(798761,owned.offer_id),true);
assert.equal(isNtcCloudWbOwned(1449484,owned.offer_id),false);
assert.equal(isNtcCloudWbOwned(798761,'OTHER'),false);
assert.deepEqual(Array.from(filterLocalWbOwned([owned,other],798761)),[other]);
assert.deepEqual(Array.from(filterLocalWbOwned([owned,other],1449484)),[owned,other]);
assert.equal(owned.amount,0,'filter never changes amounts');
const etm=fs.readFileSync('sync-etm-stocks.js','utf8');
assert.match(etm,/const validStocks = filterLocalWbOwned\(stocks, ETM_TR_WB_WAREHOUSE\)/);
assert.match(etm,/const expected = filterLocalWbOwned\(stocks, ETM_TR_WB_WAREHOUSE\)/);
assert.match(etm,/!isNtcCloudWbOwned\(ETM_TR_WB_WAREHOUSE, offersByChrtId.get/,'repair respects ownership');
const feron=fs.readFileSync('sync-feron-stocks.js','utf8');
assert.match(feron,/const warehouseStocks = filterLocalWbOwned\(validStocks, wh.id\)/);
assert.match(feron,/const batch = warehouseStocks.slice/,'filter happens before preparation/audit');
assert.match(etm,/audit.recordPayload/); assert.match(feron,/audit.recordPayload/);
console.log('NTC WB ownership tests passed');
function loadWriter(file, name, next, context) {
 const source=fs.readFileSync(file,'utf8'), start=source.indexOf('async function '+name+'('), end=source.indexOf('async function '+next+'(',start);
 assert(start>=0 && end>start); const sandbox=vm.createContext({log(){},filterLocalWbOwned,isNtcCloudWbOwned,refreshNtcCloudWbOwnership:async()=>{},google:{sheets:()=>({})},...context});
 vm.runInContext(source.slice(start,end),sandbox); return sandbox[name];
}
async function checkAdditionalWriters() {
 const sourceRows=NTC_CLOUD_OFFERS.map((offer_id,i)=>({offer_id,chrt_id:i+1,chrlid:i+1,wb_stock:5}));
 sourceRows.push({offer_id:'55189-20',chrt_id:987654,chrlid:987654,wb_stock:5});
 sourceRows.push({offer_id:'OTHER_ALIAS',chrt_id:987654,chrlid:987654,wb_stock:5});
 sourceRows.push({offer_id:'OTHER',chrt_id:99,chrlid:99,wb_stock:8});
 const sent=[], prepared=[];
 const rs=loadWriter('sync-rs-stocks.js','updateRsStocksWb','main',{
  RS_WB_WAREHOUSE_ID:798761,SHEET_NAME:'StreamSupps',BATCH_SIZE_WB:200,normalizeChrtId:Number,
  createWbStockAudit:()=>({runId:'test',filePath:'test',recordPayload:p=>{prepared.push(p);return {checksum:'sum'};},recordBatchResult(){}}),
  sendRsWbStocksBatch:async p=>{sent.push(p);return {ok:true,code:204};},
 });
 await rs(sourceRows);
 assert.equal(sent.length,1);assert.equal(sent[0].length,1);assert.equal(sent[0][0].offerId,'OTHER');
 assert.equal(prepared[0].items.length,1,'RS ownership exclusion precedes audit');
 sent.length=0;
 const zeroEtm=loadWriter('zero-etm-stocks.js','updateETMStocksWB','main',{
  ETM_TR_WB_WAREHOUSE:798761,WB_RPS:2,lastRequestTime:0,rateLimitRPS:async t=>t,
  sendETMStocksBatch:async p=>{sent.push(p);return {ok:true};},
 });
 await zeroEtm(sourceRows);assert.equal(sent[0].length,1);assert.equal(sent[0][0].chrtId,99);assert.equal(sent[0][0].amount,0);
 const zeroAll=loadWriter('zero-wb-fbs-stocks.js','zeroWarehouse','main',{
  BATCH_SIZE:1000,REQUEST_INTERVAL_MS:0,sleep:async()=>{},sendBatch:async (warehouse,p)=>{sent.push(p);return {ok:true};},
 });
 const ids=new Map(sourceRows.map(r=>[r.chrt_id,new Set([r.offer_id])]));
 // Aliases of a protected chrtId must not reopen ownership through another source.
 ids.get(1).add('OTHER_ALIAS');sent.length=0;
 await zeroAll(798761,ids);assert.equal(sent[0].length,1);assert.equal(sent[0][0].chrtId,99);
 sent.length=0;await zeroAll(1449484,ids);assert.equal(sent[0].length,23,'same offers unchanged on other warehouses');
 console.log('NTC RS/manual zero ownership tests passed');
}
await checkAdditionalWriters();
for (const invalid of [[], [['Артикул продавца','chrlid']], [['Артикул продавца','Артикул продавца','chrlid'],['new','new',1]], [['Артикул продавца','chrlid'],['new','bad']]]) {
 await assert.rejects(refreshNtcCloudWbOwnership({spreadsheets:{values:{get:async()=>({data:{values:invalid}})}}}),/writes blocked/);
 assert.throws(()=>filterLocalWbOwned([{offer_id:'OTHER'}],798761),/not been verified/);
 assert.deepEqual(Array.from(filterLocalWbOwned([{offer_id:'OTHER'}],1449484)),[{offer_id:'OTHER'}]);
}
await refreshNtcCloudWbOwnership(sheets);
await assert.rejects(refreshNtcCloudWbOwnership({spreadsheets:{values:{get:async()=>{throw new Error('read failed');}}}}),/writes blocked/);
assert.throws(()=>isNtcCloudWbOwned(798761,'OTHER'),/not been verified/,'a failed live refresh invalidates the successful previous snapshot');
for (const file of ['sync-etm-stocks.js','sync-feron-stocks.js','sync-rs-stocks.js','zero-etm-stocks.js','zero-wb-fbs-stocks.js']) assert.match(fs.readFileSync(file,'utf8'),/await refreshNtcCloudWbOwnership\(/,file+' refreshes live ownership');
console.log('NTC dynamic ownership/fail-closed tests passed');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
