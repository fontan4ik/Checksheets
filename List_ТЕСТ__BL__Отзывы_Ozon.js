/**
 * Compatibility shims for legacy review-count triggers.
 * The full BL refresh runs locally in ozon_reviews_local.js.
 */
function updateOzonReviewCountBL() {
  return runWithTelegramAlertGAS_("updateOzonReviewCountBL", function() {
    Logger.log("Отзывы Ozon BL обновляет локальный ozon_reviews_local.js; Apps Script запись отключена.");
  });
}

function resumeOzonReviewCountBL() {
  return runWithTelegramAlertGAS_("resumeOzonReviewCountBL", function() {
    Logger.log("Локальный ozon_reviews_local.js владеет проходом отзывов; Apps Script продолжение отключено.");
  });
}

function updateOzonReviewCountBLManual() {
  return runWithTelegramAlertGAS_("updateOzonReviewCountBLManual", function() {
    Logger.log("Ручной Apps Script подсчёт отзывов отключён; используйте локальный ozon_reviews_local.js.");
  });
}
