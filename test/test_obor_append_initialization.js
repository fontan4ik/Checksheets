'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {prepareOborFormulas,MIN_ROW}=require('../obor_formulas_local');
test('OBOR initializes a new tail once and preserves later deletion and existing blanks',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'obor-append-'));
 try{
 const head=structuredClone(require('./obor_canonical_formulas_fixture.json').values),tail=[['EXISTING']],keys=Array.from({length:MIN_ROW},()=>[]);keys[0]=['Артикул'];keys[MIN_ROW-1]=['EXISTING'];let writes=0;
 const sheets={spreadsheets:{values:{batchGet:async()=>({data:{valueRanges:[{values:structuredClone(head)},{values:structuredClone(tail)},{values:structuredClone(keys)}]}})},get:async()=>({data:{sheets:[{properties:{title:'ОБОР',sheetId:8}}]}}),batchUpdate:async({requestBody})=>{writes++;for(const {updateCells:u}of requestBody.requests){assert.ok(u.range.startRowIndex>=MIN_ROW);u.rows.forEach((r,i)=>{const index=u.range.startRowIndex+i-MIN_ROW+1;tail[index]||=[];tail[index][u.range.startColumnIndex]=r.values[0].userEnteredValue.formulaValue;});}return{data:{}};}}};
 const opts={backupDir:dir,ledgerStateFile:path.join(dir,'ledger.json')};
 const baseline=await prepareOborFormulas(sheets,['EXISTING'],opts);assert.equal(baseline.written,0);assert.equal(writes,0);
 keys.push(['NEW']);tail.push(['NEW']);const initialized=await prepareOborFormulas(sheets,['EXISTING','NEW'],opts);assert.equal(initialized.written,24);assert.equal(writes,1);
 tail[1][6]='';const again=await prepareOborFormulas(sheets,['EXISTING','NEW'],opts);assert.equal(again.written,0);assert.equal(writes,1);assert.equal(tail[1][6],'');assert.equal(tail[0][6],undefined);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
