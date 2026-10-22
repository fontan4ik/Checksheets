const {api}=require('../fetch_ozon_etm_matrix_20261021.cjs');
const fs=require('node:fs');
async function main(){
 const file=require('node:path').join(__dirname,'../ozon_etm_matrix_api_20261021.json');
 const snapshot=JSON.parse(fs.readFileSync(file)); const ids=new Set(snapshot.rows.map(p=>p.product_id));
 const archived=new Map(); let cursor='',total=0;
 while(true){
  const r=(await api('/v3/product/list',{filter:{visibility:'ARCHIVED'},last_id:cursor,limit:1000})).result;
  if(!r||!Array.isArray(r.items)) throw new Error('Invalid archived list');
  total=Number(r.total); for(const p of r.items) archived.set(String(p.product_id),p);
  if(archived.size===total||!r.items.length)break;
  if(!r.last_id||r.last_id===cursor)throw new Error('Archive pagination stalled'); cursor=r.last_id;
 }
 if(total!==archived.size)throw new Error('Archive count mismatch');
 const extra=[...archived.values()].filter(p=>!ids.has(String(p.product_id)));
 console.log(JSON.stringify({archived:total,alreadyInAll:total-extra.length,extra:extra.length}));
 for(let i=0;i<extra.length;i+=100){
  const batch=extra.slice(i,i+100);
  const dr=await api('/v3/product/info/list',{product_id:batch.map(p=>p.product_id)});
  const details=new Map((dr.items||dr.result?.items||[]).map(p=>[String(p.id||p.product_id),p]));
  const ar=await api('/v4/product/info/attributes',{filter:{product_id:batch.map(p=>String(p.product_id)),visibility:'ALL'},limit:100});
  const attrs=new Map((ar.result||[]).map(p=>[String(p.id||p.product_id),p]));
  for(const p of batch){
   const id=String(p.product_id),d=details.get(id),a=attrs.get(id); if(!d||!a)throw new Error('Missing archived detail');
   snapshot.rows.push({offer_id:p.offer_id,product_id:id,sku:String(d.sku||''),brand:a.attributes?.find(v=>Number(v.id)===85)?.values?.map(v=>v.value).filter(Boolean).join(', ')||'',name:d.name||a.name||'',archived:true,manufacturer_article:a.attributes?.find(v=>Number(v.id)===9048)?.values?.map(v=>v.value).filter(Boolean).join(', ')||''});
  }
 }
 snapshot.visibility_all_total=snapshot.total;snapshot.archived_total=total;snapshot.archived_extra=extra.length;snapshot.total=snapshot.rows.length;
 fs.writeFileSync(file,JSON.stringify(snapshot)); console.log('Final total',snapshot.total);
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
