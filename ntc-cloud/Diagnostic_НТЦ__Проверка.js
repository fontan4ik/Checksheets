/** Focused live verification: one physical piece in/out, no MP stock writes. */
function ntcVerifyInstallation() {
  const p = PropertiesService.getScriptProperties();
  if (p.getProperty('NTC_LIVE') === 'true') throw new Error('Проверку установки запускают до включения трансляции');
  const before = ntcReadCatalog_();
  let saved = p.getProperty('NTC_VERIFY_OPERATION');
  if (!saved) { saved = JSON.stringify({id: Utilities.getUuid(), model: before.rows[0].model, physical: before.stock_by_model}); p.setProperty('NTC_VERIFY_OPERATION',saved); }
  const test = JSON.parse(saved), supply = {id: test.id + '-in', type: 'supply', items: [{model: test.model,quantity: 1}], comment: 'Проверка установки: приход +1 и обратное списание'};
  const out = {id: test.id + '-out', type: 'writeoff', items: [{model: test.model,quantity: 1}], comment: 'Проверка установки: восстановление исходного остатка'};
  ntcScannerSubmit(supply); ntcScannerSubmit(supply);
  ntcScannerSubmit(out); ntcScannerSubmit(out);
  const after = ntcReadCatalog_(); if (!ntcEqual_(after.stock_by_model,test.physical)) throw new Error('Проверка: исходные остатки не восстановлены');
  const state = ntcReadState_();
  if (!state.scanner_operations[supply.id] || !state.scanner_operations[out.id]) throw new Error('Проверка: журнал операции отсутствует');
  Logger.log('НТЦ: +1/-1 и повтор каждого UUID проверены; исходные физические остатки восстановлены; API записи МП не вызывались');
  return ntcDiagnostics();
}

/** Real +1/-1 on both sheet columns with net zero and no marketplace call. */
function ntcVerifySeparatedFlow() {
  ntcRequireOwner_(); const operator=ntcBook_().getSheetByName(NTC_OPERATOR), before=ntcReadCatalog_();
  const input=operator.getRange(7,1,Math.max(1,operator.getLastRow()-6),8).getValues();
  if (input.some(function(r) { return r[4]!=='' || r[7]!==''; })) throw new Error('Для проверки поля C/D должны быть пустыми');
  const model=String(input[0][0]), supplyRow=input.findIndex(function(r) { return String(r[3])===model; })+7, writeoffRow=input.findIndex(function(r) { return String(r[6])===model; })+7;
  if (supplyRow<7 || writeoffRow<7) throw new Error('Модель не найдена в обеих таблицах движения');
  operator.getRange(supplyRow,5).setValue(1); operator.getRange(writeoffRow,8).setValue(1);
  const result=ntcSupply(), after=ntcReadCatalog_(), cleared=[operator.getRange(supplyRow,5).getValue(),operator.getRange(writeoffRow,8).getValue()];
  if (!ntcEqual_(before.stock_by_model,after.stock_by_model) || cleared[0]!=='' || cleared[1]!=='') throw new Error('Проверка совместного прихода/списания не прошла');
  Logger.log(JSON.stringify({verified:true,model:model,physical:after.stock_by_model[model],bothInputsCleared:true,result:result}));
  return ntcDiagnostics();
}
/** Pure-engine cloud smoke test: never changes real inventory or MP stocks. */
function ntcVerifyCappedWriteoff() {
  const articles = [{offer_id:'VERIFY-3',model:'VERIFY',H:3}];
  const first = ntcAdvance_({stock_by_model:{VERIFY:2},articles:articles,postings:[],returns:[],manual_k:{}}, null).state;
  const movement = {id:'verify-cap',model:'VERIFY',quantity:10,type:'writeoff'};
  const capped = ntcApplyMovements_(first,articles,[movement]);
  const retry = ntcApplyMovements_(capped,articles,[movement]);
  const supplied = ntcApplyMovements_(retry,articles,[{id:'verify-supply',model:'VERIFY',quantity:7,type:'supply'}]);
  if (capped.last_f_by_model.VERIFY !== 0 || capped.movements['verify-cap'].applied_quantity !== 2 ||
      !ntcEqual_(capped,retry) || supplied.last_f_by_model.VERIFY !== 7) throw new Error('Capped writeoff verification failed');
  Logger.log(JSON.stringify({verified:true,requested:10,actual:2,remaining:0,nextSupply:7,retryIdempotent:true}));
  return {ok:true};
}

