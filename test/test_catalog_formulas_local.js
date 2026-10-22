const test=require('node:test'),assert=require('node:assert/strict');
const{planCatalogFormulas,DEFINITIONS}=require('../catalog_formulas_local');
const col=s=>[...s].reduce((n,c)=>n*26+c.charCodeAt(0)-64,0);
function fixture(sheetName='ТЗ'){
 const def=DEFINITIONS[sheetName],headers=[],formulas=[],keys=[];
 headers[0]='Артикул';for(const[c,h]of Object.entries(def.references))headers[col(c)-1]=h;
 for(const[c,f]of Object.entries(def.fields)){headers[col(c)-1]=f.header??'';(formulas[1]??=[])[col(c)-1]=f.formula??f.value;}
 if(sheetName==='UNIT API'){headers[16]=headers[40]='Цена продажи';headers[26]='';for(let i=1;i<def.minimumRow-1;i++)(formulas[i]??=[])[42]=0.5219;}
 keys[0]=['Артикул'];keys[10]=['NEW-1'];keys[def.minimumRow-1]=['NEW-1'];
 (formulas[10]??=[])[0]='NEW-1';formulas[def.minimumRow-1]=['NEW-1'];
 return{sheetName,headers,formulas,keys,targetOffers:new Set(['NEW-1'])};
}
test('only managed offers after documented migration boundaries receive formulas',()=>{
 const d=fixture(),p=planCatalogFormulas(d);assert.equal(p.changed,8);assert.ok(p.changes.every(c=>c.row===22546));
 assert.ok(p.changes.some(c=>c.column==='BO'));assert.ok(p.changes.every(c=>c.values[0][0].startsWith('=IF')));
 assert.equal(p.changes.find(c=>c.column==='W').values[0][0],'=IFNA(VLOOKUP(I22546;\'ОБОР\'!A:BF;38;0);"Нет в ОБОР")');
});
test('preserves existing manual values and formulas and is idempotent',()=>{
 const d=fixture(),r=22545;d.formulas[r][col('Y')-1]=0;d.formulas[r][col('AH')-1]='=CUSTOM()';
 const p=planCatalogFormulas(d);assert.equal(p.changed,6);
 for(const c of p.changes)d.formulas[c.row-1][col(c.column)-1]=c.values[0][0];assert.equal(planCatalogFormulas(d).changed,0);
});
test('UNIT financial assumptions stay blank and pending',()=>{
 const p=planCatalogFormulas(fixture('UNIT API'));assert.equal(p.changed,12);assert.equal(p.pending.length,3);
 assert.ok(p.pending.every(x=>['AA','AO','AR'].includes(x.field)));
});
test('missing canonical template fails closed',()=>{
 const d=fixture();d.formulas[1][col('BB')-1]='=OTHER()';assert.throws(()=>planCatalogFormulas(d),/verified canonical/);
});
test('moved and duplicate visible headers and unnamed service changes fail closed',()=>{
 let d=fixture();d.headers.push('ФБС+ФБО');assert.throws(()=>planCatalogFormulas(d),/дублируется/);
 d=fixture();[d.headers[col('BB')-1],d.headers[col('Y')-1]]=[d.headers[col('Y')-1],d.headers[col('BB')-1]];assert.throws(()=>planCatalogFormulas(d),/moved/);
 d=fixture();d.headers[col('BO')-1]='new';assert.throws(()=>planCatalogFormulas(d),/blank BO/);
 d=fixture('UNIT API');d.headers[26]='changed';assert.throws(()=>planCatalogFormulas(d),/service layout/);
});
test('untracked offers and absent catalog keys are skipped',()=>{
 const d=fixture();d.targetOffers=new Set(['OTHER-1']);assert.equal(planCatalogFormulas(d).changed,0);
 assert.throws(()=>planCatalogFormulas({...d,targetOffers:undefined}),/Explicit targetOffers/);
});
test('new UNIT financial formulas require explicitly numeric manual assumptions',()=>{
 const p=planCatalogFormulas(fixture('UNIT API'));
 for(const [column,inputs]of Object.entries({Z:['AA'],AC:['AA'],AE:['AA'],AG:['AA'],AM:['AA'],AL:['AA','AO'],AP:['AA','AO'],AN:['AA','AR']})){
  const f=p.changes.find(c=>c.column===column).values[0][0];
  assert.ok(f.startsWith('=IF(OR('),column);
  for(const input of inputs)assert.ok(f.includes(`NOT(ISNUMBER(${input}23795))`),`${column}:${input}`);
 }
});
test('existing raw AG, custom formulas and historical blanks are never upgraded',()=>{
 const d=fixture('UNIT API');d.keys[10]=['NEW-1'];d.formulas[10][32]='=(AC11/AD11)-1*100%';
 d.keys[11]=['NEW-1'];d.formulas[11][32]='=CUSTOM(AC12/AD12)';
 d.keys[12]=['NEW-1'];d.formulas[12][32]='=(AC12/AD13)-1*100%';
 d.keys[13]=['NEW-1'];d.formulas[13][32]='';
 d.formulas[23794][32]='=(AC23795/AD23795)-1*100%';
 const p=planCatalogFormulas(d);
 assert.equal(p.changes.some(c=>c.column==='AG'),false);
 assert.ok(p.changes.every(c=>c.row>=23795));
});
function fakeSheets(datasets){
 let writes=0,loseReply=false;
 const sheets={spreadsheets:{values:{batchGet:async request=>({data:{valueRanges:request.ranges.map(range=>{
  const[,name,address]=range.match(/^'([^']+)'!(.*)$/),d=datasets[name];
  if(address==='1:1')return{range,values:[d.headers]};
  if(address==='A:A')return{range,values:d.keys};
  const[,a,start,b,end]=address.match(/^([A-Z]+)(\d+):([A-Z]+)(\d+)$/);
  return{range,values:Array.from({length:Number(end)-Number(start)+1},(_,i)=>(d.formulas[Number(start)-1+i]||[]).slice(col(a)-1,col(b)))};
 })}}),batchUpdate:async request=>{
  writes++;for(const c of request.requestBody.data){const[,name,column,row]=c.range.match(/^'([^']+)'!([A-Z]+)(\d+)$/);(datasets[name].formulas[Number(row)-1]??=[])[col(column)-1]=c.values[0][0];}
  if(loseReply){loseReply=false;throw new Error('acknowledged write with lost reply');}return{data:{}};
 }}}};
 return{sheets,get writes(){return writes;},loseNextReply(){loseReply=true;}};
}
function appendFixtureRow(d,offer){d.keys.push([offer]);d.formulas[d.keys.length-1]=[offer];return d.keys.length;}
test('append ledger protects baseline rows and later user deletions; only future rows initialize',async()=>{
 const fs=require('node:fs'),path=require('node:path'),{prepare}=require('../catalog_formulas_local');
 const parent=path.join(__dirname,'runtime');fs.mkdirSync(parent,{recursive:true});const dir=fs.mkdtempSync(path.join(parent,'catalog-append-test-'));
 const datasets=Object.fromEntries(['UNIT API','ТЗ'].map(name=>{const d=fixture(name);d.keys=Array.from({length:d.keys.length},(_,i)=>d.keys[i]||[]);return[name,d];}));
 const fake=fakeSheets(datasets),options={targetOffers:new Set(['NEW-1']),ledgerStateFile:path.join(dir,'ledger.json'),backupDir:dir,readMinGapMs:0,readRetryDelayMs:0};
 try{
  assert.equal((await prepare(fake.sheets,options)).changed,0);assert.equal(fake.writes,0);
  const ur=appendFixtureRow(datasets['UNIT API'],'NEW-2'),tr=appendFixtureRow(datasets['ТЗ'],'NEW-2');
  datasets['UNIT API'].formulas[ur-1][col('W')-1]='manual override';options.targetOffers.add('NEW-2');
  const first=await prepare(fake.sheets,options);assert.equal(first.changed,19);assert.equal(fake.writes,2);
  datasets['UNIT API'].formulas[ur-1][col('AG')-1]='';datasets['UNIT API'].formulas[ur-1][col('W')-1]='';datasets['ТЗ'].formulas[tr-1][col('Y')-1]='';
  const repeat=await prepare(fake.sheets,options);assert.equal(repeat.changed,0);assert.equal(fake.writes,2);
  assert.equal(datasets['UNIT API'].formulas[ur-1][col('AG')-1],'');assert.equal(datasets['UNIT API'].formulas[ur-1][col('W')-1],'');assert.equal(datasets['ТЗ'].formulas[tr-1][col('Y')-1],'');
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
test('lost reply never resends issued cells; unattempted sheet initialization can continue',async()=>{
 const fs=require('node:fs'),path=require('node:path'),{prepare}=require('../catalog_formulas_local');
 const parent=path.join(__dirname,'runtime');fs.mkdirSync(parent,{recursive:true});const dir=fs.mkdtempSync(path.join(parent,'catalog-retry-test-'));
 const datasets=Object.fromEntries(['UNIT API','ТЗ'].map(name=>{const d=fixture(name);d.keys=Array.from({length:d.keys.length},(_,i)=>d.keys[i]||[]);return[name,d];}));
 const fake=fakeSheets(datasets),options={targetOffers:new Set(['NEW-1']),ledgerStateFile:path.join(dir,'ledger.json'),backupDir:dir,readMinGapMs:0,readRetryDelayMs:0};
 try{
  await prepare(fake.sheets,options);
  const row=appendFixtureRow(datasets['UNIT API'],'NEW-3');appendFixtureRow(datasets['ТЗ'],'NEW-3');options.targetOffers.add('NEW-3');fake.loseNextReply();
  await assert.rejects(prepare(fake.sheets,options),/lost reply/);assert.equal(fake.writes,1);
  datasets['UNIT API'].formulas[row-1][col('AG')-1]='';
  const retry=await prepare(fake.sheets,options);assert.equal(retry.changed,8);assert.equal(fake.writes,2);
  assert.equal(datasets['UNIT API'].formulas[row-1][col('AG')-1],'');
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
test('protected baseline custom AQ needs no canonical validation; future AQ stays pending',async()=>{
 const fs=require('node:fs'),path=require('node:path'),{prepare}=require('../catalog_formulas_local');
 const parent=path.join(__dirname,'runtime');fs.mkdirSync(parent,{recursive:true});const dir=fs.mkdtempSync(path.join(parent,'catalog-custom-aq-test-'));
 const datasets=Object.fromEntries(['UNIT API','ТЗ'].map(name=>{const d=fixture(name);d.keys=Array.from({length:d.keys.length},(_,i)=>d.keys[i]||[]);return[name,d];}));
 datasets['UNIT API'].formulas[2][col('AQ')-1]=0.6;
 const fake=fakeSheets(datasets),options={targetOffers:new Set(['NEW-1']),ledgerStateFile:path.join(dir,'ledger.json'),backupDir:dir,readMinGapMs:0,readRetryDelayMs:0};
 try{
  assert.equal((await prepare(fake.sheets,options)).changed,0);assert.equal(fake.writes,0);
  assert.equal((await prepare(fake.sheets,{...options,dryRun:true})).changed,0);
  const row=appendFixtureRow(datasets['UNIT API'],'NEW-AQ');options.targetOffers.add('NEW-AQ');
  const result=await prepare(fake.sheets,options);assert.equal(result.changed,11);
  assert.ok(result.pending.some(p=>p.field==='AQ'&&p.reason.includes('authoritative')));
  assert.equal(datasets['UNIT API'].formulas[row-1][col('AQ')-1],undefined);
  assert.equal(datasets['UNIT API'].formulas[2][col('AQ')-1],0.6);
  for(const column of ['AE','AL','AM','AN'])assert.ok(datasets['UNIT API'].formulas[row-1][col(column)-1].includes(`NOT(ISNUMBER(AQ${row}))`));
  assert.equal((await prepare(fake.sheets,options)).changed,0);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
