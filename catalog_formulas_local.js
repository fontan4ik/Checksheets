/** Formula templates for first initialization of newly appended catalog rows.
 * Spill anchors and
 * manual source inputs are never changed. Fixed formula layouts are checked
 * against visible headers before using the established spreadsheet formulas. */
const fs=require('node:fs'),path=require('node:path');
const {resolveStreamSuppsColumns}=require('./stream_supps_schema');
const BOOK='15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
// Verified migration boundaries, 2026-10-21: all earlier rows are protected
// even when duplicate inherited keys match a newly managed seller offer.
const DEFINITIONS={
  'UNIT API':{minimumRow:23795,end:'AS',key:'Артикул',fields:{
    W:{header:'НТЦ ДОП 1,1%',formula:'=-(J2+K2-((J2+K2)*0,989))'},
    Z:{header:'СБОРКА',formula:'=M2*-AA2',manualInputs:['AA']},
    AC:{header:'UNIT НАЧИСЛЕНО',formula:'=(J2+K2+N2+O2+P2+T2+U2+V2+W2+Z2)-X2-Y2-(AK2*AF2)',manualInputs:['AA']},
    AH:{header:'закупка на цену',formula:'=AB2/Q2'},
    AE:{header:'эко',formula:'=Q2-(Q2*AQ2)-AA2-AB2-R2-AF2',manualInputs:['AA','AQ']},
    AG:{header:'% НАЦЕНКИ К СБС ФАКТ',formula:'=(AC2/AD2)-1*100%',manualInputs:['AA','AD'],nonzeroInputs:['AD']},
    AK:{header:'упд + юнит',formula:'=AJ2+M2'},
    AL:{header:'Эко цель',formula:'=AO2-(AO2*AQ2)-AA2-AB2-R2-AF2',manualInputs:['AA','AO','AQ']},
    AM:{header:'ЦЕЛЬ 90',formula:'=(100+AA2+AB2+R2+AF2)/(1-AQ2)',manualInputs:['AA','AQ']},
    AN:{header:'ЦЕЛЕВАЯ ЦЕНА',formula:'=(AA2+AB2+R2+AF2)/(1-AQ2-AR2)',manualInputs:['AA','AR','AQ']},
    AP:{header:'НАЦЕНКА ОТ ЦЕНЫ ПРОДАЖИ',formula:'=AL2/AO2',manualInputs:['AA','AO']},
    AQ:{header:null,value:0.5219},
  },references:{J:'UNIT СУММА',K:'УПД',M:'UNIT ШТ',N:'ВОЗНАГРАЖДЕНИЕ',O:'ЛОГИСТИКА',P:'ПЕРЕПЛАТА',T:'ДОП',V:'ЗВЕЗДЫ + ЭКВ',X:'КЛИКИ',Y:'ЗАКАЗЫ',AB:'ЗАКУП',AD:'UNIT СБС',R:'ОВХ СР',AF:'СДЕК',AJ:'УПД ШТ'}},
  'ТЗ':{minimumRow:22546,end:'CK',key:'Артикул',fields:{
    W:{header:'СТАТУС',formula:"=VLOOKUP(I2;'ОБОР'!A:BF;38;0)",guard:'IFNA',fallback:'"Нет в ОБОР"'},
    Y:{header:'НАРУШЕНИЯ',formula:'=AA2-AC2'},
    AH:{header:'ПЛАН НАЦЕНКА ОТ ЦЕНЫ ПРОДАЖИ',formula:'=AG2/Z2*100%'},
    AI:{header:'РАЗНИЦА',formula:'=AH2-AL2'},
    AJ:{header:'ЦЕЛЕВАЯ ЧИСТАЯ НАЦ ШТ',formula:'=AK2/AE2'},
    BB:{header:'ФБС+ФБО',formula:'=BC2+BD2'},
    BO:{header:null,formula:'=(Z2-AE2)/Z2'},
    BS:{header:'РЕКЛ КЭФ',formula:'=AI2'},
  },references:{I:'ориг. артикул',AA:'ЦЕЛЕВАЯ ЦЕНА',AC:'МИЦ',AG:'ПЛАН НАЦЕНКА',Z:'Цена продажи',AL:'ЦЕЛЬ НАЦЕНКА ОТ ЦЕНЫ ПРОДАЖИ',AK:'ЦЕЛЕВАЯ НАЦЕНКА',AE:'ЗАКУП',BC:'ФБО',BD:'ФБС'}},
};
const blank=v=>v===undefined||v===null||v==='';
const text=v=>String(v??'').trim();
function col(s){return [...s].reduce((n,c)=>n*26+c.charCodeAt(0)-64,0);}
function norm(f){return String(f).replace(/\s/g,'').replace(/(\$?[A-Z]+)\$?\d+/g,'$1#').toUpperCase();}
function rowFormula(f,row){return f.replace(/([A-Z]+)2\b/g,(_,c)=>`${c}${row}`);}
function guardedFormula(field,row){
  if(Object.prototype.hasOwnProperty.call(field,'value'))return field.value;
  const formula=rowFormula(field.formula,row);
  const expression=`${field.guard||'IFERROR'}(${formula.slice(1)};${field.fallback||'""'})`;
  const missing=(field.manualInputs||[]).map(c=>`NOT(ISNUMBER(${c}${row}))`);
  missing.push(...(field.nonzeroInputs||[]).map(c=>`${c}${row}=0`));
  return missing.length?`=IF(OR(${missing.join(';')});"";${expression})`:`=${expression}`;
}
function planCatalogFormulas({sheetName,headers,formulas,keys,targetOffers}){
  if(!targetOffers)throw Error('Explicit targetOffers required; historical manual blanks are protected');
  const definition=DEFINITIONS[sheetName];if(!definition)throw Error('Unsupported catalog formula sheet');
  const schema={key:definition.key};
  for(const [c,h]of Object.entries(definition.references))schema[`ref_${c}`]=h;
  for(const [c,f]of Object.entries(definition.fields))if(f.header!==null)schema[c]=f.header;
  const resolved=resolveStreamSuppsColumns(headers,schema,sheetName);
  if(resolved.key!==1)throw Error(`${sheetName}: key moved from A`);
  for(const [field,actual]of Object.entries(resolved))if(field!=='key'){
    const expected=col(field.startsWith('ref_')?field.slice(4):field);
    if(actual!==expected)throw Error(`${sheetName}: fixed formula reference ${field} moved`);
  }
  if(sheetName==='UNIT API'){
    // The two literal header names "Цена продажи" and the service cells are
    // documented exceptions. They are checked at their exact established
    // positions, never silently searched by an ambiguous duplicate label.
    if(headers[16]!=='Цена продажи'||headers[40]!=='Цена продажи'||!blank(headers[26]))throw Error('UNIT API: service layout changed (Q/AA/AO)');
  }
  if(sheetName==='ТЗ'&&!blank(headers[col('BO')-1]))throw Error('ТЗ: documented blank BO header changed');
  const selected=new Set(targetOffers),changes=[],pending=[],counts={};
  for(const [letter,field]of Object.entries(definition.fields)){
    const index=col(letter)-1,canonical=norm(field.formula);
    const literal=Object.prototype.hasOwnProperty.call(field,'value');
    const historical=formulas.slice(1,definition.minimumRow-1);
    const verified=literal?historical.length>=1000&&historical.every(r=>r?.[index]===field.value):formulas.some((r,i)=>i>0&&typeof r[index]==='string'&&norm(r[index])===canonical);
    const eligible=keys.some((key,i)=>i+1>=definition.minimumRow&&selected.has(text(key?.[0]))&&blank(formulas[i]?.[index]));
    if(!eligible)continue;
    if(!verified){
      if(!literal)throw Error(`${sheetName}: no verified canonical template for ${letter}`);
      for(let i=1;i<keys.length;i++)if(i+1>=definition.minimumRow&&selected.has(text(keys[i]?.[0]))&&blank(formulas[i]?.[index]))pending.push({offer:text(keys[i][0]),row:i+1,field:letter,reason:'historical literal template changed; authoritative value required; preserved blank'});
      continue;
    }
    for(let i=1;i<keys.length;i++){
      const offer=text(keys[i]?.[0]),current=formulas[i]?.[index];
      if(!selected.has(offer))continue;
      if(i+1<definition.minimumRow||!blank(current))continue;
      const guarded=guardedFormula(field,i+1);
      changes.push({range:`'${sheetName}'!${letter}${i+1}`,values:[[guarded]],offer,row:i+1,column:letter});counts[letter]=(counts[letter]||0)+1;
    }
  }
  // Do not infer the merchant's financial assumptions from another product.
  // Missing inputs may legitimately leave target-price calculations pending.
  if(sheetName==='UNIT API')for(let i=1;i<keys.length;i++)if(i+1>=definition.minimumRow&&selected.has(text(keys[i]?.[0])))for(const c of ['AA','AO','AR']){
    if(blank(formulas[i]?.[col(c)-1]))pending.push({offer:text(keys[i][0]),row:i+1,field:c,reason:'manual financial input missing; preserved blank'});
  }
  return{sheetName,changes,changed:changes.length,counts,pending};
}
async function prepare(sheets,{targetOffers,dryRun=false,spreadsheetId=BOOK,backupDir=path.join(__dirname,'test','runtime'),readRetryDelayMs=1000,readMinGapMs=2000,ledgerStateFile,claimAppendInitializations}={}){
  if(!targetOffers)throw Error('Explicit targetOffers required');
  let lastReadAt=0;
  const read=async params=>{for(let attempt=0;;attempt++)try{
    const wait=Math.max(0,lastReadAt+readMinGapMs-Date.now());if(wait)await new Promise(r=>setTimeout(r,wait));lastReadAt=Date.now();
    return await sheets.spreadsheets.values.batchGet({spreadsheetId,...params},{timeout:90000,retry:false});}catch(e){
    const transient=/quota exceeded/i.test(e.message||'')||[408,429,500,502,503,504].includes(Number(e.response?.status))||['ECONNRESET','ETIMEDOUT','ECONNABORTED','EAI_AGAIN','ENOTFOUND'].includes(e.code)||/socket hang up/i.test(e.message||'');
    if(!transient||attempt>=3)throw e;const delay=Number(e.response?.status)===429||/quota exceeded/i.test(e.message||'')?Math.min(60000,Math.max(30000,readRetryDelayMs)*2**attempt):readRetryDelayMs*2**attempt;await new Promise(r=>setTimeout(r,delay));
  }};
  const result={changed:0,sheets:{},pending:[],errors:[]};
  for(const [name,def]of Object.entries(DEFINITIONS)){
    const prefix=`'${name}'`;
    const index=await read({ranges:[`${prefix}!1:1`,`${prefix}!A:A`],valueRenderOption:'UNFORMATTED_VALUE'});
    const headers=index.data.valueRanges[0].values?.[0]||[],keys=index.data.valueRanges[1].values||[],last=Math.max(2,keys.length);
    const entered=await read({ranges:[`${prefix}!A1:${def.end}${last}`],valueRenderOption:'FORMULA'});
    const formulas=entered.data.valueRanges[0].values||[];
    // Observe all governed destinations, including nonempty/manual cells. A
    // later deletion must never become a first initialization opportunity.
    const observedCells=[];
    for(let i=1;i<keys.length;i++){
      const offer=text(keys[i]?.[0]);if(!offer)continue;
      for(const column of Object.keys(def.fields)){
        const entered=formulas[i]?.[col(column)-1]??'';
        const isFormula=typeof entered==='string'&&entered.startsWith('=');
        observedCells.push({row:i+1,offer,column,value:isFormula?'':entered,formula:isFormula?entered:''});
      }
    }
    const claim=claimAppendInitializations||require('./append_initialization_ledger').claimAppendInitializations;
    const ledgerOptions={scope:'catalog-formulas',sheetName:name,keys,observedCells,stateFile:ledgerStateFile};
    // Gate row/cell eligibility before validating templates: protected existing
    // rows cannot require a template that this run will never use.
    const selected=new Set(targetOffers);
    const candidates=observedCells.filter(c=>selected.has(c.offer)&&c.row>=def.minimumRow&&blank(c.value)&&blank(c.formula)).map(c=>({...c,range:`${prefix}!${c.column}${c.row}`}));
    const eligibility=claim({...ledgerOptions,changes:candidates,dryRun:true});
    if(!eligibility.authorized.length){
      if(!dryRun)claim({...ledgerOptions,changes:[],dryRun:false});
      result.sheets[name]={changed:0,proposed:0,counts:{},blocked:eligibility.blocked.length,seeded:eligibility.seeded,admittedRows:eligibility.admittedRows.length};
      continue;
    }
    const eligibleOffers=new Set(eligibility.authorized.map(c=>c.offer));
    const proposed=planCatalogFormulas({sheetName:name,headers,formulas,keys,targetOffers:eligibleOffers});
    const admission=claim({...ledgerOptions,changes:proposed.changes,dryRun:true});
    const counts={};for(const change of admission.authorized)counts[change.column]=(counts[change.column]||0)+1;
    const plan={...proposed,changes:admission.authorized,changed:admission.authorized.length,counts};
    result.sheets[name]={changed:plan.changed,proposed:proposed.changed,counts,
      blocked:admission.blocked.length,seeded:admission.seeded,admittedRows:admission.admittedRows.length};
    result.pending.push(...plan.pending);result.changed+=plan.changed;
    if(dryRun)continue;
    if(!plan.changed){claim({...ledgerOptions,changes:[],dryRun:false});continue;}
    const written=[];
    fs.mkdirSync(backupDir,{recursive:true});
    const backup=path.join(backupDir,`catalog-formulas-before-${name==='ТЗ'?'tz':'unit'}-${Date.now()}-${process.pid}.json`);
    fs.writeFileSync(backup,JSON.stringify({at:new Date().toISOString(),headers,keys,formulas,plan}),{mode:0o600});
    result.sheets[name].backup=backup;
    for(let start=0;start<plan.changes.length;start+=500){
      const batch=plan.changes.slice(start,start+500);
      const rowNumbers=[...new Set(batch.map(c=>c.row))].sort((a,b)=>a-b),segments=[];
      for(const row of rowNumbers){const prior=segments.at(-1);if(prior&&row===prior.end+1&&row-prior.start<250)prior.end=row;else segments.push({start:row,end:row});}
      const ranges=segments.map(s=>`${prefix}!A${s.start}:${def.end}${s.end}`);
      const mapRows=response=>{const result=new Map();segments.forEach((s,i)=>{for(let row=s.start;row<=s.end;row++)result.set(row,response.data.valueRanges[i].values?.[row-s.start]||[]);});return result;};
      const checked=mapRows(await read({ranges,valueRenderOption:'FORMULA'}));
      batch.forEach(c=>{const row=checked.get(c.row);if(!blank(row[col(c.column)-1])||text(row[0])!==c.offer)throw Error(`Concurrent edit at ${c.range}`);});
      const freshObserved=observedCells.map(item=>{
        if(!checked.has(item.row))return item;
        const current=checked.get(item.row)[col(item.column)-1]??'';
        const isFormula=typeof current==='string'&&current.startsWith('=');
        return {...item,value:isFormula?'':current,formula:isFormula?current:''};
      });
      const issued=claim({...ledgerOptions,changes:batch,observedCells:freshObserved,dryRun:false});
      result.sheets[name].blocked+=issued.blocked.length;
      const authorized=issued.authorized;if(!authorized.length)continue;
      await sheets.spreadsheets.values.batchUpdate({spreadsheetId,requestBody:{valueInputOption:'USER_ENTERED',data:authorized.map(({range,values})=>({range,values}))}},{timeout:90000,retry:false});
      const verified=mapRows(await read({ranges,valueRenderOption:'FORMULA'}));
      authorized.forEach(c=>{if(verified.get(c.row)?.[col(c.column)-1]!==c.values[0][0])throw Error(`Formula read-back mismatch at ${c.range}`);});
      written.push(...authorized);
    }
    result.changed+=written.length-plan.changed;
    const actualCounts={};for(const c of written)actualCounts[c.column]=(actualCounts[c.column]||0)+1;
    Object.assign(result.sheets[name],{changed:written.length,counts:actualCounts});
    if(!written.length)continue;
    const ranges=[];const rows=[...new Set(written.map(c=>c.row))].sort((a,b)=>a-b);
    for(let start=0;start<rows.length;start+=100){const block=rows.slice(start,start+100);ranges.push(`${prefix}!A${block[0]}:${def.end}${block.at(-1)}`);}
    const evaluated=await read({ranges,valueRenderOption:'UNFORMATTED_VALUE'});
    const errors=[];for(const group of evaluated.data.valueRanges)for(const [i,row]of(group.values||[]).entries())for(const [j,value]of row.entries())if(typeof value==='string'&&/^#(REF!|ERROR!|DIV\/0!|N\/A|VALUE!|NUM!|NAME\?)/.test(value))errors.push({range:group.range,offsetRow:i,offsetColumn:j,value});
    result.sheets[name].calculatedErrors=errors;result.errors.push(...errors.map(e=>({sheet:name,...e})));
    const reportFile=path.join(backupDir,`catalog-formulas-result-${name==='ТЗ'?'tz':'unit'}-${Date.now()}.json`);fs.writeFileSync(reportFile,JSON.stringify(result.sheets[name],null,2));
  }
  return result;
}
module.exports={prepare,planCatalogFormulas,DEFINITIONS,guardedFormula};
