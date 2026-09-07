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
  const nowStr = new Date().toLocaleString("ru-RU", { timeZone: "Europe/Samara" });
  const lines = [
    `🚨 <b>Сбой синхронизации: ${serviceName}</b>`,
    `⏰ <b>Время:</b> <code>${nowStr}</code>`,
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
function recordAndCompareFbsStats(supplierName, totalSku, activeSku) {
  if (!fs.existsSync(LOGS_DIR)) {
    fs.mkdirSync(LOGS_DIR, { recursive: true });
  }

  const safeSupplier = supplierName.toLowerCase().replace(/[^a-z0-9а-яё]/gi, "_");
  const historyFile = path.join(LOGS_DIR, `fbs_history_${safeSupplier}.json`);

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
    const prevActive = prevDayEntry.active;
    const delta = activeSku - prevActive;
    const sign = delta >= 0 ? "+" : "";
    const pct = prevActive > 0 ? (delta / prevActive) * 100 : 0;
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
 * Send completed FBS broadcast summary report.
 */
async function sendFbsBroadcastReport({
  supplier = "ФБС",
  totalSku = 0,
  activeSku = 0,
  durationSec = null,
}) {
  const durationText = durationSec
    ? `${Math.floor(durationSec / 60)} мин ${durationSec % 60} сек`
    : "";

  const { growthText } = recordAndCompareFbsStats(supplier, totalSku, activeSku);

  const formattedTotal = Number(totalSku).toLocaleString("ru-RU");
  const formattedActive = Number(activeSku).toLocaleString("ru-RU");

  const header = durationText
    ? `📦 <b>Трансляция ФБС ${supplier} завершена</b> (${durationText})`
    : `📦 <b>Трансляция ФБС ${supplier} завершена</b>`;

  const lines = [
    header,
    `Всего в трансляции ФБС: <b>${formattedTotal}</b> SKU`,
    `Транслируем: <b>${formattedActive}</b> SKU`,
    growthText,
  ];

  return sendTelegramMessage(lines.join("\n"), "HTML");
}

module.exports = {
  sendTelegramMessage,
  sendTelegramAlert,
  sendFbsBroadcastReport,
  recordAndCompareFbsStats,
};
