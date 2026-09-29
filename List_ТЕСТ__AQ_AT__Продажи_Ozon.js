/**
 * Compatibility shim for the legacy Apps Script trigger.
 * The scheduled AQ:AT sales refresh runs locally in ozon_fbo_fbs_sales_local.js.
 */
function updateOzonFBOSales() {
  return runWithTelegramAlertGAS_("updateOzonFBOSales", function() {
    Logger.log("Продажи Ozon AQ:AT обновляет локальный ozon_fbo_fbs_sales_local.js; Apps Script запись отключена.");
  });
}
