const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
process.env.CATALOG_ARTICLES_LOG_DIR = path.join(__dirname, 'tmp/catalog-articles-unit');
fs.mkdirSync(process.env.CATALOG_ARTICLES_LOG_DIR, {recursive:true});
const {TARGETS, planAppend, parsePage, updateTarget} = require('../catalog_articles_local');

assert.deepEqual(TARGETS.ozon.find(([name])=>name==='UNIT API'),['UNIT API','Артикул']);
assert.deepEqual(TARGETS.wb,[['UNIT WB','Артикул']]);
assert.deepEqual(planAppend('UNIT API','Артикул',['Артикул','СКУ OZ'],
  [['Артикул'],['0001-1']], [['Артикул'],['0001-1'],['=""']],['0001-1','0001-5']),
{last:3,missing:['0001-5']});
assert.throws(()=>planAppend('UNIT API','Артикул',[''],[],[],[]),/однозначно/);
assert.throws(()=>planAppend('UNIT API','Артикул',['','Артикул'],[],[],[]),/однозначно/);
assert.throws(()=>planAppend('UNIT API','Артикул',['Артикул','Артикул'],[],[],[]),/однозначно/);
assert.throws(()=>planAppend('UNIT API','Артикул',['Артикул'],[['Артикул'],['OLD']],
  [['={"Артикул";\'ТЕСТ\'!A2:A}']],['NEW']),/буквальный заголовок/);

let p = planAppend('ТЗ','Артикул',['Артикул'],[['Артикул'],['001-1'],[],[]],[['Артикул'],['001-1'],[],['=""']],['001-1','001-5','001-5','0002','=LITERAL']);
assert.equal(p.last,4);
assert.deepEqual(p.missing,['001-5','0002','=LITERAL']);
assert.throws(()=>planAppend('ТЗ','Артикул',['Артикул','Артикул'],[],[],[]),/однозначно/);
assert.throws(()=>planAppend('ТЗ','Артикул',['Other','Артикул'],[],[],[]),/однозначно/);
assert.throws(()=>planAppend('Дизайн контент',null,['Changed'],[],[],[]),/пустой заголовок/);
// StreamSupps has a documented blank A1 key, shared with its stock writers.
for (const firstHeader of ['', 'Артикул продавца']) {
  assert.deepEqual(planAppend('StreamSupps','Артикул продавца',[firstHeader,'CODES'],
    [[firstHeader],['OLD']],[[firstHeader],['OLD']],['OLD','NEW','NEW']),
  {last:2,missing:['NEW']});
}
assert.throws(()=>planAppend('StreamSupps','Артикул продавца',['Unknown'],[],[],[]),/не найден/);
assert.throws(()=>planAppend('StreamSupps','Артикул продавца',[],[],[],[]),/не найден/);
assert.throws(()=>planAppend('StreamSupps','Артикул продавца',[' ','CODES'],[],[],[]),/не найден/);
assert.throws(()=>planAppend('StreamSupps','Артикул продавца',['','Артикул продавца'],[],[],[]),/однозначно/);
assert.throws(()=>planAppend('StreamSupps','Артикул продавца',
  ['Артикул продавца','Артикул продавца'],[],[],[]),/дублируется/);
assert.throws(()=>planAppend('ТЗ','Артикул',[''],[],[],[]),/однозначно/);
assert.throws(()=>planAppend('Other','Артикул продавца',[''],[],[],[]),/однозначно/);
// UNIT WB legacy numeric cells can display a seller article via custom formatting.
assert.deepEqual(planAppend('UNIT WB','Артикул',['Артикул'],[['Артикул'],['6302-1']],
  [['Артикул'],[1607799]],['6302-1']).missing,[]);
assert.equal(parsePage('ozon',{result:{items:[{offer_id:'0001-10'}]}},1000).articles[0],'0001-10');
assert.equal(parsePage('wb',{cards:[{vendorCode:'WB-1'}]},100).articles[0],'WB-1');
assert.throws(()=>parsePage('wb',{cards:Array.from({length:100},()=>({vendorCode:'X'}))},100),/нет курсора/);
assert.throws(()=>parsePage('ozon',{result:{items:[{offer_id:123}]}},1000),/пустой артикул/);

(async()=>{
  const rows=[['Артикул'],['OLD']], writes=[];
  let capacity=2, failAfterCommit=true;
  const api={spreadsheets:{
    values:{batchGet:async({ranges})=>({data:{valueRanges:ranges.map(range=>({values:
      range.endsWith('!1:1')?[['Артикул']]:range.includes('!A3:A4')?rows.slice(2,4):rows.map(r=>[...r])
    }))}})},
    get:async()=>({data:{sheets:[{properties:{title:'ТЗ',sheetId:1,gridProperties:{rowCount:capacity}}}]}}),
    batchUpdate:async({requestBody})=>{
      writes.push(requestBody);
      for(const r of requestBody.requests){
        if(r.appendDimension) capacity+=r.appendDimension.length;
        if(r.updateCells){
          assert.equal(r.updateCells.range.startColumnIndex,0);
          assert.equal(r.updateCells.range.endColumnIndex,1);
          assert.equal(r.updateCells.fields,'userEnteredValue');
          r.updateCells.rows.forEach((row,i)=>{rows[r.updateCells.range.startRowIndex+i]=[row.values[0].userEnteredValue.stringValue];});
        }
      }
      if(failAfterCommit){failAfterCommit=false;throw Error('lost write response');}
      return {};
    }
  }};
  // The write committed but its response was lost. Mutation must not be resent.
  await assert.rejects(updateTarget(api,['ТЗ','Артикул'],['OLD','0001-1','=LITERAL'],false),/lost write response/);
  assert.equal(writes.length,1);
  assert.deepEqual(rows,[['Артикул'],['OLD'],['0001-1'],['=LITERAL']]);
  assert.equal((await updateTarget(api,['ТЗ','Артикул'],['OLD','0001-1','=LITERAL'],false)).added,0);
  assert.equal(writes.length,1);
  assert.equal(capacity,4);
  console.log('PASS header guards, blank formulas, zeros/suffixes/literal strings, deduplication, atomic A-only write and recovery after lost response');
})().catch(error=>{console.error(error);process.exitCode=1;});
