/**
 * Telegram notification and FBS broadcast metrics module for Node.js scripts.
 */

const axios = require("axios");
const fs = require("fs");
const path = require("path");

const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || "8795048754:AAHXbXFhzTHa6ICvwyQ1sE2pBvb-ZgqZIac";
const CHAT_ID = process.env.TELEGRAM_CHAT_ID || "-5299125247";
const TELEGRAM_API_URL = `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`;
const LOGS_DIR = path.join(__dirname, "logs");

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
  const durationText = durationSec
    ? `${Math.floor(durationSec / 60)} мин ${durationSec % 60} сек`
    : "";

  const now = new Date();
  const dateStr = now.toLocaleDateString("ru-RU", { timeZone: "Europe/Samara" });
  const timeStr = now.toLocaleTimeString("ru-RU", { timeZone: "Europe/Samara", hour12: false });

  const key = historyKey || `${marketplace}_${warehouseName}`;
  const { growthText } = recordAndCompareFbsStats(
    key,
    totalSku,
    activeSku,
    marketplaceStockSku,
    marketplaceTotalPieces
  );

  const formattedTotal = Number(totalSku).toLocaleString("ru-RU");
  const formattedActive = Number(activeSku).toLocaleString("ru-RU");

  const header = durationText
    ? `📦 <b>Трансляция ${marketplace} (склад «${warehouseName}») завершена</b> (${durationText})`
    : `📦 <b>Трансляция ${marketplace} (склад «${warehouseName}») завершена</b>`;

  const lines = [
    header,
    `📅 <b>Дата:</b> <code>${dateStr}</code>`,
    `⏰ <b>Время окончания трансляции:</b> <code>${timeStr}</code>`,
    `Всего в трансляции: <b>${formattedTotal}</b> SKU`,
    `Транслируем: <b>${formattedActive}</b> SKU`,
  ];

  if (marketplaceStockSku !== null && marketplaceStockSku !== undefined) {
    const formattedMarketplaceSku = Number(marketplaceStockSku).toLocaleString("ru-RU");
    if (marketplaceTotalPieces !== null && marketplaceTotalPieces !== undefined && marketplaceTotalPieces > 0) {
      const formattedPieces = Number(marketplaceTotalPieces).toLocaleString("ru-RU");
      lines.push(
        `Сейчас на остатках ${marketplace}: <b>${formattedMarketplaceSku}</b> SKU (${formattedPieces} шт.)`
      );
    } else {
      lines.push(
        `Сейчас на остатках ${marketplace}: <b>${formattedMarketplaceSku}</b> SKU`
      );
    }
  }

  lines.push(growthText);

  return sendTelegramMessage(lines.join("\n"), "HTML");
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
  const durationText = durationSec
    ? `${Math.floor(durationSec / 60)} мин ${durationSec % 60} сек`
    : "";

  const now = new Date();
  const dateStr = now.toLocaleDateString("ru-RU", { timeZone: "Europe/Samara" });
  const timeStr = now.toLocaleTimeString("ru-RU", { timeZone: "Europe/Samara", hour12: false });

  const formattedTotal = Number(totalSku).toLocaleString("ru-RU");

  const header = durationText
    ? `📦 <b>Трансляция ${marketplace} (${supplier}) завершена</b> (${durationText})`
    : `📦 <b>Трансляция ${marketplace} (${supplier}) завершена</b>`;

  const lines = [
    header,
    `📅 <b>Дата:</b> <code>${dateStr}</code>`,
    `⏰ <b>Время окончания трансляции:</b> <code>${timeStr}</code>`,
    `Всего в таблице: <b>${formattedTotal}</b> SKU`,
    "",
    `🏪 <b>Склады ${marketplace}:</b>`,
  ];

  for (const wh of warehouses) {
    const name = wh.warehouseName || wh.name || "Склад";
    const active = Number(wh.activeSku || 0).toLocaleString("ru-RU");
    let whLine = `• <b>${name}:</b> транслируем <b>${active}</b> SKU`;
    if (wh.marketplaceStockSku !== null && wh.marketplaceStockSku !== undefined) {
      const mktSku = Number(wh.marketplaceStockSku).toLocaleString("ru-RU");
      if (wh.marketplaceTotalPieces !== null && wh.marketplaceTotalPieces !== undefined && wh.marketplaceTotalPieces > 0) {
        const mktPieces = Number(wh.marketplaceTotalPieces).toLocaleString("ru-RU");
        whLine += ` | остаток: <b>${mktSku}</b> SKU (${mktPieces} шт.)`;
      } else {
        whLine += ` | остаток: <b>${mktSku}</b> SKU`;
      }
    }
    lines.push(whLine);
  }

  return sendTelegramMessage(lines.join("\n"), "HTML");
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
};
