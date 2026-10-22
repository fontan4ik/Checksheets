function ntcFbsPaused_() {
  return (typeof NTC_FBS_TEMPORARILY_PAUSED !== 'undefined' && NTC_FBS_TEMPORARILY_PAUSED === true) || PropertiesService.getScriptProperties().getProperty('NTC_FBS_PAUSED') === 'true';
}
/** Persistent Google triggers run under the owner even with all browser tabs closed. */
function ntcRequireOwner_() {
  if (Session.getEffectiveUser().getEmail().toLowerCase() !== NTC_OWNER) throw new Error('Запустите от ' + NTC_OWNER);
}
function ntcInstallOrderTrigger_(replace) {
  if (ntcFbsPaused_()) return;
  if (replace) ScriptApp.getProjectTriggers().forEach(function(t) { if (t.getHandlerFunction()==='ntcCloudTick') ScriptApp.deleteTrigger(t); });
  const triggers = ScriptApp.getProjectTriggers();
  if (!triggers.some(function(t) { return t.getHandlerFunction() === 'ntcCloudTick'; })) ScriptApp.newTrigger('ntcCloudTick').timeBased().everyMinutes(5).create();
}
function ntcStartTransmission() {
  return ntcLocked_('Запуск трансляции', function() {
    ntcRequireOwner_();
    if (ntcFbsPaused_()) throw new Error('FBS приостановлен пользователем. Сначала возобновите учёт FBS.');
    ntcReadCatalog_(); ntcInstallOrderTrigger_();
    const p = PropertiesService.getScriptProperties();
    const triggers = ScriptApp.getProjectTriggers();
    if (!triggers.some(function(t) { return t.getHandlerFunction() === 'ntcTransmitterTick'; })) ScriptApp.newTrigger('ntcTransmitterTick').timeBased().everyMinutes(5).create();
    if (!triggers.some(function(t) { return t.getHandlerFunction() === 'ntcTransmissionOnce'; })) ScriptApp.newTrigger('ntcTransmissionOnce').timeBased().after(1000).create();
    p.setProperty('NTC_TRANSMISSION_RUNNING','true'); ntcSetToggleStatus_();
    const message = 'Облачная трансляция запущена. Можно закрыть вкладку. Передаются только площадки с отметкой ВКЛ.';
    ntcBook_().toast(message,'Склад НТЦ',12); return {ok:true,message:message};
  });
}
function ntcStopTransmission() {
  return ntcLocked_('Остановка трансляции', function() {
    ntcRequireOwner_(); PropertiesService.getScriptProperties().setProperty('NTC_TRANSMISSION_RUNNING','false');
    ScriptApp.getProjectTriggers().forEach(function(t) { if (['ntcTransmitterTick','ntcTransmissionOnce'].indexOf(t.getHandlerFunction()) >= 0) ScriptApp.deleteTrigger(t); });
    ntcSetToggleStatus_(); const message='Трансляция остановлена. Учёт FBS-заказов и возвратов продолжает работать.';
    ntcBook_().toast(message,'Склад НТЦ',10); return {ok:true,message:message};
  });
}
function ntcTransmitterTick() {
  return ntcBackgroundLocked_('Фоновая трансляция', function() {
    const p=PropertiesService.getScriptProperties();
    if (ntcFbsPaused_()) return {ok:true,message:'FBS приостановлен'};
    if (p.getProperty('NTC_TRANSMISSION_RUNNING') !== 'true') return {ok:true,message:'Трансляция остановлена'};
    if (p.getProperty('NTC_OZON_ENABLED')!=='true' && p.getProperty('NTC_WB_ENABLED')!=='true') { Logger.log(JSON.stringify({event:'transmission_tick',message:'Обе площадки выключены'})); return {ok:true,message:'Обе площадки выключены'}; }
    const result=ntcPublishCurrent_();
    p.setProperty('NTC_LAST_TRANSMISSION',new Date().toISOString());
    Logger.log(JSON.stringify({event:'transmission_tick',pending:!!result.pending,message:result.message}));
    return result;
  });
}
function ntcTransmissionOnce() {
  return runWithTelegramAlertGAS_('Разовый запуск трансляции', function() {
  // Google one-off triggers remain listed after running; remove only this handler.
  ScriptApp.getProjectTriggers().forEach(function(t) { if (t.getHandlerFunction()==='ntcTransmissionOnce') ScriptApp.deleteTrigger(t); });
  return ntcTransmitterTick();
  });
}
function ntcSetupRuntime() {
  return ntcLocked_('Настройка облачного учёта', function() {
    ntcRequireOwner_(); ntcInstallOrderTrigger_(true);
    const c=ntcReadCatalog_(); ntcFormatOperator_(ntcBook_().getSheetByName(NTC_OPERATOR),c);
    const eventSheet=ntcServiceSheet_('События FBS',NTC_FBS_EVENT_HEADERS_), envelope=ntcReadState_();
    if (!envelope.fbs_log_started_at) {
      const now=new Date().toISOString(), rows=[];
      Object.keys(envelope.engine.postings || {}).sort().forEach(function(number) {
        const posting=envelope.engine.postings[number];
        Object.keys(posting.items || {}).forEach(function(offer) {
          const a=envelope.engine.article_schema_by_offer[offer], stock=envelope.engine.last_f_by_model[a.model];
          rows.push(['baseline',now,number.indexOf('WB:')===0?'WB':'Ozon',number,'Снимок ранее учтённого заказа','',posting.status,offer,a.model,posting.items[offer],a.H,0,stock,stock,'Учтён до включения журнала; повторно не списывается','']);
        });
      });
      envelope.fbs_log_started_at=now;
      const requests=ntcJournalRequests_(envelope);
      if (rows.length) requests.push({appendCells:{sheetId:eventSheet.getSheetId(),rows:rows.map(function(r) { return {values:r.map(function(v) { return {userEnteredValue:typeof v==='number'?{numberValue:v}:{stringValue:String(v)}}; })}; }),fields:'userEnteredValue'}});
      Sheets.Spreadsheets.batchUpdate({requests:requests},NTC_BOOK_ID);
    }
    eventSheet.showSheet(); eventSheet.setFrozenRows(1); eventSheet.getRange(1,1,1,NTC_FBS_EVENT_HEADERS_.length).setFontWeight('bold').setBackground('#a7c8df').setWrap(true);
    eventSheet.setColumnWidths(1,NTC_FBS_EVENT_HEADERS_.length,150);
    ntcSetToggleStatus_(); return ntcDiagnostics();
  });
}

/** Same persistent mode as start/stop, with a single visible on/off control. */
function ntcToggleAutoTransmission() {
  return PropertiesService.getScriptProperties().getProperty("NTC_TRANSMISSION_RUNNING") === "true" ? ntcStopTransmission() : ntcStartTransmission();
}

/** Temporary owner pause: preserve ledger and Telegram bindings, make no MP calls. */
function ntcPauseFbs() {
  return ntcLocked_('Приостановка FBS', function() {
    ntcRequireOwner_();
    const p = PropertiesService.getScriptProperties();
    p.setProperties({NTC_FBS_PAUSED:'true',NTC_TRANSMISSION_RUNNING:'false',NTC_OZON_ENABLED:'false',NTC_WB_ENABLED:'false'},false);
    const stopped = ['ntcCloudTick','ntcTransmitterTick','ntcTransmissionOnce','ntcOperatorEdit'];
    ScriptApp.getProjectTriggers().forEach(function(t) { if (stopped.indexOf(t.getHandlerFunction()) >= 0) ScriptApp.deleteTrigger(t); });
    ntcSetToggleStatus_();
    const triggers = ScriptApp.getProjectTriggers().map(function(t) { return t.getHandlerFunction(); });
    if (triggers.some(function(h) { return stopped.indexOf(h) >= 0; })) throw new Error('Не все FBS-триггеры сняты');
    const result = {ok:true,fbsPaused:true,transmissionRunning:false,ozonEnabled:false,wbEnabled:false,remainingTriggers:triggers};
    Logger.log(JSON.stringify(result)); return result;
  });
}
