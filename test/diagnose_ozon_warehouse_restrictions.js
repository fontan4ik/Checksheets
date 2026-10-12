'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const axios = require('axios');
require('dotenv').config({path:path.join(__dirname,'../.env'),quiet:true});
const source=fs.readFileSync(path.join(__dirname,'../sync-rs-stocks.js'),'utf8');
const start=source.indexOf('function ozonHeaders()');
const end=source.indexOf('\nfunction wbToken()',start);
const context={process,text:value=>String(value??'').trim()};
vm.createContext(context);vm.runInContext(source.slice(start,end),context);
const headers=context.ozonHeaders();
const affected=new Set();
const evidence=[];
for(const filename of fs.readdirSync(path.join(__dirname,'../logs')).filter(name=>/^marketplace_ozon_202610(0[5-9]|1[01])\.log$/.test(name))){
 for(const line of fs.readFileSync(path.join(__dirname,'../logs',filename),'utf8').split('\n')){
  if(!line.includes('OVER_MAX_OVH_NON_KGT'))continue;
  const match=line.match(/(?:не обновил |: )([^ :]+)(?: не обновлён|: \[)/);
  if(match){affected.add(match[1]);evidence.push({filename,line});}
 }
}
(async()=>{
 const output={readAt:new Date().toISOString(),offerIds:[...affected].sort(),evidence};
 for(const [key,endpoint,body] of [['warehouses','/v2/warehouse/list',{}],['products','/v3/product/info/list',{offer_id:[...affected]}],['attributes','/v4/product/info/attributes',{filter:{offer_id:[...affected],visibility:'ALL'},limit:1000}]]){
  try { const result=await axios.post('https://api-seller.ozon.ru'+endpoint,body,{headers,timeout:45000}); output[key]=result.data;console.log(key+': HTTP '+result.status); }
  catch(error){ output[key]={status:error.response?.status||0,message:error.response?.data||error.message};console.log(key+': HTTP '+(error.response?.status||0)); }
 }
 // Persist only operational diagnostic fields, excluding addresses and contacts.
 if(output.warehouses?.warehouses) output.warehouses={warehouses:output.warehouses.warehouses.map(item=>Object.fromEntries(['warehouse_id','name','is_kgt','is_rfbs','status','warehouse_type'].map(key=>[key,item[key]??null])))};
 if(output.products?.items) output.products={items:output.products.items.map(item=>Object.fromEntries(['id','offer_id','name','is_archived','is_autoarchived','errors','statuses'].map(key=>[key,item[key]??null])))};
 if(output.attributes?.result) output.attributes={result:output.attributes.result.map(item=>Object.fromEntries(['offer_id','name','height','width','depth','dimension_unit','weight','weight_unit'].map(key=>[key,item[key]??null])))};
 const dest=path.join(__dirname,'ozon_warehouse_restrictions_20261012.json');
 fs.writeFileSync(dest,JSON.stringify(output,null,2)+'\n');
 console.log('Affected offers: '+affected.size+'; saved '+dest);
})().catch(error=>{console.error(error.message);process.exitCode=1;});
