const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const DEFAULT_STALE_AFTER_MS = 15 * 60 * 1000;

function safeIso(value) {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? new Date().toISOString() : date.toISOString();
}

function localDateKey(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}${month}${day}`;
}

function normalizeAuditItem(item) {
  return {
    offerId: String(item.offerId || ""),
    chrtId: Number(item.chrtId) || 0,
    amount: Number(item.amount) || 0,
  };
}

function createWbStockAudit({
  scriptName,
  sheetName,
  sourceReadAt,
  logDirectory = path.join(__dirname, "logs"),
  staleAfterMs = Number(process.env.WB_STOCK_AUDIT_STALE_MS) || DEFAULT_STALE_AFTER_MS,
}) {
  const snapshotAt = safeIso(sourceReadAt || new Date());
  const runId = `${scriptName}-${snapshotAt.replace(/\D/g, "").slice(0, 17)}-${process.pid}`;
  const filePath = path.join(logDirectory, `wb_stock_payload_audit_${localDateKey()}.jsonl`);
  fs.mkdirSync(logDirectory, { recursive: true });

  let lastStaleWarningBucket = -1;

  function append(event) {
    fs.appendFileSync(
      filePath,
      `${JSON.stringify({
        recordedAt: new Date().toISOString(),
        runId,
        scriptName,
        sheetName,
        snapshotAt,
        ...event,
      })}\n`,
      "utf8",
    );
  }

  append({ event: "run_started", staleAfterSeconds: Math.round(staleAfterMs / 1000) });

  return {
    filePath,
    runId,
    snapshotAt,

    snapshotAgeSeconds(now = Date.now()) {
      return Math.max(0, Math.round((now - new Date(snapshotAt).getTime()) / 1000));
    },

    recordPayload({ warehouseId, warehouseName, sourceColumn, batchIndex, totalBatches, items }) {
      const normalizedItems = items.map(normalizeAuditItem);
      const ageSeconds = this.snapshotAgeSeconds();
      const checksum = crypto
        .createHash("sha256")
        .update(JSON.stringify(normalizedItems))
        .digest("hex")
        .slice(0, 16);
      const positiveItems = normalizedItems.filter((item) => item.amount > 0);
      const maxItem = positiveItems.reduce(
        (current, item) => (!current || item.amount > current.amount ? item : current),
        null,
      );

      append({
        event: "payload_prepared",
        warehouseId,
        warehouseName,
        sourceColumn,
        batchIndex,
        totalBatches,
        snapshotAgeSeconds: ageSeconds,
        staleSnapshot: ageSeconds * 1000 >= staleAfterMs,
        checksum,
        stats: {
          items: normalizedItems.length,
          positive: positiveItems.length,
          zero: normalizedItems.length - positiveItems.length,
          totalPieces: positiveItems.reduce((sum, item) => sum + item.amount, 0),
          maxItem,
        },
        items: normalizedItems,
      });

      const warningBucket = Math.floor((ageSeconds * 1000) / staleAfterMs);
      const shouldWarn = warningBucket >= 1 && warningBucket > lastStaleWarningBucket;
      if (shouldWarn) lastStaleWarningBucket = warningBucket;
      return { ageSeconds, checksum, shouldWarn };
    },

    recordBatchResult({ warehouseId, batchIndex, checksum, status, code, successCount, skippedCount, errorCount }) {
      append({
        event: "batch_result",
        warehouseId,
        batchIndex,
        checksum,
        status,
        code: Number(code) || 0,
        successCount: Number(successCount) || 0,
        skippedCount: Number(skippedCount) || 0,
        errorCount: Number(errorCount) || 0,
        snapshotAgeSeconds: this.snapshotAgeSeconds(),
      });
    },

    recordItemResult({ warehouseId, batchIndex, offerId, chrtId, amount, status, code }) {
      append({
        event: "item_result",
        warehouseId,
        batchIndex,
        offerId: String(offerId || ""),
        chrtId: Number(chrtId) || 0,
        amount: Number(amount) || 0,
        status,
        code: Number(code) || 0,
        snapshotAgeSeconds: this.snapshotAgeSeconds(),
      });
    },
  };
}

module.exports = { createWbStockAudit };
