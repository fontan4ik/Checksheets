'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const props = {}, audit = [], calls = [];
let api;
const context = vm.createContext({console, Date, Set, Map,
  PropertiesService: {getScriptProperties: () => ({getProperty: k => props[k], setProperty: (k,v) => {props[k] = v;}})},
  Utilities: {sleep() {}, getUuid: () => 'run', DigestAlgorithm: {SHA_256: 'sha256'}, Charset: {UTF_8:'utf8'}, computeDigest: (_,s) => Array.from(crypto.createHash('sha256').update(s).digest())},
  ntcAudit_: e => audit.push(e),
  UrlFetchApp: {fetch: (url, options) => {calls.push({url,options}); const r = api(url, options); return {getResponseCode: () => r.code || 200, getContentText: () => JSON.stringify(r.body || {}), getHeaders: () => ({})};}},
});
vm.runInContext(fs.readFileSync('ntc-cloud/Shared_Marketplaces.js','utf8'),context);
const cfg = {ozonClientId:'client',ozonApiKey:'secret',wbToken:'secret',ozonWarehouseId:11,wbWarehouseId:22,start:'2026-09-16T00:00:00Z'};
const rows = [{offer_id:'A',ozonSku:1,wbSku:2,chrtId:3,amount:4,row:2},{offer_id:'B',ozonSku:4,wbSku:5,chrtId:6,amount:0,row:3}];
api = () => {throw Error('must not request');};
assert.throws(() => context.ntcPublish_([Object.assign({},rows[0],{chrtId:''})],cfg),/привязка/);
assert.equal(calls.length,0,'whole preflight happens before calls');
let failB = true;
api = url => url.includes('api-seller') ? {body:{result:[{offer_id:'A',updated:true,errors:[]},{offer_id:'B',updated:!failB,errors:failB?[{code:'ERR'}]:[]}]}} : {code:204};
assert.throws(() => context.ntcPublish_(rows,cfg),/не подтверждена/);
assert.equal(props.NTC_MP_ozon_11_A,'4');
assert.equal(props.NTC_MP_ozon_11_B,undefined);
assert.equal(props.NTC_MP_wb_22_3,'4');
assert.equal(audit.filter(e => e.platform==='ozon' && e.event==='result')[0].success,false);
failB = false;
api = url => url.includes('api-seller') ? {body:{result:[{offer_id:'B',updated:true}]}} : {code:204};
const before = calls.length;
context.ntcPublish_(rows,cfg);
assert.equal(calls.length-before,1,'only unsuccessful platform/item retried');
assert.equal(JSON.parse(calls.at(-1).options.payload).stocks[0].offer_id,'B');
assert.equal(calls.at(-1).options.payload.includes('"stock":0'),true,'zero publishes deliberately');
const allConfirmed = calls.length;
context.ntcPublish_(rows,cfg);
assert.equal(calls.length,allConfirmed,'confirmed unchanged values skipped');
assert.throws(() => context.ntcPublish_([Object.assign({},rows[0],{amount:5})],cfg,Date.now()-1),/лимит/);
for (const k of Object.keys(props)) delete props[k];
api = (url, opts) => {
 if(url.includes('api-seller')) return {body:{result:rows.map(r=>({offer_id:r.offer_id,updated:true}))}};
 const stocks=JSON.parse(opts.payload).stocks;
 return stocks.length>1 || stocks[0].chrtId===6 ? {code:409} : {code:204};
};
assert.throws(()=>context.ntcPublish_(rows,cfg),/не подтверждена/);
assert.equal(props.NTC_MP_wb_22_3,'4');
assert.equal(props.NTC_MP_wb_22_6,undefined);
assert(audit.some(e => e.event==='item_result' && e.platform==='wb' && e.chrtId===6 && !e.success));
api = url => {
 if(url.includes('/posting/fbs/list')) return {body:{postings:[
  {posting_number:'old',status:'delivered',in_process_at:'2026-09-01T00:00:00Z',delivery_method:{warehouse_id:11},products:[{offer_id:'A',quantity:1}]},
  {posting_number:'other',status:'delivered',in_process_at:'2026-10-01T00:00:00Z',delivery_method:{warehouse_id:99},products:[{offer_id:'A',quantity:1}]},
  {posting_number:'cancel',status:'cancelled',in_process_at:'2026-10-01T00:00:00Z',delivery_method:{warehouse_id:11},products:[{offer_id:'A',quantity:1}]}
 ],has_next:false}};
 if(url.includes('/orders?')) return {body:{orders:[{id:7,warehouseId:22,article:'A',createdAt:'2026-10-01T00:00:00Z'}],next:0}};
 if(url.includes('/orders/new')) return {body:{orders:[]}};
 if(url.includes('/orders/status')) return {body:{orders:[{id:7,supplierStatus:'cancel',wbStatus:'canceled'}]}};
 throw Error(url);
};
const orders = context.ntcFetchOrders_(rows,{postings:{}},cfg);
assert.equal(orders.length,2);
assert.equal(orders.find(p=>p.posting_number==='cancel').ever_handed_over,true);
assert.equal(orders.find(p=>p.posting_number==='WB:7').ever_handed_over,true,'unknown WB cancellation never invents physical return');
assert.equal(orders.find(p=>p.posting_number==='WB:7').items[0].quantity,1);
api = () => ({body:{returns:[{id:1,schema:'Fbs',visual:{status:{sys_name:'ReceivedBySeller'}}},{id:2,schema:'Fbo',visual:{status:{sys_name:'ReceivedBySeller'}}},{id:3,schema:'Fbs',visual:{status:{sys_name:'OnTheWay'}}}],has_next:false}});
assert.equal(context.ntcFetchReturns_({postings:{cancel:{},'WB:7':{}}},cfg).length,1);
assert.equal(JSON.stringify(audit).includes('secret'),false);
console.log('NTC marketplace tests passed');

api = url => url.includes('/v2/warehouse/list') ? {body:{warehouses:[{warehouse_id:1020005000454993,name:'НТЦ СКЛАД'}]}} : {body:[{id:798761,name:'ВольтМир'}]};
const discovery = context.ntcDiscoverWarehouses_(Object.assign({},cfg,{wbWarehouseId:''}));
assert.equal(discovery.ozon.id,1020005000454993);
assert.equal(discovery.wb,null,'unrelated WB warehouse never chosen');
api = url => url.includes('/v2/warehouse/list') ? {body:{warehouses:[{warehouse_id:1020005000454993,name:'НТЦ СКЛАД'}]}} : {body:[{id:798761,name:'ВольтМир'},{id:22,name:'НТЦ СКЛАД'}]};
assert.equal(context.ntcDiscoverWarehouses_(cfg).wb.id,22);
let pendingQueries = 0;
api = (url,options) => {
 if(url.includes('/posting/fbs/list')) {
  const f = JSON.parse(options.payload).filter;
  if(f.last_changed_status_date) return {body:{postings:[],has_next:false}};
  pendingQueries++;
  return {body:{postings:f.statuses && f.statuses.includes('awaiting_packaging') ? [{posting_number:'partial',status:'awaiting_packaging',in_process_at:'2026-09-15T00:00:00Z',delivery_method:{warehouse_id:11},products:[{offer_id:'A',quantity:2}]}] : [],has_next:false}};
 }
 if(url.includes('/orders?') || url.includes('/orders/new')) return {body:{orders:[],next:0}};
 throw Error(url);
};
const quantityChanges = context.ntcFetchOrders_(rows,{postings:{partial:{items:{A:3},status:'awaiting_packaging'}}},Object.assign({},cfg,{cursor:'2026-10-12T00:00:00Z'}));
assert.equal(pendingQueries,1);
assert.equal(quantityChanges[0].items[0].quantity,2,'pending scan catches quantities changing without status transition');
assert.equal(context.ntcFetchOrders_(rows,{postings:{}},Object.assign({},cfg,{cursor:'2026-10-12T00:00:00Z'}))[0].posting_number,'partial','pending pre-cutoff orders reserved at migration');
console.log('NTC warehouse/pending tests passed');
for (const k of Object.keys(props)) delete props[k];
props.NTC_MP_wb_22_3='unchanged';
api = url => { assert(url.includes('api-seller'),'disabled WB sends no requests'); return {body:{result:[{offer_id:'A',updated:true}]}}; };
const ozonOnly = context.ntcPublish_([{offer_id:'A',ozonSku:1,amount:7,row:2}],Object.assign({},cfg,{wbEnabled:false,wbWarehouseId:''}));
assert.equal(ozonOnly.enabled.join(','),'ozon');
assert.equal(ozonOnly.disabled.join(','),'wb');
assert.equal(props.NTC_MP_wb_22_3,'unchanged','disabled platform cache preserved');
api = url => { assert(url.includes('wildberries'),'disabled Ozon sends no requests'); return {code:204}; };
const wbOnly = context.ntcPublish_([{offer_id:'A',wbSku:2,chrtId:3,amount:8,row:2}],Object.assign({},cfg,{ozonEnabled:false,ozonWarehouseId:''}));
assert.equal(wbOnly.enabled.join(','),'wb');
const toggleCalls=calls.length;
context.ntcPublish_(rows,Object.assign({},cfg,{ozonEnabled:false,wbEnabled:false,ozonWarehouseId:'',wbWarehouseId:''}));
assert.equal(calls.length,toggleCalls,'both disabled sends no requests');
console.log('NTC transmission toggle tests passed');
const catalogHeaders=['Артикул продавца','Артикул производителя','ФОТО','SKU OZON','SKU WB','Остаток склад по моделям','Виртуальный остаток','Х','Округлённое+прогруз на мп','chrlid'];
context.ntcColumn_ = (headers,name) => {const i=headers.indexOf(name); assert(i>=0); return i;};
const sourceRow = (offer,sku,photo) => {const r=Array(22).fill('');r[0]=offer;r[4]=photo;r[21]=sku;return r;};
const sourceGrid=[Array(22).fill(''),sourceRow('A',1,{toString:()=> 'CellImage'}),sourceRow('UNRELATED',10,''),sourceRow('UNRELATED',20,'')];
const formulas=sourceGrid.map(()=>Array(22).fill(''));
formulas[1][4]='=IMAGE("https://cdn.example.org/product.jpg")';
context.SpreadsheetApp={openById:()=>({getSheetByName:name=>name==='ТЕСТ'?{getDataRange:()=>({getValues:()=>sourceGrid,getFormulas:()=>formulas})}:null})};
const photoWrites=[];
const target={getDataRange:()=>({getValues:()=>[catalogHeaders,['A','MODEL','',1,2,100,33,3,33,3]]}),getRange:(row,col)=>({setFormula:value=>photoWrites.push({row,col,value}),setValue:value=>photoWrites.push({row,col,value})})};
api=()=>{throw Error('catalog complete: no API required');};
context.ntcEnrichCatalog_(target,Object.assign({},cfg,{sourceSpreadsheetId:'source'}));
assert.deepEqual(photoWrites,[{row:2,col:3,value:'=IMAGE("https://cdn.example.org/product.jpg")'}],'IMAGE URL extracted from formula and displayed as image; unrelated conflicts ignored');
assert.throws(()=>context.ntcPhotoUrl_('http://cdn.example.org/image.jpg'),/HTTPS/);
formulas[1][4]='=IMAGE("https://cdn.example.org/p""q.jpg")';photoWrites.length=0;
context.ntcEnrichCatalog_(target,Object.assign({},cfg,{sourceSpreadsheetId:'source'}));
assert.equal(photoWrites[0].value,'=IMAGE("https://cdn.example.org/p""q.jpg")','literal quotes escaped inside IMAGE formula');
console.log('NTC IMAGE formula enrichment tests passed');

// Live Ozon v2 returns a nonempty cursor even on the final page.
api = (url) => url.includes('/v2/warehouse/list') ? {body:{warehouses:[{warehouse_id:22,name:'НТЦ СКЛАД'}],has_next:false,cursor:'terminal-token'}} : {body:[{id:798761,name:'ВольтМир'}]};
const finalWarehousePage = context.ntcDiscoverWarehouses_({ozonClientId:'x',ozonApiKey:'x',wbToken:'x',wbWarehouseId:798761});
assert.equal(finalWarehousePage.ozon.id,22);
assert.equal(finalWarehousePage.wb.id,798761);
console.log('NTC live warehouse final cursor regression passed');

let returnCalls=0;api=(url,opts)=>{returnCalls++;assert.equal(JSON.parse(opts.payload).filter.posting_numbers.length,50);return {body:{returns:[],has_next:false}};};
const oldHistory={postings:Object.fromEntries(Array.from({length:100},(_,i)=>['O:'+String(i).padStart(3,'0'),{}]))};
const firstReturnGroup=context.ntcFetchReturns_(oldHistory,Object.assign({},cfg,{returnCursor:0}));assert.equal(firstReturnGroup.nextCursor,1);
const secondReturnGroup=context.ntcFetchReturns_(oldHistory,Object.assign({},cfg,{returnCursor:1}));assert.equal(secondReturnGroup.nextCursor,0);assert.equal(returnCalls,2);
console.log('NTC bounded returns sweep regression passed');

api=(url,options)=>{
 if(url.includes('/posting/fbs/list'))return {body:{postings:[],has_next:false}};
 if(url.includes('/orders/new'))return {body:{orders:[]}};
 if(url.includes('/api/v3/orders?'))return {body:{orders:[],next:123456}};
 throw Error('unexpected '+url);
};
assert.equal(context.ntcFetchOrders_([], {postings:{}},cfg).length,0);
console.log('NTC WB terminal empty cursor regression passed');

const opaque=context.ntcParseApiJson_('{"orders":[],"next":1791915498719814821}');
assert.equal(opaque.next,'1791915498719814821');assert.equal(context.ntcParseApiJson_('{"next":0}').next,0);
console.log('NTC WB int64 cursor precision regression passed');

let historyPages=0;api=(url)=>{
 if(url.includes('/posting/fbs/list'))return {body:{postings:[],has_next:false}};
 if(url.includes('/orders/new'))return {body:{orders:[]}};
 if(url.includes('/api/v3/orders?')){historyPages++;return {body:{orders:[{id:1,warehouseId:22,createdAt:'2026-10-13T12:00:00Z',article:'other'}],next:'1791915498719814821'}};}
 throw Error('unexpected '+url);
};
assert.equal(context.ntcFetchOrders_([], {postings:{}},cfg).length,0);assert.equal(historyPages,1);
console.log('NTC WB short final page cursor regression passed');

// A missing cancellation flag remains conservative even when the preceding
// poll saw awaiting_packaging: physical handover can occur between polls.
vm.runInContext(fs.readFileSync('ntc-cloud/Shared_Engine.js','utf8'),context);
const cancelArticles = [{offer_id:'A', model:'M', H:3}];
const cancelBase = context.ntcAdvance_({articles:cancelArticles,stock_by_model:{M:30}},null).state;
const reserved = context.ntcAdvance_({articles:cancelArticles,stock_by_model:{M:30},postings:[
 {posting_number:'cancel-evidence',status:'awaiting_packaging',items:[{offer_id:'A',quantity:2}]}]},cancelBase).state;
function normalizedCancel(flag, deliveringDate) {
 api = url => {
  if(url.includes('/posting/fbs/list')) {
   const item={posting_number:'cancel-evidence',status:'cancelled',in_process_at:'2026-10-01T00:00:00Z',delivery_method:{warehouse_id:11},products:[{offer_id:'A',quantity:2}]};
   if(flag !== undefined) item.cancellation={cancelled_after_ship:flag};
   if(deliveringDate) item.delivering_date=deliveringDate;
   return {body:{postings:[item],has_next:false}};
  }
  if(url.includes('/orders?') || url.includes('/orders/new')) return {body:{orders:[],next:0}};
  throw Error('cancellation normalization must not add undocumented requests: '+url);
 };
 return context.ntcFetchOrders_(rows,reserved,cfg);
}
function applyCancel(state, updates) {
 return context.ntcAdvance_({articles:cancelArticles,stock_by_model:state.last_f_by_model,postings:updates},state).state;
}
const beforeShipCancellation=normalizedCancel(false);
assert.equal(beforeShipCancellation[0].ever_handed_over,false);
assert.equal(applyCancel(reserved,beforeShipCancellation).last_f_by_model.M,30,'explicit pre-transfer cancellation restores reserved physical pieces');
assert.equal(applyCancel(cancelBase,beforeShipCancellation).last_f_by_model.M,30,'cancellation first observed before transfer never debits stock');
const afterShipCancellation=normalizedCancel(true);
assert.equal(afterShipCancellation[0].ever_handed_over,true);
assert.equal(applyCancel(reserved,afterShipCancellation).last_f_by_model.M,24,'post-transfer cancellation retains debit');
const unknownCancellation=normalizedCancel(undefined);
assert.equal(unknownCancellation[0].ever_handed_over,true);
assert.equal(applyCancel(reserved,unknownCancellation).last_f_by_model.M,24,'awaiting snapshot cannot prove no handover between polls');
assert.equal(applyCancel(cancelBase,unknownCancellation).last_f_by_model.M,24,'unknown first-observed cancellation keeps conservative debit');
assert.equal(normalizedCancel('false')[0].ever_handed_over,true,'string false is not physical evidence');
const shippedState=context.ntcAdvance_({articles:cancelArticles,stock_by_model:reserved.last_f_by_model,postings:[
 {posting_number:'cancel-evidence',status:'delivering',items:[{offer_id:'A',quantity:2}]}]},reserved).state;
assert.equal(applyCancel(shippedState,beforeShipCancellation).last_f_by_model.M,24,'previous confirmed handover is sticky despite contradictory false flag');
const awaitingDeliver=context.ntcAdvance_({articles:cancelArticles,stock_by_model:reserved.last_f_by_model,postings:[
 {posting_number:'cancel-evidence',status:'awaiting_deliver',items:[{offer_id:'A',quantity:2}]}]},reserved).state;
assert.equal(awaitingDeliver.postings['cancel-evidence'].ever_handed_over,false,'awaiting delivery remains before handover');
console.log('NTC Ozon cancellation evidence and sticky handover regressions passed');

const rapidHandedCancel=normalizedCancel(false,"2026-10-01T12:00:00Z");
assert.equal(rapidHandedCancel[0].ever_handed_over,true);
assert.equal(applyCancel(reserved,rapidHandedCancel).last_f_by_model.M,24,"handoff timestamp retains debit when delivery status was missed between polls");
console.log("NTC rapid cancellation with handoff timestamp regression passed");

// Ozon v4 uses a top-level response and opaque cursor; active statuses share one scan.
let ozonPages = 0, ozonFilters = [];
api=(url,options)=>{
 if(url.includes('/posting/fbs/list')) {
  assert(url.endsWith('/v4/posting/fbs/list'));
  const request=JSON.parse(options.payload);assert.equal(request.limit,100);assert.equal(request.sort_dir,'ASC');
  assert.equal(request.offset,undefined);assert.equal(request.filter.warehouse_id,undefined);assert.equal(request.filter.status,undefined);
  assert.deepEqual(request.filter.warehouse_ids,[11]);ozonFilters.push(request.filter);
  ozonPages++;
  if(ozonPages===1) {assert.equal(request.cursor,'');return {body:{postings:[{posting_number:'paged',status:'awaiting_packaging',in_process_at:'2026-10-01T00:00:00Z',delivery_method:{warehouse_id:11},products:[{offer_id:'A',quantity:1}]}],cursor:'opaque-page-2',has_next:true}};}
  if(ozonPages===2) assert.equal(request.cursor,'opaque-page-2');
  return {body:{postings:[],cursor:'terminal',has_next:false}};
 }
 if(url.includes('/orders?') || url.includes('/orders/new')) return {body:{orders:[],next:0}};
 throw Error(url);
};
assert.equal(context.ntcFetchOrders_(rows,{postings:{}},Object.assign({},cfg,{cursor:'2026-10-12T00:00:00Z'})).length,1);
assert.equal(ozonPages,3);assert(ozonFilters[0].last_changed_status_date);assert.equal(ozonFilters[2].statuses.length,5);
for(const failure of ['empty-page','empty-cursor','repeated-cursor']) {
 let calls=0;
 api=()=>{calls++;return {body:{postings:failure==='empty-page'?[]:[{posting_number:'paged',status:'awaiting_packaging',in_process_at:'2026-10-01T00:00:00Z',delivery_method:{warehouse_id:11},products:[{offer_id:'A',quantity:1}]}],cursor:failure==='empty-cursor'?'':'same-token',has_next:true}};};
 assert.throws(()=>context.ntcFetchOrders_(rows,{postings:{}},cfg),/пагинация не продвигается/,failure);
 assert.equal(calls,failure==='repeated-cursor'?2:1);
}
console.log('NTC Ozon v4 request and cursor pagination regressions passed');
