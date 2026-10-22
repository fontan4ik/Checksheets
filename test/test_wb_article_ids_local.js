const assert = require('node:assert/strict');
const path = require('node:path');
const { HEADER, OLD_ARRAY, planWbArticleIds, requestsFor, prepareWbArticleIds } = require('../wb_article_ids_local');

const keys = [[''], ['A'], ['B'], ['C'], ['D'], ['A']];
const current = [[OLD_ARRAY], [123], ['WRONG'], [], ['OLDONLY']];
const tech = [['Артикул продавца', 'Код размера (chrt_id)', HEADER], ['A', '1', '123'], ['B', '2', '456'], ['C', '3', '789']];
const plan = planWbArticleIds(keys, current, tech);
assert.equal(plan.headerChange, true);
assert.equal(plan.existing, 3);
assert.equal(plan.matching, 1);
assert.deepEqual(plan.conflicts, [{ row: 3, offer: 'B', before: 'WRONG', expected: '456' }]);
assert.deepEqual(plan.sourceUnavailable, [{ row: 5, offer: 'D', before: 'OLDONLY' }]);
assert.deepEqual(plan.changes, [{ row: 4, offer: 'C', value: '789' }, { row: 6, offer: 'A', value: '123' }]);
assert.throws(() => planWbArticleIds(keys, [['Unexpected']], tech), /T1/);
assert.throws(() => planWbArticleIds(keys, current, [...tech, ['A', '4', '999']]), /ambiguous/);
assert.throws(() => planWbArticleIds(keys, current, [tech[0], ['A', '4', '0']]), /invalid/);
assert.throws(() => planWbArticleIds(keys, current, [['Артикул продавца', HEADER, HEADER], tech[1]]), /duplicate/);
assert.equal(planWbArticleIds([[''], ['A ']], [[HEADER]], tech).changes.length, 0);
for (const request of requestsFor(plan, 7)) {
  assert.equal(request.updateCells.range.startColumnIndex, 19);
  assert.equal(request.updateCells.range.endColumnIndex, 20);
  assert.equal(request.updateCells.fields, 'userEnteredValue');
}

(async () => {
  const fs=require('node:fs'),os=require('node:os');
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'wb-append-test-'));
  try {
  const liveKeys=[[''],['A'],['B']],rows=[[HEADER],[123],['WRONG']];let writes=0;
  const options={backupDir:dir,ledgerStateFile:path.join(dir,'ledger.json')};
  const sheets={spreadsheets:{
    values:{batchGet:async({valueRenderOption})=>({data:{valueRanges:valueRenderOption==='FORMULA'?[{values:structuredClone(rows)}]:[{values:structuredClone(liveKeys)},{values:tech}]}})},
    get:async()=>({data:{sheets:[{properties:{sheetId:7,title:'ТЕСТ'}}]}}),
    batchUpdate:async({requestBody})=>{writes++;for(const {updateCells} of requestBody.requests){assert.equal(updateCells.range.startColumnIndex,19);updateCells.rows.forEach((r,i)=>{rows[updateCells.range.startRowIndex+i]=[r.values[0].userEnteredValue.stringValue];});}throw Error('lost response after commit');}
  }};
  const baseline=await prepareWbArticleIds(sheets,options);assert.equal(baseline.written,0);assert.equal(writes,0);
  liveKeys.push(['C']);
  await assert.rejects(prepareWbArticleIds(sheets,options),/lost response/);assert.equal(writes,1);assert.equal(rows[3][0],'789');
  rows[3]=[];
  const recovered=await prepareWbArticleIds(sheets,options);assert.equal(recovered.planned,0);assert.equal(recovered.written,0);assert.equal(writes,1);assert.deepEqual(rows[3],[]);
  rows[0]=[OLD_ARRAY];await assert.rejects(prepareWbArticleIds(sheets,options),/header repair denied/);
  console.log('PASS append-only nmID, existing conflicts preserved, deletion and ambiguous writes never repeated');
  }finally{fs.rmSync(dir,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
