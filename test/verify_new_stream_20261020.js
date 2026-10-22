'use strict';
const fs=require('node:fs');
const {google}=require('googleapis');
const {resolveStreamSuppsColumns}=require('../stream_supps_schema');
async function main(){
  const sheets=google.sheets({version:'v4',auth:new google.auth.GoogleAuth({keyFile:'nomadic-bedrock-485314-b0-d7624dedd83c.json',scopes:['https://www.googleapis.com/auth/spreadsheets.readonly']})});
  const spreadsheetId='15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
  const response=(await sheets.spreadsheets.values.batchGet({spreadsheetId,ranges:["'StreamSupps'!A1:AE1","'StreamSupps'!A21999:AE22487","'StreamSupps'!T1:T22864"],valueRenderOption:'UNFORMATTED_VALUE'},{timeout:90000})).data;
  const headers=response.valueRanges[0].values[0],rows=response.valueRanges[1].values,codes=response.valueRanges[2].values;
  const cols=resolveStreamSuppsColumns(headers,{offer:'Артикул продавца',code:'CODES',model:'Артикул производителя',brand:'brand',sku:'SKU OZON',chrt:'chrlid',etm:'ЭТМ САМАРА',etmRaw:'ETM SMR',rs:'РЕЗЕРВ',rsRaw:'RS SMR',rsMoscow:{header:'РУССКИЙ СВЕТ МОСКВА',occurrence:1},wb:'WB ВОЛЬТМИР ИТОГ',wbMoscow:'ФБС ФЕРОН МОСКВА'});
  if(cols.code!==20)throw Error('CODES moved, explicit read must be updated');
  const before=JSON.parse(fs.readFileSync('test/new_stream_before_20261020.json'));
  const targets=JSON.parse(fs.readFileSync('test/new_stream_targets_20261020.json'));
  const result={at:new Date().toISOString(),count:rows.length,codesFilled:0,missingCodes:[],missingOzonSku:0,missingWbChrt:0,etmPositive:0,rsPositive:0,moscowPositive:0,preservedExistingCodes:true,errors:[],changedIdentity:[],wbFormulaMismatches:[]};
  for(let i=1;i<before.length;i++)if(before[i][cols.code-1]&&String(before[i][cols.code-1])!==String(codes[i]?.[0]||''))result.preservedExistingCodes=false;
  rows.forEach((r,i)=>{
    const t=targets[i];
    for(const field of ['offer','model','brand','sku'])if(String(r[cols[field]-1]||'')!==String(t.v[cols[field]-1]||''))result.changedIdentity.push({offer:t.v[0],field});
    if(r[cols.code-1])result.codesFilled++;else result.missingCodes.push(t.v[0]);
    if(!r[cols.sku-1])result.missingOzonSku++;
    if(!r[cols.chrt-1])result.missingWbChrt++;
    if(Number(r[cols.etm-1])>1)result.etmPositive++;
    if(Number(r[cols.rs-1])>1)result.rsPositive++;
    if(Number(r[cols.rsMoscow-1])>0)result.moscowPositive++;
    for(const field of ['etm','etmRaw','rs','rsRaw','rsMoscow','wb','wbMoscow'])if(!Number.isFinite(Number(r[cols[field]-1]))||r[cols[field]-1]===''||r[cols[field]-1]===undefined)result.errors.push({offer:t.v[0],field,value:r[cols[field]-1]});
    // Established AB=N+S+V, AC=M+X fixed source letters confirmed in headers.
    if(Number(r[cols.wb-1])!==Math.round(Number(r[13])+Number(r[18])+Number(r[21]))||Number(r[cols.wbMoscow-1])!==Math.round(Number(r[12])+Number(r[23])))result.wbFormulaMismatches.push(t.v[0]);
  });
  fs.writeFileSync('test/new_stream_final_verification_20261020.json',JSON.stringify(result,null,2));
  fs.writeFileSync('test/new_stream_final_values_20261020.json',JSON.stringify(response));
  console.log(JSON.stringify(result));
  if(!result.preservedExistingCodes||result.changedIdentity.length||result.errors.length||result.wbFormulaMismatches.length||result.moscowPositive)process.exitCode=1;
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
