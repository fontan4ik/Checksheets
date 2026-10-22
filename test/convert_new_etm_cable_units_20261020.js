'use strict';
const fs=require('node:fs');
const {google}=require('googleapis');
const {resolveStreamSuppsColumns}=require('../stream_supps_schema');
async function main(){
  const spreadsheetId='15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI';
  const entries=JSON.parse(fs.readFileSync('test/new_etm_unit_review_candidates_20261020.json')).entries;
  const targets=JSON.parse(fs.readFileSync('test/new_stream_targets_20261020.json'));
  const api=google.sheets({version:'v4',auth:new google.auth.GoogleAuth({keyFile:'nomadic-bedrock-485314-b0-d7624dedd83c.json',scopes:['https://www.googleapis.com/auth/spreadsheets']})});
  const ranges=["'StreamSupps'!A1:X1",...entries.map(e=>`'StreamSupps'!A${targets.find(t=>t.v[0]===e.offer_id).row}:X${targets.find(t=>t.v[0]===e.offer_id).row}`)];
  const before=(await api.spreadsheets.values.batchGet({spreadsheetId,ranges,valueRenderOption:'UNFORMATTED_VALUE'})).data;
  const columns=resolveStreamSuppsColumns(before.valueRanges[0].values[0],{offer:'Артикул продавца',model:'Артикул производителя',pack:'Х',etmRaw:'ETM SMR',etm:'ЭТМ САМАРА',rs:'РЕЗЕРВ'});
  if(columns.etmRaw!==17||columns.etm!==19||columns.pack!==6)throw Error('Established layout moved');
  const plan=entries.map((e,i)=>{
    const r=before.valueRanges[i+1].values[0],row=targets.find(t=>t.v[0]===e.offer_id).row;
    if(r[columns.offer-1]!==e.offer_id||r[columns.model-1]!==e.model||Number(r[columns.pack-1])!==1)throw Error('Cable identity/pack changed');
    return {range:`'StreamSupps'!S${row}`,values:[[`=ROUND(TRUNC(Q${row}/305)/F${row}/1,5;0)`]],offer:e.offer_id,row};
  });
  fs.writeFileSync('test/new_etm_cable_conversion_plan_20261020.json',JSON.stringify({before,columns,plan},null,2));
  console.log('Five metre-to-305m-coil conversions prepared');
  if(process.argv.includes('--apply')){
    await api.spreadsheets.values.batchUpdate({spreadsheetId,requestBody:{valueInputOption:'USER_ENTERED',data:plan.map(({range,values})=>({range,values}))}});
    const after=(await api.spreadsheets.values.batchGet({spreadsheetId,ranges:plan.map(x=>x.range),valueRenderOption:'FORMULA'})).data;
    for(let i=0;i<plan.length;i++)if(after.valueRanges[i].values[0][0].replace(/\s/g,'')!==plan[i].values[0][0].replace(/\s/g,''))throw Error('Formula readback mismatch');
    fs.writeFileSync('test/new_etm_cable_conversion_readback_20261020.json',JSON.stringify(after));
    console.log('Applied and verified all five ETM cable conversions');
  }
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
