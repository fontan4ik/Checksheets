const test = require('node:test');
const assert = require('node:assert/strict');
const { planStreamSupps, prepareStreamSupps, relocateFormula, SCHEMA } = require('../stream_onboarding_formulas');
const headers = ['', 'Артикул производителя', 'PIC', 'brand', 'SKU OZON', 'Х', 'chrlid', 'СМР САМ', 'FER MSK', 'FER SMR', 'FER NSB', 'FER EKB', 'ПОДОРОЖНИК ФБС', 'ФЕРОН ФБС', 'НОВОСИБИРСК ФЕРОН', 'ЕКБ Ферон', 'ETM SMR', 'ETM MSK', 'ЭТМ САМАРА', 'CODES', 'RS SMR', 'РЕЗЕРВ', 'RS MSK', 'РУССКИЙ СВЕТ МОСКВА', 'ПРОДАЖ', 'ДИЗАЙН', 'АРЛАЙТ МСК', 'WB ВОЛЬТМИР ИТОГ', 'ФБС ФЕРОН МОСКВА', 'Цена продажи', 'СУММА ВСЕХ ПОСТАВЩИКОВ'];
function testDirectory(t) {
  const fs=require('node:fs'),path=require('node:path');
  const parent=path.join(__dirname,'runtime');fs.mkdirSync(parent,{recursive:true});
  const dir=fs.mkdtempSync(path.join(parent,'append-formulas-'));
  t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  return dir;
}
function ledgerFor(dir, d, seed = true) {
  const stateFile=require('node:path').join(dir,'ledger','state.json');
  if(seed)require('../append_initialization_ledger').claimAppendInitializations({scope:'stream-formulas',sheetName:'StreamSupps',
    keys:d.values.slice(0,2).map(row=>[row[0]]),changes:[],observedCells:[],stateFile});
  return stateFile;
}
function fixture() {
  const existing = ['MODEL-1','MODEL','','IEK',123,1];
  existing[12] = 0; existing[30] = 4;
  const newcomer = ['MODEL-5','MODEL','','IEK',456];
  const values = [headers, existing, newcomer];
  const formulas = [headers.slice(), existing.slice(), newcomer.slice()];
  formulas[1][12] = '=ROUND(I2/F2/1,5;0)';
  formulas[1][30] = '=I2+J2+K2+L2';
  return {values, formulas, txoz:[['Артикул','№','Кратность нтц'], ['MODEL-5',1,5]], targetOffers:['MODEL-5']};
}
test('requires explicit tracked offer scope and preserves historical blanks', () => {
  const d = fixture(); assert.throws(() => planStreamSupps({...d, targetOffers:undefined}), /targetOffers/);
  const p = planStreamSupps(d); assert.ok(p.changes.length); assert.ok(p.changes.every(c => c.row === 3));
  assert.ok(p.changes.every(c => !['A','B','C','D','E','G','Y','Z','AA','O','P'].includes(c.range.match(/!([A-Z]+)/)[1])));
});
test('pack uses unique exact TXOZ mapping, never numeric suffix fallback', () => {
  const d = fixture(); d.txoz[1][2] = 2;
  let p = planStreamSupps(d); assert.ok(p.changes.find(c=>c.field==='pack').values[0][0].includes('VLOOKUP'));
  d.txoz.pop(); p = planStreamSupps(d);
  assert.equal(p.changes.some(c=>c.field==='pack'),false); assert.equal(p.changes.some(c=>c.field==='etm'),false);
  assert.ok(p.pending.some(c=>c.reason.includes('exact TXOZ')));
});
test('duplicate TXOZ pack mapping fails closed', () => {
  const d = fixture(); d.txoz.push(['MODEL-5',2,5]);
  const p = planStreamSupps(d); assert.ok(p.pending.some(c=>c.reason.includes('duplicate')));
  assert.equal(p.changes.some(c=>c.field==='pack'),false);
});
test('preserves manual values, zero, formulas and Moscow disabled', () => {
  const d = fixture(); d.values[2][18] = 0; d.formulas[2][18]=0;
  d.values[2][21] = 7; d.formulas[2][21]='=CUSTOM(U3)';
  const p = planStreamSupps(d);
  assert.equal(p.changes.some(c=>['etm','rs'].includes(c.field)),false);
  assert.equal(p.changes.find(c=>c.field==='rsMoscow').values[0][0],0);
});
test('special cable converts ETM meters while RS uses pre-normalized coils', () => {
  const d = fixture(); d.values[2][1]='LC1-C5E04-311';
  const p=planStreamSupps(d);
  assert.match(p.changes.find(c=>c.field==='etm').values[0][0],/TRUNC\(Q3\/305\)/);
  assert.doesNotMatch(p.changes.find(c=>c.field==='rs').values[0][0],/305/);
});
test('missing numeric sources stay pending; formulas guard blank stocks and incomplete sums', () => {
  const p=planStreamSupps(fixture());
  assert.ok(p.pending.some(c=>c.field==='etmSource'));
  assert.match(p.changes.find(c=>c.field==='etm').values[0][0],/ISNUMBER\(Q3\)/);
  assert.match(p.changes.find(c=>c.field==='wbSamara').values[0][0],/COUNT\(N3;S3;V3\)<>3/);
});
test('does not borrow other brand formulas', () => {
  const d=fixture();d.values[2][3]='UNKNOWN';
  const p=planStreamSupps(d);assert.equal(p.changes.some(c=>c.field==='moscow'),false);
  assert.ok(p.pending.some(c=>c.field==='moscow'));
});
test('missing-only plan is idempotent after user-entered cells exist', () => {
  const d=fixture(),p=planStreamSupps(d);
  for (const c of p.changes) { const col=Object.keys(SCHEMA).indexOf(c.field); void col;
    const letters=c.range.match(/!([A-Z]+)/)[1]; let n=0;for (const x of letters)n=n*26+x.charCodeAt(0)-64;
    d.formulas[c.row-1][n-1]=c.values[0][0]; d.values[c.row-1][n-1]=c.field==='pack'?5:c.values[0][0]; }
  assert.equal(planStreamSupps(d).changed,0);
});
test('duplicate or moved headers are rejected', () => {
  const d=fixture();d.values[0]=[...headers];d.values[0][31]='Х';assert.throws(()=>planStreamSupps(d),/дублируется/);
  d.values[0]=[...headers];[d.values[0][12],d.values[0][13]]=[d.values[0][13],d.values[0][12]];assert.throws(()=>planStreamSupps(d),/moved/);
});
test('row relocation retains constants and absolute references', () => {
  assert.equal(relocateFormula('=TRUNC(Q2/305)+$A$2+F2+$A2',2,99),'=TRUNC(Q99/305)+$A$2+F99+$A99');
});
test('prepare dry-run reads bounded ranges and never writes',async t=>{
  const d=fixture(); const sheets=mockSheets(d);
  sheets.spreadsheets.values.batchUpdate=()=>assert.fail('dry-run writes');
  const result=await prepareStreamSupps(sheets,{dryRun:true,targetOffers:['MODEL-5'],ledgerStateFile:ledgerFor(testDirectory(t),d)});
  assert.ok(result.changed);assert.deepEqual(result.headers,headers);assert.ok(result.snapshot);
});
test('authoritative exact packMap fills missing TXOZ without overwriting pack or ambiguous TXOZ',()=>{
  const d=fixture(); d.txoz.pop(); d.packMap=new Map([['MODEL-5',{pack:10,source:'verified API'}]]);
  assert.equal(planStreamSupps(d).changes.find(c=>c.field==='pack').values[0][0],10);
  d.values[2][5]=3; d.formulas[2][5]=3;
  assert.equal(planStreamSupps(d).changes.some(c=>c.field==='pack'),false);
  delete d.values[2][5];delete d.formulas[2][5];
  d.txoz.push(['MODEL-5',1,5],['MODEL-5',2,5]);
  assert.equal(planStreamSupps(d).changes.some(c=>c.field==='pack'),false);
});
function mockSheets(d, race = false, badReadback = false) {
  let written=false;
  return {spreadsheets:{values:{
    batchGet:async req=>{
      if(req.ranges[0]==="'StreamSupps'!1:1")return{data:{valueRanges:[{values:[headers]},{values:d.values.map(r=>[r[0]])},{values:d.txoz.map(r=>[r[0]])}]}};
      if(req.ranges[0].startsWith("'StreamSupps'!A1:AE"))return{data:{valueRanges:req.valueRenderOption==='FORMULA'?[{values:d.formulas},{values:d.txoz}]:[{values:d.values},{values:d.txoz}]}};
      return {data:{valueRanges:req.ranges.map((range,i)=>{
        const match=range.match(/!([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$/);
        const [,l,r,endL,endR]=match;
        const col=x=>{let n=0;for(const a of x)n=n*26+a.charCodeAt(0)-64;return n;};
        const source=req.valueRenderOption==='FORMULA'?d.formulas:d.values;
        const rows=[];
        for(let row=Number(r);row<=Number(endR||r);row++){
          const cells=[];for(let c=col(l);c<=col(endL||l);c++)cells.push(source[row-1]?.[c-1]??'');rows.push(cells);
        }
        if(!endL && race && !written && i===0)rows[0][0]='manual concurrent override';
        if(!endL && badReadback && written)rows[0][0]='wrong';
        return{range,values:rows};
      })}};
    },
    batchUpdate:async req=>{written=true;for(const change of req.requestBody.data){const[,l,r]=change.range.match(/!([A-Z]+)(\d+)$/);let c=0;for(const a of l)c=c*26+a.charCodeAt(0)-64;d.formulas[Number(r)-1][c-1]=change.values[0][0];}return{data:{}};},
  }}};
}
test('mutations back up originals and verify exact formula readback',async()=>{
  const fs=require('node:fs'),path=require('node:path');const parent=path.join(__dirname,'runtime');fs.mkdirSync(parent,{recursive:true});const dir=fs.mkdtempSync(path.join(parent,'formula-test-'));
  try {const d=fixture(),result=await prepareStreamSupps(mockSheets(d),{targetOffers:['MODEL-5'],backupDir:dir,ledgerStateFile:ledgerFor(dir,d)});assert.ok(result.changed);const backups=fs.readdirSync(dir).filter(n=>n.startsWith('stream-formulas-before-'));assert.equal(backups.length,1);const backup=JSON.parse(fs.readFileSync(path.join(dir,backups[0])));assert.equal(backup.values[2][5],'');assert.ok(backup.changes.length);} finally{fs.rmSync(dir,{recursive:true,force:true});}
});
test('concurrent user edit aborts before mutation',async()=>{
  const fs=require('node:fs'),path=require('node:path');const parent=path.join(__dirname,'runtime');fs.mkdirSync(parent,{recursive:true});const dir=fs.mkdtempSync(path.join(parent,'formula-race-test-'));
  try {const d=fixture();await assert.rejects(prepareStreamSupps(mockSheets(d,true),{targetOffers:['MODEL-5'],backupDir:dir,ledgerStateFile:ledgerFor(dir,d)}),/concurrent edit/);assert.equal(d.formulas[2][5],undefined);} finally{fs.rmSync(dir,{recursive:true,force:true});}
});
test('mismatched post-write readback is a terminal error',async()=>{
  const fs=require('node:fs'),path=require('node:path');const parent=path.join(__dirname,'runtime');fs.mkdirSync(parent,{recursive:true});const dir=fs.mkdtempSync(path.join(parent,'formula-verify-test-'));
  try {const d=fixture();await assert.rejects(prepareStreamSupps(mockSheets(d,false,true),{targetOffers:['MODEL-5'],backupDir:dir,ledgerStateFile:ledgerFor(dir,d)}),/read-back mismatch/);} finally{fs.rmSync(dir,{recursive:true,force:true});}
});
test('new manufacturer brands use verified common allocation rule and diagnostic total fallback',()=>{
  const d=fixture();
  const canonical='=LET(base;REGEXREPLACE($A2;"-[0-9]+$";"");arl_tr;IFERROR(VLOOKUP(A2;\'ARL TR\'!$A:$I;9;0);0);TRUNC(I2/F2/1,5)+IF(LOWER(TRIM(D2))="arlight";arl_tr;0))';
  for(let i=0;i<5;i++){
    const r=['OLD'+i+'-1','OLD'+i,'','Feron',123,1];d.values.push(r);d.formulas.push(r.slice());d.formulas.at(-1)[12]=relocateFormula(canonical,2,d.values.length);
  }
  d.values[2][3]='DEKraft';
  const p=planStreamSupps(d),m=p.changes.find(c=>c.field==='moscow');
  assert.ok(m);assert.match(m.values[0][0],/"arlight"/);assert.match(m.values[0][0],/ISNUMBER\(I3\)/);
  assert.ok(p.changes.find(c=>c.field==='total'));assert.equal(p.pending.some(c=>c.field==='moscow'),false);
});
test('explicit unitReview prevents stock formulas and pack guesses even with positive supplied pack',()=>{
  const d=fixture();d.txoz.pop();d.packMap={'MODEL-5':{pack:1,unitReview:true}};
  const p=planStreamSupps(d);assert.ok(p.pending.some(c=>c.reason.includes('unit review')));
  assert.ok(p.changes.every(c=>c.field==='rsMoscow'));
});
test('snapshot excludes unrelated effective spills and retries transient reads only',async t=>{
  const d=fixture(),sheets=mockSheets(d),get=sheets.spreadsheets.values.batchGet;
  const reads=[];let first=true;
  sheets.spreadsheets.values.batchGet=async req=>{
    reads.push(req);
    if(first){first=false;const e=new Error('socket hang up');e.code='ECONNRESET';throw e;}
    return get(req);
  };
  await prepareStreamSupps(sheets,{targetOffers:['MODEL-5'],dryRun:true,readRetryDelayMs:0,ledgerStateFile:ledgerFor(testDirectory(t),d)});
  assert.equal(reads.filter(x=>x.ranges[0]==="'StreamSupps'!1:1").length,2);
  assert.ok(reads.some(x=>x.valueRenderOption==='FORMULA'&&x.ranges[0]==="'StreamSupps'!A1:AE3"));
  assert.ok(reads.filter(x=>x.valueRenderOption==='UNFORMATTED_VALUE').every(x=>x.ranges.every(r=>!r.includes('A1:AE')&&!/![YZ]/.test(r))));
  assert.ok(reads.some(x=>x.ranges.includes("'StreamSupps'!A3:X3")));
});
test('first observation protects every existing row including historical deleted cells',async t=>{
  const d=fixture(),dir=testDirectory(t),ledgerStateFile=ledgerFor(dir,d,false);
  const sheets=mockSheets(d);sheets.spreadsheets.values.batchUpdate=()=>assert.fail('baseline must not write');
  const result=await prepareStreamSupps(sheets,{targetOffers:['MODEL-1','MODEL-5'],backupDir:dir,ledgerStateFile});
  assert.equal(result.changed,0);assert.equal(d.formulas[2][5],undefined);
  const again=await prepareStreamSupps(sheets,{targetOffers:['MODEL-5'],backupDir:dir,ledgerStateFile});
  assert.equal(again.changed,0);
});
test('appended rows initialize once; manually erased initialized formulas stay erased',async t=>{
  const d=fixture(),dir=testDirectory(t),ledgerStateFile=ledgerFor(dir,d),sheets=mockSheets(d);
  const first=await prepareStreamSupps(sheets,{targetOffers:['MODEL-1','MODEL-5'],backupDir:dir,ledgerStateFile});
  assert.ok(first.changed);assert.ok(first.changes.every(c=>c.row===3));
  d.formulas[2][18]='';d.values[2][18]='';
  const second=await prepareStreamSupps(sheets,{targetOffers:['MODEL-5'],backupDir:dir,ledgerStateFile});
  assert.equal(second.changes.some(c=>c.field==='etm'),false);
  assert.equal(d.formulas[2][18],'');
});
test('duplicate appended offers do not receive formulas',async t=>{
  const d=fixture(),dir=testDirectory(t),ledgerStateFile=ledgerFor(dir,d);
  d.values.push([...d.values[2]]);d.formulas.push([...d.formulas[2]]);
  const sheets=mockSheets(d);sheets.spreadsheets.values.batchUpdate=()=>assert.fail('duplicate offer must not write');
  const result=await prepareStreamSupps(sheets,{targetOffers:['MODEL-5'],backupDir:dir,ledgerStateFile});
  assert.equal(result.changed,0);
});
test('a manual value observed in an appended row remains protected after deletion',async t=>{
  const d=fixture(),dir=testDirectory(t),ledgerStateFile=ledgerFor(dir,d),sheets=mockSheets(d);
  d.values[2][18]=17;d.formulas[2][18]=17;
  await prepareStreamSupps(sheets,{targetOffers:['MODEL-5'],backupDir:dir,ledgerStateFile});
  d.formulas[2][18]='';d.values[2][18]='';
  const result=await prepareStreamSupps(sheets,{targetOffers:['MODEL-5'],backupDir:dir,ledgerStateFile});
  assert.equal(result.changes.some(c=>c.field==='etm'),false);assert.equal(d.formulas[2][18],'');
});
test('ambiguous remote failure consumes the write claim and never automatically retries',async t=>{
  const d=fixture(),dir=testDirectory(t),ledgerStateFile=ledgerFor(dir,d),sheets=mockSheets(d);
  sheets.spreadsheets.values.batchUpdate=async()=>{throw Error('response lost after remote attempt');};
  await assert.rejects(prepareStreamSupps(sheets,{targetOffers:['MODEL-5'],backupDir:dir,ledgerStateFile}),/response lost/);
  sheets.spreadsheets.values.batchUpdate=()=>assert.fail('must not resend an attempted initialization');
  const retry=await prepareStreamSupps(sheets,{targetOffers:['MODEL-5'],backupDir:dir,ledgerStateFile});
  assert.equal(retry.changed,0);
});
