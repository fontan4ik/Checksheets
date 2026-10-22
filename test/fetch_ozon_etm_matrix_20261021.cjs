const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const ctx = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(root, 'Shared_Настройки.js'), 'utf8') + '\nthis.h = ozonHeaders();', ctx);
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function api(endpoint, payload) {
  for(let attempt=0; attempt<6; attempt++) {
    const r = await fetch('https://api-seller.ozon.ru'+endpoint,{method:'POST',headers:ctx.h,body:JSON.stringify(payload),signal:AbortSignal.timeout(90000)});
    if(r.ok) return r.json();
    if([429,500,502,503,504].includes(r.status) && attempt<5) { await sleep(1000*2**attempt); continue; }
    throw new Error(endpoint+' HTTP '+r.status);
  }
}
async function main() {
  const listed=new Map(); let cursor='', expected=0; const cursors=new Set();
  while(true) {
    const r=(await api('/v3/product/list',{filter:{visibility:'ALL'},last_id:cursor,limit:1000})).result;
    if(!r || !Array.isArray(r.items)) throw new Error('Invalid product list');
    expected=Number(r.total);
    for(const p of r.items) listed.set(String(p.product_id),p);
    console.log('Catalog',listed.size,'/',expected);
    if(!r.items.length || listed.size===expected) break;
    if(!r.last_id || cursors.has(r.last_id)) throw new Error('Catalog pagination stopped before total');
    cursors.add(r.last_id); cursor=r.last_id; await sleep(100);
  }
  if(listed.size!==expected) throw new Error('Catalog total mismatch');
  const rows=[...listed.values()]; const info=new Map(), attrs=new Map();
  for(let i=0;i<rows.length;i+=1000) {
    const r=await api('/v3/product/info/list',{product_id:rows.slice(i,i+1000).map(p=>p.product_id)});
    for(const p of r.items||r.result?.items||[]) info.set(String(p.id||p.product_id),p);
    console.log('Details',info.size); await sleep(100);
  }
  for(let i=0;i<rows.length;i+=100) {
    const batch=rows.slice(i,i+100);
    const r=await api('/v4/product/info/attributes',{filter:{product_id:batch.map(p=>String(p.product_id)),visibility:'ALL'},limit:100});
    if(!Array.isArray(r.result)) throw new Error('Invalid attributes');
    for(const p of r.result) attrs.set(String(p.id||p.product_id),p);
    if(i%1000===0||i+100>=rows.length) console.log('Attributes',attrs.size);
    await sleep(100);
  }
  const output=rows.map(p=>{
    const id=String(p.product_id), d=info.get(id), a=attrs.get(id);
    if(!d || !a) throw new Error('Missing API detail for '+id);
    const brand=a.attributes?.find(v=>Number(v.id)===85)?.values?.map(v=>v.value).filter(Boolean).join(', ')||'';
    return {offer_id:p.offer_id,product_id:id,sku:String(d.sku||''),brand,name:d.name||a.name||'',archived:!!(d.is_archived||p.archived), manufacturer_article:a.attributes?.find(v=>Number(v.id)===9048)?.values?.map(v=>v.value).filter(Boolean).join(', ')||''};
  });
  fs.writeFileSync(path.join(__dirname,'ozon_etm_matrix_api_20261021.json'),JSON.stringify({at:new Date().toISOString(),total:expected,details:info.size,attributes:attrs.size,rows:output}));
  console.log(JSON.stringify({total:expected,brands:[...new Set(output.map(p=>p.brand))],missingBrand:output.filter(p=>!p.brand).length}));
}
module.exports={api};
if(require.main===module) main().catch(e=>{console.error(e.message);process.exitCode=1;});
