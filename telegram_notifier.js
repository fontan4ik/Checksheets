/**
 * Telegram notification and FBS broadcast metrics module for Node.js scripts.
 */

const axios = require("axios");
const fs = require("fs");
const path = require("path");

const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || "8795048754:AAHXbXFhzTHa6ICvwyQ1sE2pBvb-ZgqZIac";
const CHAT_ID = process.env.TELEGRAM_CHAT_ID || "751491813";
const TELEGRAM_API_URL = `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`;
const LOGS_DIR = path.join(__dirname, "logs");
const FBS_REPORT_QUEUE_FILE = path.join(LOGS_DIR, "fbs_broadcast_report_queue.json");

/**
 * Safe Telegram text message sender.
 */
async function sendTelegramMessage(text, parseMode = "HTML") {
  if (!BOT_TOKEN || !CHAT_ID) {
    console.error("[telegram_notifier] Missing BOT_TOKEN or CHAT_ID");
    return false;
  }

  let safeText = text;
  if (safeText.length > 4000) {
    safeText = safeText.slice(0, 3950) + "\n... [обрезано]";
  }

  try {
    const res = await axios.post(
      TELEGRAM_API_URL,
      {
        chat_id: CHAT_ID,
        text: safeText,
        parse_mode: parseMode,
        disable_web_page_preview: true,
      },
      { timeout: 15000 }
    );
    return res.status === 200;
  } catch (err) {
    console.error(`[telegram_notifier] Error sending message: ${err.message || err}`);
    return false;
  }
}

/**
 * Send failure alert to Telegram.
 */
async function sendTelegramAlert(serviceName, errorMessage, details = null) {
  const now = new Date();
  const dateStr = now.toLocaleDateString("ru-RU", { timeZone: "Europe/Samara" });
  const timeStr = now.toLocaleTimeString("ru-RU", { timeZone: "Europe/Samara", hour12: false });
  const lines = [
    `🚨 <b>Сбой синхронизации: ${serviceName}</b>`,
    `📅 <b>Дата ошибки:</b> <code>${dateStr}</code>`,
    `⏰ <b>Время ошибки:</b> <code>${timeStr}</code>`,
    `❌ <b>Ошибка:</b> <code>${errorMessage}</code>`,
  ];

  if (details) {
    let detailsStr = typeof details === "string" ? details : JSON.stringify(details, null, 2);
    if (detailsStr.length > 1500) {
      detailsStr = detailsStr.slice(-1500);
    }
    lines.push(`\n<b>Детали:</b>\n<pre>${detailsStr}</pre>`);
  }

  return sendTelegramMessage(lines.join("\n"), "HTML");
}

/**
 * Record FBS broadcast numbers and calculate comparison vs previous day.
 */
function recordAndCompareFbsStats(
  historyKey,
  totalSku,
  activeSku,
  marketplaceSku = null,
  marketplacePieces = null
) {
  if (!fs.existsSync(LOGS_DIR)) {
    fs.mkdirSync(LOGS_DIR, { recursive: true });
  }

  const safeKey = String(historyKey || "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9а-яё]/gi, "_");
  const historyFile = path.join(LOGS_DIR, `fbs_history_${safeKey}.json`);

  let history = [];
  if (fs.existsSync(historyFile)) {
    try {
      history = JSON.parse(fs.readFileSync(historyFile, "utf8"));
      if (!Array.isArray(history)) history = [];
    } catch (e) {
      history = [];
    }
  }

  const now = new Date();
  const todayStr = now.toISOString().slice(0, 10); // YYYY-MM-DD

  // Find most recent entry from a PREVIOUS calendar day
  let prevDayEntry = null;
  for (let i = history.length - 1; i >= 0; i--) {
    const entry = history[i];
    if (entry && entry.date && entry.date < todayStr) {
      prevDayEntry = entry;
      break;
    }
  }

  // If no entry from previous day, look for any earlier entry
  if (!prevDayEntry && history.length > 0) {
    prevDayEntry = history[history.length - 1];
  }

  // Append current run
  history.push({
    date: todayStr,
    timestamp: now.toISOString(),
    total: totalSku,
    active: activeSku,
    marketplaceSku,
    marketplacePieces,
  });

  // Keep last 60 entries
  if (history.length > 60) {
    history = history.slice(-60);
  }

  try {
    fs.writeFileSync(historyFile, JSON.stringify(history, null, 2), "utf8");
  } catch (err) {
    console.error(`[telegram_notifier] Failed to save history: ${err.message}`);
  }

  let growthText = "Прирост: <i>(первый запуск, накапливаем статистику)</i>";
  if (prevDayEntry && typeof prevDayEntry.active === "number") {
    // Compare marketplaceSku if present on both, otherwise activeSku
    const useMarketplace =
      marketplaceSku !== null &&
      marketplaceSku !== undefined &&
      typeof prevDayEntry.marketplaceSku === "number";
    const currentVal = useMarketplace ? marketplaceSku : activeSku;
    const prevVal = useMarketplace ? prevDayEntry.marketplaceSku : prevDayEntry.active;

    const delta = currentVal - prevVal;
    const sign = delta >= 0 ? "+" : "";
    const pct = prevVal > 0 ? (delta / prevVal) * 100 : 0;
    const pctSign = pct >= 0 ? "+" : "";
    const dateLabel = prevDayEntry.date < todayStr ? "днем ранее" : "прошлый запуск";
    growthText = `Прирост: <b>${pctSign}${pct.toFixed(1)}%</b> (${sign}${delta.toLocaleString("ru-RU")} SKU ${dateLabel})`;
  }

  return {
    growthText,
    prevActive: prevDayEntry ? prevDayEntry.active : null,
  };
}

/**
 * Send completed FBS warehouse broadcast report for a single warehouse & marketplace.
 */
async function sendFbsWarehouseReport({
  marketplace = "Ozon",
  warehouseName = "Склад",
  totalSku = 0,
  activeSku = 0,
  marketplaceStockSku = null,
  marketplaceTotalPieces = null,
  durationSec = null,
  historyKey = null,
}) {
  return queueFbsBroadcastReport({
    marketplace,
    warehouseName,
    totalSku,
    activeSku,
    marketplaceStockSku,
    marketplaceTotalPieces,
    durationSec,
    historyKey,
  });
}

/**
 * Send multi-warehouse summary report (for suppliers with multiple warehouses like Feron).
 */
async function sendFbsMultiWarehouseReport({
  supplier = "Ферон",
  marketplace = "Ozon",
  totalSku = 0,
  warehouses = [],
  durationSec = null,
}) {
  const results = [];
  for (const wh of warehouses) {
    results.push(await queueFbsBroadcastReport({
      supplier,
      marketplace,
      warehouseName: wh.warehouseName || wh.name || "Склад",
      totalSku,
      activeSku: wh.activeSku,
      marketplaceStockSku: wh.marketplaceStockSku,
      marketplaceTotalPieces: wh.marketplaceTotalPieces,
      durationSec,
    }));
  }
  return results.every(Boolean);
}

/** Store completed broadcasts until the next scheduled Telegram digest. */
function queueFbsBroadcastReport(report) {
  if (!fs.existsSync(LOGS_DIR)) fs.mkdirSync(LOGS_DIR, { recursive: true });

  let queue = [];
  try {
    queue = JSON.parse(fs.readFileSync(FBS_REPORT_QUEUE_FILE, "utf8"));
    if (!Array.isArray(queue)) queue = [];
  } catch (err) {
    if (err.code !== "ENOENT") {
      console.error(`[telegram_notifier] Failed to read FBS report queue: ${err.message}`);
    }
  }

  queue.push({ ...report, completedAt: new Date().toISOString() });
  try {
    fs.writeFileSync(FBS_REPORT_QUEUE_FILE, JSON.stringify(queue.slice(-500), null, 2), "utf8");
    return true;
  } catch (err) {
    console.error(`[telegram_notifier] Failed to queue FBS report: ${err.message}`);
    return false;
  }
}

function formatFbsBroadcastDigest(reports) {
  const lines = ["📦 <b>Сводка трансляций остатков</b>"];
  for (const report of reports) {
    const completedAt = new Date(report.completedAt);
    const date = completedAt.toLocaleDateString("ru-RU", { timeZone: "Europe/Samara" });
    const time = completedAt.toLocaleTimeString("ru-RU", { timeZone: "Europe/Samara", hour12: false });
    const total = Number(report.totalSku || 0).toLocaleString("ru-RU");
    const active = Number(report.activeSku || 0).toLocaleString("ru-RU");
    const supplier = report.supplier ? `, ${report.supplier}` : "";

    lines.push("", `🏪 <b>${report.marketplace}${supplier} — ${report.warehouseName}</b>`);
    lines.push(`⏰ Трансляция завершена: <code>${date} ${time}</code>`);
    lines.push(`Транслировалось: <b>${active}</b> из <b>${total}</b> SKU`);
    if (report.marketplaceStockSku !== null && report.marketplaceStockSku !== undefined) {
      const stockSku = Number(report.marketplaceStockSku).toLocaleString("ru-RU");
      const pieces = Number(report.marketplaceTotalPieces || 0).toLocaleString("ru-RU");
      lines.push(report.marketplaceTotalPieces > 0
        ? `Остатки ${report.marketplace}: <b>${stockSku}</b> SKU, <b>${pieces}</b> шт.`
        : `Остатки ${report.marketplace}: <b>${stockSku}</b> SKU`);
    }
  }
  return lines.join("\n");
}

/** Send and clear all successful broadcast reports accumulated since the last digest. */
async function sendQueuedFbsBroadcastSummary() {
  let reports = [];
  try {
    reports = JSON.parse(fs.readFileSync(FBS_REPORT_QUEUE_FILE, "utf8"));
    if (!Array.isArray(reports)) reports = [];
  } catch (err) {
    if (err.code !== "ENOENT") throw err;
  }
  if (!reports.length) return false;

  const sent = await sendTelegramMessage(formatFbsBroadcastDigest(reports), "HTML");
  if (sent) fs.unlinkSync(FBS_REPORT_QUEUE_FILE);
  return sent;
}

/**
 * Backwards-compatible sendFbsBroadcastReport.
 */
async function sendFbsBroadcastReport(options) {
  if (options.warehouseName) {
    return sendFbsWarehouseReport(options);
  }
  if (Array.isArray(options.warehouses) && options.warehouses.length > 0) {
    return sendFbsMultiWarehouseReport(options);
  }
  return sendFbsWarehouseReport({
    marketplace: options.supplier || "ФБС",
    warehouseName: options.supplier || "ФБС",
    totalSku: options.totalSku,
    activeSku: options.activeSku,
    durationSec: options.durationSec,
  });
}

module.exports = {
  sendTelegramMessage,
  sendTelegramAlert,
  sendFbsWarehouseReport,
  sendFbsMultiWarehouseReport,
  sendFbsBroadcastReport,
  recordAndCompareFbsStats,
  queueFbsBroadcastReport,
  formatFbsBroadcastDigest,
  sendQueuedFbsBroadcastSummary,
};
