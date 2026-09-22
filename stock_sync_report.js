"use strict";

/*
 * Common, side-effect-free report accounting for local stock synchronizers.
 * The notifier deliberately receives raw counters so it can evolve its message
 * format without each writer inventing a different meaning for “success”.
 */

function numberOrZero(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? Math.trunc(number) : 0;
}

function buildStockReport({
  sourcePositiveSku = 0,
  attemptedSku = 0,
  acceptedSku = 0,
  skippedSku = 0,
  errorSku = 0,
  verification = null,
  runId = null,
  snapshotReadAt = null,
  snapshotSources = null,
  ...identity
} = {}) {
  const mismatchSku = numberOrZero(verification?.mismatchSku);
  const verificationStatus = verification?.status || "not_run";
  return {
    ...identity,
    sourcePositiveSku: numberOrZero(sourcePositiveSku),
    attemptedSku: numberOrZero(attemptedSku),
    acceptedSku: numberOrZero(acceptedSku),
    skippedSku: numberOrZero(skippedSku),
    errorSku: numberOrZero(errorSku),
    verifiedPositiveSku: verification?.positiveSku ?? null,
    verifiedPieces: verification?.pieces ?? null,
    mismatchSku,
    verificationStatus,
    runId: runId || null,
    snapshotReadAt: snapshotReadAt || null,
    snapshotSources: snapshotSources || null,
  };
}

function stockSyncFailure(report) {
  if (numberOrZero(report?.errorSku) > 0) {
    return `${report.marketplace || "marketplace"} ${report.warehouseName || "warehouse"}: необработанных ошибок записи ${report.errorSku}`;
  }
  if (report?.verificationStatus === "mismatch" && numberOrZero(report?.mismatchSku) > 0) {
    return `${report.marketplace || "marketplace"} ${report.warehouseName || "warehouse"}: после post-check остались расхождения ${report.mismatchSku}`;
  }
  if (report?.verificationStatus === "incomplete") {
    return `${report.marketplace || "marketplace"} ${report.warehouseName || "warehouse"}: post-check выполнен неполностью`;
  }
  return null;
}

function throwOnStockSyncFailures(reports) {
  const failures = (reports || []).map(stockSyncFailure).filter(Boolean);
  if (failures.length) throw new Error(failures.join("; "));
}

module.exports = { buildStockReport, stockSyncFailure, throwOnStockSyncFailures };
