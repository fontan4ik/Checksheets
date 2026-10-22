const assert=require('node:assert/strict'),{TEMPLATES,MIN_ROW,PHOTO_OLD,PHOTO_NEW,translate,planPhotoLookup,planOborFormulas,requestsFor}=require('../obor_formulas_local');
// Recorded established formulas before repairing the new catalog block.
const head=require('./obor_canonical_formulas_fixture.json').values;
assert.equal(TEMPLATES.length,23);
const tail=[['NEW-1','','MANUAL BRAND','','','',123],['OTHER'],['NEW-5']];
const p=planOborFormulas(head,tail,['NEW-1','NEW-5']);
assert.equal(p.length,46);
assert.equal(p.filter(c=>c.column===3).length,1);
assert.equal(p.some(c=>c.row===MIN_ROW&&c.column===3),false);
assert.equal(p.find(c=>c.column===3).formula,`=IFERROR(XLOOKUP(A${MIN_ROW+2};'ТЕСТ'!A:A;'ТЕСТ'!C:C;"");"")`);
assert.equal(p.some(c=>c.row===MIN_ROW&&c.column===7),false);
assert.equal(p.some(c=>c.row===MIN_ROW+1),false);
assert.equal(p.find(c=>c.row===MIN_ROW+2&&c.column===30).formula,`=IFERROR(X${MIN_ROW+2}/AA${MIN_ROW+2};0)`);
assert.equal(p.find(c=>c.row===MIN_ROW+2&&c.column===7).formula,`=IFERROR(F${MIN_ROW+2}*H${MIN_ROW+2};0)`);
// A committed batch with a lost response must be recovered by re-reading,
// without resending or overwriting the cells that already contain formulas.
const committed=structuredClone(tail);
for(const c of p)committed[c.row-MIN_ROW][c.column-1]=c.formula;
assert.equal(planOborFormulas(head,committed,['NEW-1','NEW-5']).length,0);
assert.throws(()=>planOborFormulas(head,tail,['NEW-1'],MIN_ROW-1),/historical/);
assert.throws(()=>planOborFormulas(head,[['NEW-1'],['NEW-1']],['NEW-1']),/duplicate target/);
let changed=structuredClone(head);changed[3][6]='=MANUAL()';assert.throws(()=>planOborFormulas(changed,tail,['NEW-1']),/canonical/);
changed=structuredClone(head);changed[0][6]='Changed';assert.throws(()=>planOborFormulas(changed,tail,['NEW-1']),/header/);
changed=structuredClone(head);changed[0][7]=changed[0][6];assert.throws(()=>planOborFormulas(changed,tail,['NEW-1']),/duplicate header/);
const requests=requestsFor(p,123);assert.equal(requests.length,46);
for(const r of requests){assert.equal(r.updateCells.fields,'userEnteredValue');assert.equal(r.updateCells.range.sheetId,123);assert.equal(r.updateCells.range.endColumnIndex-r.updateCells.range.startColumnIndex,1);assert.equal(r.updateCells.range.endRowIndex-r.updateCells.range.startRowIndex,r.updateCells.rows.length);}
assert.equal(translate('=IFERROR(F2*$H$2;0)',MIN_ROW),`=IFERROR(F${MIN_ROW}*$H$2;0)`);
assert.equal(planPhotoLookup([[PHOTO_OLD]]),true);
assert.equal(planPhotoLookup([[PHOTO_NEW]]),false);
assert.throws(()=>planPhotoLookup([['Changed']]),/anchor/);
assert.throws(()=>planPhotoLookup([[PHOTO_OLD],['=IMAGE("manual")']]),/entered cells/);
assert.equal(PHOTO_NEW.includes("'ТЕСТ'!A:A"),true);
assert.equal(PHOTO_NEW.includes("'ТЕСТ'!B:B"),true);
assert.equal([...PHOTO_NEW].reduce((n,c)=>n+(c==='('?1:c===')'?-1:0),0),0);
console.log('PASS 23 canonical templates agreed across rows 2–4, strict schema guards, scoped missing-only writes, manual/static preservation, relative references and zero guards');
