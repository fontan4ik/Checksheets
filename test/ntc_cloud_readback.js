const fs=require('fs'),vm=require('vm'),axios=require('axios');
const x=vm.createContext({});vm.runInContext(fs.readFileSync('ntc-cloud/Shared_Credentials.js','utf8')+';this.c=NTC_BOOTSTRAP;',x);
const rows=JSON.parse(fs.readFileSync('test/ntc_cloud_runtime/expected_stocks.json'));
(async()=>{
 const results=await Promise.allSettled([
 axios.post('https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs',{offer_id:rows.map(r=>r.offer_id),limit:1000,cursor:''},{headers:{'Client-Id':x.c.OZON_CLIENT_ID,'Api-Key':x.c.OZON_API_KEY},timeout:30000}),
 axios.post('https://marketplace-api.wildberries.ru/api/v3/stocks/798761',{chrtIds:rows.map(r=>r.chrtId)},{headers:{Authorization:x.c.WB_TOKEN},timeout:30000})]);
 const out={};results.forEach((r,i)=>{const platform=['ozon','wb'][i];if(r.status==='rejected'){out[platform]={http:r.reason.response?.status||r.reason.code};return;}
  const d=r.value.data;const entries=i===0?d.products.filter(p=>String(p.warehouse_id)==='1020005000454993'):d.stocks;
  if(!Array.isArray(entries))throw Error('Unexpected readback '+platform);
  out[platform]={matched:0,total:rows.length,mismatches:[]};rows.forEach(row=>{const p=entries.find(p=>i===0?String(p.offer_id)===row.offer_id:String(p.chrtId)===String(row.chrtId));const actual=i===0?Math.max(0,Number(p?.present)-Number(p?.reserved)):Number(p?.amount);if(actual===row.amount)out[platform].matched++;else out[platform].mismatches.push({offer:row.offer_id,expected:row.amount,actual,present:p?.present,reserved:p?.reserved,totalStock:p?Number(p.present)+Number(p.reserved):null});});
 });fs.writeFileSync('test/ntc_cloud_runtime/readback.json',JSON.stringify(out,null,2));console.log(out);
})().catch(e=>{console.log(e.message);process.exitCode=1});
