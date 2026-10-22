'use strict';
const fs=require('node:fs'),path=require('node:path');
const BOOK='15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
// Verified managed migration block: 273 offers from 2026-10-20 occupy
// 32002:32274, followed by 458 offers from 2026-10-21 in 32275:32732.
// Earlier historical rows retain their manual blanks; offer scope is explicit.
const MIN_ROW=32002;
const TEMPLATES=[
  {
    "column": 7,
    "header": "НТЦ СУММ",
    "formula": "=IFERROR(F2*H2;0)"
  },
  {
    "column": 10,
    "header": "Сумма в пути",
    "formula": "=IFERROR(I2*H2;0)"
  },
  {
    "column": 13,
    "header": "СДЭК СУММА",
    "formula": "=IFERROR(L2*H2;0)"
  },
  {
    "column": 14,
    "header": "Сумма озон ост",
    "formula": "=IFERROR(K2*H2;0)"
  },
  {
    "column": 17,
    "header": "ДИНАМИКА ОЗОН",
    "formula": "=IFERROR(O2/(R2/3);0)"
  },
  {
    "column": 21,
    "header": "РАЗНИЦА ОСТ НА МП",
    "formula": "=IFERROR(N2/Y2;0)"
  },
  {
    "column": 23,
    "header": "Сумм",
    "formula": "=V2*H2"
  },
  {
    "column": 25,
    "header": "ВБ ОСТ СУММ",
    "formula": "=X2*H2"
  },
  {
    "column": 28,
    "header": "ВБ ФАКТ ВЫКУПА  МЕС СУММА СБС",
    "formula": "=AA2*H2"
  },
  {
    "column": 29,
    "header": "ДИНАМИКА",
    "formula": "=IFERROR(Z2/(AE2/3);0)"
  },
  {
    "column": 30,
    "header": "ФАКТ/ОСТ В МЕС",
    "formula": "=X2/AA2"
  },
  {
    "column": 34,
    "header": "ОБОРТЬ",
    "formula": "=IFERROR(AO2/(P2+AA2);0)"
  },
  {
    "column": 39,
    "header": "ВЫКУП 1 МЕС",
    "formula": "=AA2+P2"
  },
  {
    "column": 41,
    "header": "ОБЩ ОСТ",
    "formula": "=X2+K2+F2+L2+I2"
  },
  {
    "column": 42,
    "header": "СУММ",
    "formula": "=G2+N2+Y2+M2+J2"
  },
  {
    "column": 43,
    "header": "ВЫКУП 1 МЕС",
    "formula": "=P2+AA2"
  },
  {
    "column": 44,
    "header": "ПРОД 1 КВ",
    "formula": "=R2+AE2"
  },
  {
    "column": 45,
    "header": "ПРОД 1 ГОД",
    "formula": "=S2+AG2"
  },
  {
    "column": 46,
    "header": "Обор 1 МЕС",
    "formula": "=IF(AND(AO2=0; AQ2>0); \"Out of stock\"; IF(AND(AO2>0; AQ2=0); \"No sales\"; IF(AQ2=0; 0; AO2/AQ2)))"
  },
  {
    "column": 47,
    "header": "Обор 1 КВ",
    "formula": "=IFERROR(AO2/AR2;0)"
  },
  {
    "column": 48,
    "header": "Обор 1 ГОД",
    "formula": "=IFERROR(AO2/AS2;0)"
  },
  {
    "column": 49,
    "header": "СБС ВЫКУП/МЕС",
    "formula": "=IFERROR(H2*AQ2;0)"
  },
  {
    "column": 54,
    "header": "Сумма всех остатков",
    "formula": "=H2*AO2"
  }
];
const text=x=>String(x??'').trim(),norm=x=>text(x).toLowerCase().replace(/\s+/g,' ');
const PHOTO_OLD='={ "ФОТО"; ARRAYFORMULA(IFERROR(XLOOKUP(A2:A & ""; \'ТЕСТ\'!B:B; \'ТЕСТ\'!E:E; ""))) }';
const PHOTO_NEW='={ "ФОТО"; ARRAYFORMULA(IFERROR(XLOOKUP(A2:A & ""; \'ТЕСТ\'!A:A; \'ТЕСТ\'!E:E); IFERROR(XLOOKUP(A2:A & ""; \'ТЕСТ\'!B:B; \'ТЕСТ\'!E:E; ""); ""))) }';
function planPhotoLookup(rows){
  const anchor=text(rows[0]?.[0]);
  if(anchor!==PHOTO_OLD&&anchor!==PHOTO_NEW)throw Error('ОБОР: unexpected photo anchor');
  if(rows.slice(1).some(r=>text(r[0])))throw Error('ОБОР: photo spill contains entered cells');
  return anchor===PHOTO_OLD;
}
async function preparePhotoLookup(sheets,options={}){
  const spreadsheetId=options.spreadsheetId||BOOK;
  const read=async()=> (await sheets.spreadsheets.values.get({spreadsheetId,range:"'ОБОР'!B:B",valueRenderOption:'FORMULA'},{timeout:120000})).data;
  const before=await read(),planned=planPhotoLookup(before.values||[]),report={planned,written:false};
  if(!planned||options.dryRun)return report;
  const backupDir=options.backupDir||path.join(__dirname,'test','runtime');fs.mkdirSync(backupDir,{recursive:true});
  report.backup=path.join(backupDir,`obor-photo-before-${Date.now()}-${process.pid}.json`);fs.writeFileSync(report.backup,JSON.stringify(before,null,2));
  if(JSON.stringify(await read())!==JSON.stringify(before))throw Error('ОБОР: concurrent photo cells changed');
  await sheets.spreadsheets.values.update({spreadsheetId,range:"'ОБОР'!B1",valueInputOption:'USER_ENTERED',requestBody:{values:[[PHOTO_NEW]]}},{timeout:120000,retry:false});
  if(text((await read()).values?.[0]?.[0])!==PHOTO_NEW)throw Error('ОБОР: photo formula read-back mismatch');
  const checked=(await sheets.spreadsheets.values.get({spreadsheetId,range:"'ОБОР'!B1",valueRenderOption:'FORMATTED_VALUE'},{timeout:120000})).data;
  if(checked.values?.[0]?.[0]!=='ФОТО')throw Error('ОБОР: photo array error after change');
  report.written=true;return report;
}
function translate(formula,row,from=2){return formula.replace(/(\$?[A-Z]{1,3})(\$?)(\d+)/g,(m,col,absolute,n)=>!absolute&&Number(n)===from?col+row:m);}
function validate(head){
  const headers=head[0]||[];
  const brands=headers.flatMap((h,i)=>norm(h)==='бренд'?[i+1]:[]);
  if(JSON.stringify(brands)!=='[3]')throw Error('ОБОР: moved/missing/duplicate brand header');
  for(const template of TEMPLATES){
    const matches=headers.flatMap((h,i)=>norm(h)===norm(template.header)?[i+1]:[]);
    // These two established service fields have duplicate visible headers.
    // Their exact guarded positions are documented rather than guessed.
    const expected=norm(template.header)==='сумм'?[23,42]:norm(template.header)==='выкуп 1 мес'?[39,43]:[template.column];
    if(JSON.stringify(matches)!==JSON.stringify(expected))throw Error('ОБОР: moved/missing/duplicate header '+template.header);
    for(let row=2;row<=4;row++)if(translate(head[row-1]?.[template.column-1]||'',2,row)!==template.formula)throw Error('ОБОР: canonical formula changed '+template.column+'/'+row);
  }
}
function planOborFormulas(head,tail,offers,minRow=MIN_ROW){
  if(!Number.isInteger(minRow)||minRow<MIN_ROW)throw Error('ОБОР: unsafe historical start row');
  validate(head);const allowed=new Set(offers.map(text)),seen=new Set(),changes=[];
  tail.forEach((values,i)=>{const offer=text(values[0]);if(!allowed.has(offer))return;if(seen.has(offer))throw Error('ОБОР: duplicate target offer '+offer);seen.add(offer);const row=minRow+i;
    for(const t of TEMPLATES)if(!text(values[t.column-1])){let formula=translate(t.formula,row);if(!/^=IFERROR\(/i.test(formula))formula='=IFERROR('+formula.slice(1)+';0)';changes.push({offer,row,column:t.column,formula});}
    // Only new blank brand cells use the authoritative exact-offer source.
    // Established manual brands are never copied or overwritten.
    if(!text(values[2]))changes.push({offer,row,column:3,formula:`=IFERROR(XLOOKUP(A${row};'ТЕСТ'!A:A;'ТЕСТ'!C:C;"");"")`});
  });return changes;
}
function requestsFor(changes,sheetId){
  const byColumn=new Map();for(const c of changes){if(!byColumn.has(c.column))byColumn.set(c.column,[]);byColumn.get(c.column).push(c);}
  const requests=[];for(const [column,cells]of byColumn){let group=[];const flush=()=>{if(!group.length)return;requests.push({updateCells:{range:{sheetId,startRowIndex:group[0].row-1,endRowIndex:group.at(-1).row,startColumnIndex:column-1,endColumnIndex:column},rows:group.map(c=>({values:[{userEnteredValue:{formulaValue:c.formula}}]})),fields:'userEnteredValue'}});group=[];};for(const c of cells){if(group.length&&c.row!==group.at(-1).row+1)flush();group.push(c);}flush();}return requests;
}
async function prepareOborFormulas(sheets,offers,options={}){
  const spreadsheetId=options.spreadsheetId||BOOK,minRow=options.minRow??MIN_ROW;
  const ranges=["'ОБОР'!A1:BC4",`'ОБОР'!A${minRow}:BC`,"'ОБОР'!A:A"];
  const read=async(render='FORMULA')=>(await sheets.spreadsheets.values.batchGet({spreadsheetId,ranges,valueRenderOption:render},{timeout:120000})).data;
  const before=await read(),head=before.valueRanges[0].values||[],tail=before.valueRanges[1].values||[];
  const keys=before.valueRanges[2].values||[],columns=[3,...TEMPLATES.map(t=>t.column)],observedCells=[];
  tail.forEach((values,i)=>{const row=minRow+i,offer=text(keys[row-1]?.[0]);if(!offer)return;for(const column of columns)observedCells.push({row,offer,column,value:values[column-1]??''});});
  const ledger=require('./append_initialization_ledger'),ledgerOptions={scope:'obor-formulas',sheetName:'ОБОР',keys,columns,observedCells,stateFile:options.ledgerStateFile,dryRun:!!options.dryRun};
  ledger.claimAppendInitializations({...ledgerOptions,changes:[]});
  const eligibility=ledger.inspectAppendEligibility(ledgerOptions);
  const eligible=new Set(eligibility.eligibleOffers),selected=offers.filter(o=>eligible.has(text(o)));
  if(!selected.length)return {planned:0,rows:0,written:0,protectedExisting:true};
  const proposed=planOborFormulas(head,tail,selected,minRow);
  const admission=ledger.claimAppendInitializations({...ledgerOptions,changes:proposed});
  const changes=admission.authorized;
  const report={planned:changes.length,blocked:admission.blocked.length,rows:new Set(changes.map(c=>c.row)).size,written:0};if(!changes.length||options.dryRun)return report;
  const backupDir=options.backupDir||path.join(__dirname,'test','runtime');fs.mkdirSync(backupDir,{recursive:true});report.backup=path.join(backupDir,`obor-formulas-before-${Date.now()}-${process.pid}.json`);fs.writeFileSync(report.backup,JSON.stringify({at:new Date().toISOString(),before,changes},null,2));
  if(JSON.stringify(await read())!==JSON.stringify(before))throw Error('ОБОР: concurrent cells changed');
  const metadata=(await sheets.spreadsheets.get({spreadsheetId,fields:'sheets.properties'},{timeout:120000})).data,sheetId=metadata.sheets.find(s=>s.properties.title==='ОБОР')?.properties.sheetId;if(sheetId===undefined)throw Error('ОБОР sheet missing');
  const requests=requestsFor(changes,sheetId);for(let i=0;i<requests.length;i+=500)await sheets.spreadsheets.batchUpdate({spreadsheetId,requestBody:{requests:requests.slice(i,i+500)}},{timeout:120000,retry:false});
  const after=await read(),actual=after.valueRanges[1].values||[];for(const c of changes)if(actual[c.row-minRow]?.[c.column-1]!==c.formula)throw Error('ОБОР: formula read-back mismatch '+c.row+'/'+c.column);
  const effective=(await read('FORMATTED_VALUE')).valueRanges[1].values||[];const errors=changes.filter(c=>text(effective[c.row-minRow]?.[c.column-1]).startsWith('#'));if(errors.length)throw Error('ОБОР: new formula errors '+errors.length);
  report.written=changes.length;report.effectiveErrors=0;return report;
}
module.exports={MIN_ROW,TEMPLATES,PHOTO_OLD,PHOTO_NEW,translate,planPhotoLookup,planOborFormulas,requestsFor,preparePhotoLookup,prepareOborFormulas};
