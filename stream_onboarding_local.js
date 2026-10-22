#!/usr/bin/env node
'use strict';
// Durable preparation of newly observed offers. Historical rows are explicitly
// bootstrapped once; completion is earned only by a publisher's API readback.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');
const {google} = require('googleapis');
google.options({timeout:90000,retry:false});
const {resolveStreamSuppsColumns} = require('./stream_supps_schema');
const ROOT = __dirname;
const BOOK = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
const LOGS = process.env.STREAM_ONBOARDING_LOG_DIR || path.join(ROOT, 'logs');
const STATE = path.join(LOGS, 'stream-onboarding-state.json');
const LOCKS = '/tmp/checksheets_locks';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const text = v => String(v ?? '').trim();
const hash = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
const presentNumber = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const log = message => console.log(`${new Date().toISOString()} ${message}`);
async function retryRead(operation){
  for(let attempt=0;;attempt++){
    try{return await operation();}catch(error){
      const status=Number(error.response?.status||error.code);
      const transient=[408,429,500,502,503,504].includes(status)||/socket hang up|ECONNRESET|ETIMEDOUT|timeout|ECONNABORTED/i.test(error.message||'');
      if(!transient||attempt>=3)throw error;
      log(`Временная ошибка чтения Google; повтор ${attempt+1}/3`);
      await sleep(3000*2**attempt);
    }
  }
}

function atomicJson(file, value) {
  fs.mkdirSync(path.dirname(file), {recursive:true});
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(value, null, 2), {mode:0o600});
  fs.renameSync(tmp, file);
}

function acquireLease(name, lockDirectory = LOCKS) {
  fs.mkdirSync(lockDirectory, {recursive:true});
  const dir = path.join(lockDirectory, `${name}.lock`);
  for (let attempt=0; attempt<2; attempt++) {
    try {
      fs.mkdirSync(dir);
      fs.writeFileSync(path.join(dir, 'pid'), String(process.pid));
      return () => {
        if (fs.existsSync(path.join(dir,'pid')) && fs.readFileSync(path.join(dir,'pid'),'utf8')===String(process.pid)) {
          fs.unlinkSync(path.join(dir,'pid')); fs.rmdirSync(dir);
        }
      };
    } catch (error) {
      if (error.code!=='EEXIST') throw error;
      let pid;
      try { pid=Number(fs.readFileSync(path.join(dir,'pid'),'utf8')); }
      catch (readError) { if (readError.code==='ENOENT') return null; throw readError; }
      if (!Number.isSafeInteger(pid)||pid<=0) return null;
      try { process.kill(pid,0); return null; }
      catch (probe) { if(probe.code!=='ESRCH') throw probe; }
      if(fs.readFileSync(path.join(dir,'pid'),'utf8')!==String(pid)) return null;
      fs.unlinkSync(path.join(dir,'pid')); fs.rmdirSync(dir);
    }
  }
  return null;
}

const SCHEMA = {
  offer:'Артикул продавца', model:'Артикул производителя', brand:'brand', sku:'SKU OZON',
  pack:'Х', chrt:['chrtid','chrlid'], code:'CODES', etmRaw:'ETM SMR', rsRaw:'RS SMR',
  feronRawMsk:'FER MSK', feronRawSmr:'FER SMR', feronRawNsb:'FER NSB', feronRawEkb:'FER EKB',
  etm:'ЭТМ САМАРА', rs:'РЕЗЕРВ', feron_msk:'ПОДОРОЖНИК ФБС', feron_smr:'ФЕРОН ФБС',
  feron_nsb:'НОВОСИБИРСК ФЕРОН', feron_ekb:'ЕКБ Ферон', wb_stock:'WB ВОЛЬТМИР ИТОГ',
  wb_moscow:'ФБС ФЕРОН МОСКВА', rsMoscow:{header:'РУССКИЙ СВЕТ МОСКВА',occurrence:1},
};

async function readIndex(sheets) {
  log('Чтение схемы и списка артикулов StreamSupps');
  const metadata=(await retryRead(()=>sheets.spreadsheets.get({spreadsheetId:BOOK,fields:'sheets.properties'},{timeout:90000,retry:false}))).data;
  const properties=metadata.sheets.find(s=>s.properties.title==='StreamSupps')?.properties;
  if(!properties) throw Error('StreamSupps missing');
  const data=(await retryRead(()=>sheets.spreadsheets.values.batchGet({spreadsheetId:BOOK,
    ranges:["'StreamSupps'!1:1",`'StreamSupps'!A2:A${properties.gridProperties.rowCount}`],
    valueRenderOption:'UNFORMATTED_VALUE'},{timeout:90000,retry:false}))).data.valueRanges;
  const headers=data[0].values?.[0]||[];
  const columns=resolveStreamSuppsColumns(headers,SCHEMA);
  const index=[];
  for(const [i,r] of (data[1].values||[]).entries()) if(text(r[0]))index.push({row:i+2,offer_id:text(r[0])});
  return {headers,columns,index};
}

async function readRecords(sheets, index, targetOffers) {
  const selected=index.index.filter(r=>targetOffers.has(r.offer_id));
  if(!selected.length)return [];
  // Adjacent target rows share one request; unrelated historical data is not read.
  const blocks=[];
  for(const r of selected){
    const last=blocks.at(-1);
    if(last&&r.row<=last.end+1&&r.row-last.start<100)last.end=r.row;
    else blocks.push({start:r.row,end:r.row});
  }
  const values=new Map();
  for(let offset=0;offset<blocks.length;offset+=50){
    const group=blocks.slice(offset,offset+50);
    const result=(await retryRead(()=>sheets.spreadsheets.values.batchGet({spreadsheetId:BOOK,
      ranges:group.flatMap(b=>[`'StreamSupps'!A${b.start}:X${b.end}`,`'StreamSupps'!AB${b.start}:AC${b.end}`]),valueRenderOption:'UNFORMATTED_VALUE'},
      {timeout:90000,retry:false}))).data.valueRanges;
    group.forEach((block,i)=>{
      for(let offset=0;offset<=block.end-block.start;offset++){
        const row=[...(result[i*2].values?.[offset]||[])];
        const pooled=result[i*2+1].values?.[offset]||[];
        row[27]=pooled[0];row[28]=pooled[1];values.set(block.start+offset,row);
      }
    });
  }
  const stamp=new Date().toISOString();
  return selected.map(entry=>{
    const row=values.get(entry.row)||[],record={...entry,snapshotReadAt:stamp};
    if(text(row[index.columns.offer-1])!==entry.offer_id)throw Error('StreamSupps row moved while reading');
    for(const [field,col]of Object.entries(index.columns))record[field]=row[col-1];
    record.offer_id=entry.offer_id;
    return record;
  });
}

function identityFingerprint(record) {
  return hash(['v1',record.offer_id,text(record.model),text(record.brand).toLowerCase(),record.sku,
    record.pack,text(record.code),text(record.chrt),!!record.unitReview]);
}

function identityReasons(record) {
  const errors=[];
  if(!text(record.model))errors.push('missing_model');
  if(!text(record.brand))errors.push('missing_brand');
  if(!presentNumber(record.pack)||record.pack<=0)errors.push('missing_pack');
  if(!/^[1-9]\d*$/.test(text(record.sku)))errors.push('missing_ozon_sku');
  return errors;
}

function sourceReasons(record) {
  const result=identityReasons(record);
  if(record.unitReview)result.push('supplier_unit_review');
  if(record.rsQuarantined)result.push('rs_source_row_quarantined');
  for(const key of ['etmRaw','rsRaw','feronRawMsk','feronRawSmr','feronRawNsb','feronRawEkb','etm','rs','feron_msk','feron_smr','wb_stock','wb_moscow']) {
    if(!presentNumber(record[key]))result.push(`missing_or_invalid:${key}`);
  }
  if(!presentNumber(record.rsMoscow)||record.rsMoscow!==0)result.push('rs_moscow_must_remain_zero');
  return result;
}

function loadState(file, bootstrapThrough) {
  if(fs.existsSync(file)){
    const state=JSON.parse(fs.readFileSync(file,'utf8'));
    if(state.version!==1||!state.offers||typeof state.offers!=='object'||Array.isArray(state.offers))throw Error('Invalid onboarding state; no publication is safe');
    return state;
  }
  if(!Number.isInteger(bootstrapThrough)||bootstrapThrough<1)throw Error('First run requires explicit --bootstrap-existing-through row; refusing to republish historical catalog');
  return {version:1,createdAt:new Date().toISOString(),bootstrapThrough,offers:{}};
}

function discover(state,index) {
  const seedHistorical=!state.bootstrapSeeded&&Object.keys(state.offers).length===0;
  const duplicates=new Set();
  const counts=new Map();for(const r of index.index)counts.set(r.offer_id,(counts.get(r.offer_id)||0)+1);
  for(const row of index.index){
    if(counts.get(row.offer_id)>1)duplicates.add(row.offer_id);
    if(!state.offers[row.offer_id])state.offers[row.offer_id]={baseline:seedHistorical&&row.row<=state.bootstrapThrough,detectedAt:new Date().toISOString()};
  }
  state.bootstrapSeeded=true;
  return {targetOffers:new Set(index.index.filter(r=>!state.offers[r.offer_id].baseline&&!duplicates.has(r.offer_id)).map(r=>r.offer_id)),duplicates};
}

async function runSourceJob(job,args=[]) {
  const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Dubai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()).replaceAll('-','');
  const jobLog=path.join(ROOT,'logs',`${job}_${day}.log`);
  for(let attempt=0;attempt<120;attempt++){
    const requestedAt=Date.now();
    const offset=fs.existsSync(jobLog)?fs.statSync(jobLog).size:0;
    log(`Источник ${job}: запрос запуска${args.length?' '+args.join(' '):''}`);
    const code=await new Promise((resolve,reject)=>{
      const child=spawn(path.join(ROOT,'run_with_lock.sh'),[job,...args],{cwd:ROOT,
        env:{...process.env,CHECKSHEETS_REQUIRE_JOB_RUN:'1',PYTHONUNBUFFERED:'1'},stdio:['ignore','inherit','inherit']});
      child.once('error',reject);child.once('exit',(code,signal)=>signal?reject(Error(`${job}: terminated ${signal}`)):resolve(code));
    });
    if(code===75){if(attempt===119)throw Error(`${job}: source remained busy`);await sleep(15000);continue;}
    if(code!==0)throw Error(`${job}: source failed (${code}); publication postponed`);
    const contents=fs.existsSync(jobLog)?fs.readFileSync(jobLog).subarray(offset).toString('utf8'):'';
    if(!contents.includes(`Starting ${job}`)||!contents.includes(`${job} finished with exit code 0`))throw Error(`${job}: no proof that source actually ran`);
    if(job==='etm_sync'&&(!contents.includes('StreamSupps ETM values written successfully')||contents.includes('values were not written because no records were parsed')))throw Error('ETM: both source files must be parsed and written');
    if(job==='rs_sync'&&!contents.includes('RS SMR and RS MSK updated successfully!'))throw Error('RS: no confirmed source write');
    if(job==='feron_sync'&&!contents.includes('SYNCHRONIZATION COMPLETED')) {
      // Feron prints per-column completion; numeric readiness is checked again
      // after all sources. A successful Python exit without any write is unsafe.
      if(!/Updated|updated|Successfully|successfully|ЗАПИС|обновлен/i.test(contents))throw Error('Feron: no confirmed source write');
    }
    let receipt={};
    if(job==='rs_sync'){
      const file=path.join(ROOT,'logs','rs-source-last.json');
      receipt=JSON.parse(fs.readFileSync(file,'utf8'));
      if(!(Date.parse(receipt.finishedAt)>=requestedAt)||!Array.isArray(receipt.quarantinedModels))throw Error('RS: missing current per-model freshness receipt');
    }
    return {job,finishedAt:new Date().toISOString(),...(job==='rs_sync'?{quarantinedModels:receipt.quarantinedModels}:{} )};
  }
}

async function runPipeline(options={}) {
  const dryRun=!!options.dryRun;
  const deps=options.deps||{};
  const stateFile=options.stateFile||STATE;
  const state=loadState(stateFile,options.bootstrapThrough);
  state.enforcePublicationGate=true;
  const auth=options.sheets?null:new google.auth.GoogleAuth({keyFile:path.join(ROOT,'nomadic-bedrock-485314-b0-d7624dedd83c.json'),scopes:['https://www.googleapis.com/auth/spreadsheets']});
  const sheets=options.sheets||google.sheets({version:'v4',auth});
  const read=deps.readIndex||readIndex, readRows=deps.readRecords||readRecords;
  const records=async (...args)=>(await readRows(...args)).map(r=>({...r,unitReview:!!state.offers[r.offer_id]?.unitReview,rsQuarantined:!!state.offers[r.offer_id]?.rsQuarantined}));
  let index=await read(sheets);
  const {targetOffers,duplicates}=discover(state,index);
  const report={startedAt:new Date().toISOString(),dryRun,targets:targetOffers.size,duplicates:[...duplicates].filter(id=>!state.offers[id].baseline),pending:[],sources:[],publications:[]};
  const save=()=>{if(!dryRun){state.updatedAt=new Date().toISOString();atomicJson(stateFile,state);}};
  save();
  if(!targetOffers.size){report.finishedAt=new Date().toISOString();return report;}
  const enrichTestCatalog=deps.enrichTestCatalog||require('./catalog_test_enrichment_local').enrichTestCatalog;
  report.testCatalog=await enrichTestCatalog(sheets,[...targetOffers],{dryRun,appendMissing:true});
  const prepareWbArticleIds=deps.prepareWbArticleIds||require('./wb_article_ids_local').prepareWbArticleIds;
  report.wbArticleIds=await prepareWbArticleIds(sheets,{dryRun});
  let rows=await records(sheets,index,targetOffers);
  const identityWork=rows.filter(r=>identityReasons(r).length||!state.offers[r.offer_id].catalogCheckedAt);
  let packMap={};
  if(identityWork.length){
    const resolver=deps.resolveCatalog||require('./stream_onboarding_catalog').resolveOnboardingCatalog;
    log(`Подготовка идентичности ${identityWork.length} товаров`);
    const catalog=await resolver(sheets,identityWork.map(r=>r.offer_id),{dryRun});
    packMap=catalog.packMap||{};
    const identities=catalog.identities instanceof Map?[...catalog.identities.values()]:(catalog.identities||[]);
    for(const identity of identities){
      if(!state.offers[identity.offer_id])throw Error('Catalog returned an unexpected offer');
      state.offers[identity.offer_id].catalogCheckedAt=new Date().toISOString();
      state.offers[identity.offer_id].unitReview=!!identity.unitReview;
    }
    report.catalog={identities:identities.length,pending:catalog.pending||[]};
    save();
    index=await read(sheets);rows=await records(sheets,index,targetOffers);
  }
  const prepareOborFormulas=deps.prepareOborFormulas||require('./obor_formulas_local').prepareOborFormulas;
  report.oborFormulas=await prepareOborFormulas(sheets,[...targetOffers],{dryRun});
  const prepareCatalogFormulas=deps.prepareCatalogFormulas||require('./catalog_formulas_local').prepare;
  const catalogFormulas=await prepareCatalogFormulas(sheets,{dryRun,targetOffers});
  report.catalogFormulas={changed:catalogFormulas.changed,sheets:catalogFormulas.sheets,
    pendingInputs:catalogFormulas.pending?.length||0,errors:catalogFormulas.errors||[]};
  const prepare=deps.prepare||require('./stream_onboarding_formulas').prepareStreamSupps;
  // The planner consumes the same unit-review policy as the publisher. A
  // pre-existing TXOZ/F value must not bypass that supplier-unit review.
  const formulaPacks=new Map(packMap instanceof Map?packMap:Object.entries(packMap));
  for(const id of targetOffers)if(state.offers[id].unitReview)formulaPacks.set(id,{unitReview:true});
  const formula=await prepare(sheets,{dryRun,targetOffers,packMap:formulaPacks});
  report.formulas={changed:formula.changed,pending:formula.pending,counts:formula.report?.counts};
  if(dryRun){report.pending=rows.map(r=>({offer_id:r.offer_id,reasons:identityReasons(r)})).filter(r=>r.reasons.length);report.finishedAt=new Date().toISOString();return report;}
  for(const id of formula.offers||[])delete state.offers[id].sourcesFingerprint;
  index=await read(sheets);rows=await records(sheets,index,targetOffers);
  const attempts=rows.filter(r=>!r.unitReview&&!identityReasons(r).length&&!text(r.code));
  const codeKey=hash(['exact-onboarding-v2',attempts.map(r=>[r.offer_id,r.model,r.brand]).sort()]);
  const sourceJob=deps.runSourceJob||runSourceJob;
  if(attempts.length&&(state.codeAttemptKey!==codeKey||Date.now()-Date.parse(state.codeAttemptAt||0)>3600000)){
    const catalog=await (deps.resolveCatalog||require('./stream_onboarding_catalog').resolveOnboardingCatalog)(sheets,attempts.map(r=>r.offer_id),{dryRun:false});
    const identities=catalog.identities instanceof Map?catalog.identities:new Map((catalog.identities||[]).map(r=>[r.offer_id,r]));
    const manifest=path.join(ROOT,'test','runtime',`onboarding-etm-input-${Date.now()}-${process.pid}.json`);
    atomicJson(manifest,attempts.map(r=>({offer_id:r.offer_id,model:r.model,brand:r.brand,title:identities.get(r.offer_id)?.title||''})));
    await sourceJob('sync_etm_codes',['--onboarding-input',manifest]);
    if(!deps.runSourceJob){
      const receipt=JSON.parse(fs.readFileSync(path.join(LOGS,'etm-onboarding-last.json'),'utf8'));
      if(receipt.requested!==attempts.length||!(Date.parse(receipt.finishedAt)>=Date.parse(report.startedAt)))throw Error('ETM: missing current onboarding receipt');
      for(const item of receipt.api?.pending||[])if(item.unitReview&&state.offers[item.offer_id])state.offers[item.offer_id].unitReview=true;
      report.codes={written:receipt.written,pending:receipt.api?.pending||[],finishedAt:receipt.finishedAt};
    }
    state.codeAttemptKey=codeKey;state.codeAttemptAt=new Date().toISOString();save();
    rows=await records(sheets,index,targetOffers);
  }
  let work=rows.filter(r=>!r.unitReview&&!identityReasons(r).length&&
    (state.offers[r.offer_id].ozonFingerprint!==identityFingerprint(r)||
      text(r.chrt)&&state.offers[r.offer_id].wbFingerprint!==identityFingerprint(r)||
      state.offers[r.offer_id].sourcesFingerprint!==identityFingerprint(r)));
  if(work.length){
    const needsRefresh=work.some(r=>state.offers[r.offer_id].sourcesFingerprint!==identityFingerprint(r)||Date.now()-Date.parse(state.offers[r.offer_id].sourcesAt||0)>15*60000);
    if(needsRefresh){
      const beforeSourceKeys=new Map(rows.map(r=>[r.offer_id,identityFingerprint(r)]));
      const sourceStartedAt=Date.now();
      // Independent source columns, but all must finish before any publication.
      const sources=await Promise.allSettled([
        sourceJob('etm_sync',['--force']),sourceJob('rs_sync'),sourceJob('feron_sync'),
      ]);
      report.sources=sources.map((r,i)=>{
        const job=['etm_sync','rs_sync','feron_sync'][i];
        const proven=r.status==='fulfilled'&&r.value&&r.value.job===job&&r.value.success!==false&&Date.parse(r.value.finishedAt)>=sourceStartedAt;
        return {job,...(proven?r.value:{error:r.status==='rejected'?r.reason.message:'missing source completion proof'})};
      });
      if(report.sources.some(r=>r.error)){save();throw Error(report.sources.filter(r=>r.error).map(r=>r.error).join('; '));}
      rows=await records(sheets,index,targetOffers);
      const sourceAt=new Date(Math.min(...report.sources.map(s=>Date.parse(s.finishedAt)))).toISOString();
      if(Date.now()-Date.parse(sourceAt)>15*60000)throw Error('Earliest supplier snapshot is already older than 15 minutes; publication postponed');
      const quarantined=new Set(report.sources.find(s=>s.job==='rs_sync')?.quarantinedModels||[]);
      for(const row of rows){
        const entry=state.offers[row.offer_id];
        entry.rsQuarantined=quarantined.has(text(row.model).toUpperCase());
        row.rsQuarantined=entry.rsQuarantined;
        if(entry.rsQuarantined)delete entry.sourcesFingerprint;
      }
      for(const row of rows.filter(r=>!identityReasons(r).length)){
        const s=state.offers[row.offer_id];
        if(!sourceReasons(row).length&&beforeSourceKeys.get(row.offer_id)===identityFingerprint(row)){s.sourcesFingerprint=identityFingerprint(row);s.sourcesAt=sourceAt;}
      }
      save();
    }
    const publish=deps.publish||require('./stream_onboarding_publish').publishOnboarding;
    for(const marketplace of ['ozon','wb']){
      const fingerprintKey=`${marketplace}Fingerprint`;
      const candidates=rows.filter(r=>!sourceReasons(r).length&&state.offers[r.offer_id].sourcesFingerprint===identityFingerprint(r)&&
        state.offers[r.offer_id][fingerprintKey]!==identityFingerprint(r)&&(marketplace!=='wb'||text(r.chrt)));
      if(!candidates.length)continue;
      const release=(deps.acquireLease||acquireLease)(`marketplace_${marketplace}`);
      if(!release){report.publications.push({marketplace,deferred:'marketplace_busy'});continue;}
      try{
        // Read again under the marketplace lock; never publish a long-lived
        // in-memory snapshot left over from supplier downloads or Ozon writes.
        const freshIndex=await read(sheets);
        const fresh=await records(sheets,freshIndex,new Set(candidates.map(r=>r.offer_id)));
        const stable=fresh.filter(r=>!sourceReasons(r).length&&state.offers[r.offer_id].sourcesFingerprint===identityFingerprint(r)&&Date.now()-Date.parse(state.offers[r.offer_id].sourcesAt||0)<=15*60000);
        const publication=await publish(sheets,stable.map(r=>({...r,chrt_id:r.chrt})),{marketplace});
        report.publications.push(publication);
        const byId=new Map(stable.map(r=>[r.offer_id,r]));
        for(const id of publication.verifiedOfferIds){
          if(!byId.has(id))throw Error('Publisher verified an unexpected offer');
          state.offers[id][fingerprintKey]=identityFingerprint(byId.get(id));
          state.offers[id][`${marketplace}VerifiedAt`]=new Date().toISOString();
        }
        for(const pending of publication.pending||[])state.offers[pending.offer_id].lastPending=pending.reasons;
        save();
      }finally{release();}
    }
  }
  rows=await records(sheets,index,targetOffers);
  for(const row of rows){
    const reasons=sourceReasons(row);
    if(!text(row.code))reasons.push('no_confirmed_etm_code');
    if(!text(row.chrt))reasons.push('no_wb_card');
    for(const m of ['ozon','wb'])if((m!=='wb'||text(row.chrt))&&state.offers[row.offer_id][`${m}Fingerprint`]!==identityFingerprint(row))reasons.push(`${m}_not_yet_verified`);
    state.offers[row.offer_id].lastPending=reasons;
    if(reasons.length)report.pending.push({offer_id:row.offer_id,reasons});
  }
  report.finishedAt=new Date().toISOString();save();
  atomicJson(path.join(path.dirname(stateFile),'stream-onboarding-last.json'),report);
  return report;
}

async function main(){
  const release=acquireLease('stream_onboarding');
  if(!release){log('Другой проход подготовки выполняется; отложено');return;}
  try{
    const report=await runPipeline({dryRun:process.argv.includes('--dry-run'),bootstrapThrough:Number(process.argv.find(a=>a.startsWith('--bootstrap-existing-through='))?.split('=')[1])||undefined});
    log(JSON.stringify({targets:report.targets,formulas:report.formulas?.changed,pending:report.pending.length,publications:report.publications.map(p=>({marketplace:p.marketplace,verified:p.verifiedOfferIds?.length||0,deferred:p.deferred}))}));
    return report;
  }catch(error){
    atomicJson(path.join(LOGS,'stream-onboarding-error.json'),{at:new Date().toISOString(),message:error.message});
    throw error;
  }finally{release();}
}
if(require.main===module)main().catch(async error=>{
  console.error(`Подготовка новых товаров: ${error.message}`);
  const {sendTelegramAlert}=require('./telegram_notifier');
  try{await sendTelegramAlert('Автоподготовка StreamSupps',error.message);}catch{}
  process.exitCode=1;
});
module.exports={runPipeline,readIndex,readRecords,identityFingerprint,identityReasons,sourceReasons,discover,loadState,acquireLease,runSourceJob,atomicJson};
