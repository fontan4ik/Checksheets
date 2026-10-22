const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const store = {};
let triggers = ['updateProductsV2', 'syncOfferIdWithProductId', 'unrelated'].map(name => ({getHandlerFunction:()=>name,getUniqueId:()=>name}));
let created = 0;
const context = {
  Logger:{log(){}},
  LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock(){}})},
  PropertiesService:{getScriptProperties:()=>({getProperty:k=>store[k]||null,setProperty:(k,v)=>store[k]=v})},
  ScriptApp:{getProjectTriggers:()=>triggers,deleteTrigger:t=>triggers=triggers.filter(x=>x!==t),newTrigger:name=>({timeBased(){return this;},everyMinutes(n){assert.equal(n,5);return this;},create(){created++;triggers.push({getHandlerFunction:()=>name,getUniqueId:()=>name});}})},
  SpreadsheetApp:{flush(){}},
  runWithTelegramAlertGAS_:(_name,fn)=>fn(),
  runWithOzonProductSyncLock_:(_name,fn)=>fn(),
  syncOfferIdWithProductIdCore_:()=>({complete:false}),
  updateProductsV2Core_:()=>({complete:false}),
  wbTechDataCatalogSlice_:flag=>{assert.equal(flag,false);return {complete:false};}
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('Flow_Каталоги__Автообновление.js','utf8'),context);
context.writeMarketplaceCatalogStatus_=()=>{};
context.installMarketplaceCatalogTriggersAndRefresh();
assert.equal(created,1);
assert.deepEqual(triggers.map(t=>t.getHandlerFunction()),['unrelated','refreshMarketplaceCatalogs']);
assert.equal(JSON.parse(store.MARKETPLACE_CATALOG_CYCLE_V1).phase,'catalog');
context.syncOfferIdWithProductIdCore_=()=>({complete:true});
assert.equal(context.refreshMarketplaceCatalogs().phase,'details');
assert.equal(context.refreshMarketplaceCatalogs().phase,'details');
context.updateProductsV2Core_=()=>({complete:true});
assert.equal(context.refreshMarketplaceCatalogs().phase,'wb');
assert.equal(context.refreshMarketplaceCatalogs().phase,'wb');
context.wbTechDataCatalogSlice_=flag=>{assert.equal(flag,false);return {complete:true};};
assert.equal(context.refreshMarketplaceCatalogs().phase,'idle');
assert.ok(JSON.parse(store.MARKETPLACE_CATALOG_CYCLE_V1).nextRun-Date.now()>11*60*60*1000);
context.installMarketplaceCatalogTriggersAndRefresh();
assert.equal(created,1);
context.syncOfferIdWithProductIdCore_=()=>{throw Error('HTTP 401');};
store.MARKETPLACE_CATALOG_CYCLE_V1=JSON.stringify({phase:'catalog'});
assert.throws(()=>context.refreshMarketplaceCatalogs(),/HTTP 401/);
assert.equal(JSON.parse(store.MARKETPLACE_CATALOG_CYCLE_V1).phase,'catalog');
console.log('PASS trigger migration, resumable phase ordering, freshness, and error preservation');
store.MARKETPLACE_CATALOG_CYCLE_V1=JSON.stringify({phase:'catalog',lease:'other',leaseUntil:Date.now()+100000});
assert.equal(context.refreshMarketplaceCatalogs().busy,true);
assert.equal(JSON.parse(store.MARKETPLACE_CATALOG_CYCLE_V1).lease,'other');
store.MARKETPLACE_CATALOG_CYCLE_V1=JSON.stringify({phase:'catalog',lease:'expired',leaseUntil:1});
context.syncOfferIdWithProductIdCore_=()=>({complete:true});
context.writeMarketplaceCatalogStatus_=()=>{throw Error('sheet already exists');};
assert.equal(context.refreshMarketplaceCatalogs().phase,'details');
assert.equal(JSON.parse(store.MARKETPLACE_CATALOG_CYCLE_V1).lease,undefined);
console.log('PASS active lease, expired execution recovery, and nonfatal status writes');
