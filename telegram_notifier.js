/** Telegram alerts and a concurrency-safe FBS broadcast spool. */
const axios = require("axios");
const fs = require("fs");
const path = require("path");

const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || "8657497257:AAFH9Sb6hNrKFL3WpDTuQd01FQbNB_I1-_o";
const CHAT_ID = process.env.TELEGRAM_CHAT_ID || "-1004398203333";
const TELEGRAM_API_URL = `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`;
const LOGS_DIR = process.env.TELEGRAM_NOTIFIER_LOGS_DIR || path.join(__dirname, "logs");
// Existing installations may still have this file. It is migrated on first use.
const FBS_REPORT_QUEUE_FILE = process.env.FBS_REPORT_QUEUE_FILE || path.join(LOGS_DIR, "fbs_broadcast_report_queue.json");
const FBS_REPORT_SPOOL_DIR = process.env.FBS_REPORT_SPOOL_DIR || path.join(LOGS_DIR, "fbs_broadcast_report_queue");
const TELEGRAM_MESSAGE_LIMIT = 4096;
const TELEGRAM_SAFE_MESSAGE_LENGTH = 3900;

function escapeTelegramHtml(value) {
  return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function plainTelegramText(value) {
  return String(value ?? "").replace(/<[^>]*>/g, "").replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
}
function truncate(value, max) {
  const text = String(value ?? "");
  return text.length > max ? `${text.slice(0, Math.max(0, max - 1))}…` : text;
}
function redact(value) {
  return String(value ?? "").split(BOT_TOKEN).join("[redacted]")
    .replace(/bot\d{5,}:[A-Za-z0-9_-]+/gi, "bot[redacted]")
    .replace(/\d{5,}:[A-Za-z0-9_-]{10,}/g, "[redacted]");
}
function logTelegramResponse(prefix, status, data, error) {
  const description = data && typeof data === "object" && data.description ? truncate(redact(data.description), 300) : "";
  const message = error ? truncate(redact(error.message || error.code || error), 300) : "";
  const fields = [`[telegram_notifier] ${prefix}`, `status=${status || "network"}`];
  if (description) fields.push(`description=${description}`);
  if (message) fields.push(`error=${message}`);
  console.error(fields.join(" "));
}
function isRetryable(status, error) {
  if (status === 429 || (status >= 500 && status <= 599)) return true;
  if (status) return false; // Explicitly includes 401: do not retry bad credentials.
  const code = String((error && error.code) || "");
  const message = String((error && error.message) || "");
  return /^(ECONNABORTED|ETIMEDOUT|ESOCKETTIMEDOUT|ECONNRESET|EPIPE)$/i.test(code)
    || /(timeout|timed out|tls|ssl|certificate|socket hang up)/i.test(`${code} ${message}`);
}
function retryAfterMs(headers, fallback) {
  const raw = headers && (headers["retry-after"] || headers["Retry-After"]);
  if (!raw) return fallback;
  const seconds = Number(raw);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds * 1000, 60000);
  const date = Date.parse(raw);
  return Number.isFinite(date) ? Math.min(Math.max(0, date - Date.now()), 60000) : fallback;
}
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Sends a message with bounded retries for TLS/timeouts, 429 and 5xx.
 * options exists to make retry tests deterministic; callers need not supply it.
 */
async function sendTelegramMessage(text, parseMode = "HTML", options = {}) {
  if (!BOT_TOKEN || !CHAT_ID) {
    console.error("[telegram_notifier] Missing BOT_TOKEN or CHAT_ID");
    return false;
  }
  let safeText = String(text ?? "");
  if (safeText.length > TELEGRAM_SAFE_MESSAGE_LENGTH) safeText = `${safeText.slice(0, TELEGRAM_SAFE_MESSAGE_LENGTH - 16)}\n... [обрезано]`;
  let body = safeText;
  let mode = parseMode;
  let fallbackUsed = false;
  const maxAttempts = Math.max(1, Number.isInteger(options.maxAttempts) ? options.maxAttempts : 4);
  const retryDelayMs = Number.isFinite(options.retryDelayMs) ? options.retryDelayMs : 600;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    let response;
    let error;
    try {
      const payload = { chat_id: CHAT_ID, text: body, disable_web_page_preview: true };
      if (mode) payload.parse_mode = mode;
      response = await axios.post(TELEGRAM_API_URL, payload, { timeout: 15000 });
    } catch (caught) {
      error = caught;
      response = caught && caught.response;
    }
    const status = response && response.status;
    const data = response && response.data;
    if (!error && status >= 200 && status < 300) {
      logTelegramResponse("response", status, data);
      return true;
    }
    // Telegram returns 400 for invalid HTML. Preserve the alert as plaintext.
    if (status === 400 && mode === "HTML" && !fallbackUsed) {
      logTelegramResponse("HTML rejected; retrying as plain text", status, data, error);
      body = plainTelegramText(safeText);
      mode = null;
      fallbackUsed = true;
      continue;
    }
    if (isRetryable(status, error) && attempt < maxAttempts) {
      const fallbackDelay = retryDelayMs * (2 ** (attempt - 1));
      const delay = status === 429 ? retryAfterMs(response && response.headers, fallbackDelay) : fallbackDelay;
      logTelegramResponse(`retry ${attempt}/${maxAttempts} in ${delay}ms`, status, data, error);
      await wait(delay);
      continue;
    }
    logTelegramResponse("send failed", status, data, error);
    return false;
  }
  return false;
}

async function sendTelegramAlert(serviceName, errorMessage, details = null) {
  const now = new Date();
  const date = now.toLocaleDateString("ru-RU", { timeZone: "Europe/Samara" });
  const time = now.toLocaleTimeString("ru-RU", { timeZone: "Europe/Samara", hour12: false });
  const lines = [
    `🚨 <b>Сбой синхронизации: ${escapeTelegramHtml(serviceName)}</b>`,
    `📅 <b>Дата ошибки:</b> <code>${escapeTelegramHtml(date)}</code>`,
    `⏰ <b>Время ошибки:</b> <code>${escapeTelegramHtml(time)}</code>`,
    `❌ <b>Ошибка:</b> <code>${escapeTelegramHtml(errorMessage)}</code>`,
  ];
  if (details) {
    const detailText = typeof details === "string" ? details : JSON.stringify(details, null, 2);
    lines.push(`\n<b>Детали:</b>\n<pre>${escapeTelegramHtml(truncate(detailText, 1500))}</pre>`);
  }
  return sendTelegramMessage(lines.join("\n"), "HTML");
}

function recordAndCompareFbsStats(historyKey, totalSku, activeSku, marketplaceSku = null, marketplacePieces = null) {
  fs.mkdirSync(LOGS_DIR, { recursive: true });
  const key = String(historyKey || "unknown").toLowerCase().replace(/[^a-z0-9а-яё]/gi, "_");
  const historyFile = path.join(LOGS_DIR, `fbs_history_${key}.json`);
  let history = [];
  try { history = JSON.parse(fs.readFileSync(historyFile, "utf8")); if (!Array.isArray(history)) history = []; } catch (_) {}
  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  let previous = null;
  for (let i = history.length - 1; i >= 0; i -= 1) if (history[i] && history[i].date < today) { previous = history[i]; break; }
  if (!previous && history.length) previous = history[history.length - 1];
  history.push({ date: today, timestamp: now.toISOString(), total: totalSku, active: activeSku, marketplaceSku, marketplacePieces });
  try { fs.writeFileSync(historyFile, JSON.stringify(history.slice(-60), null, 2), "utf8"); } catch (err) { console.error(`[telegram_notifier] Failed to save history: ${err.message}`); }
  if (!previous || typeof previous.active !== "number") return { growthText: "Прирост: <i>(первый запуск, накапливаем статистику)</i>", prevActive: null };
  const useMarketplace = marketplaceSku !== null && marketplaceSku !== undefined && typeof previous.marketplaceSku === "number";
  const current = useMarketplace ? marketplaceSku : activeSku;
  const before = useMarketplace ? previous.marketplaceSku : previous.active;
  const delta = current - before;
  const pct = before > 0 ? (delta / before) * 100 : 0;
  return { growthText: `Прирост: <b>${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%</b> (${delta >= 0 ? "+" : ""}${delta.toLocaleString("ru-RU")} SKU ${previous.date < today ? "днем ранее" : "прошлый запуск"})`, prevActive: previous.active };
}

function ensureSpool() { fs.mkdirSync(LOGS_DIR, { recursive: true }); fs.mkdirSync(FBS_REPORT_SPOOL_DIR, { recursive: true }); }
function uniquePart() { return `${Date.now()}-${process.pid}-${Math.random().toString(16).slice(2)}`; }
function writeSpoolReport(report) {
  ensureSpool();
  const file = path.join(FBS_REPORT_SPOOL_DIR, `${uniquePart()}.json`);
  const temporary = `${file}.tmp`;
  fs.writeFileSync(temporary, JSON.stringify(report), { encoding: "utf8", mode: 0o600 });
  fs.renameSync(temporary, file); // publish atomically: no reader observes partial JSON
}
function migrateLegacyFbsQueue() {
  ensureSpool();
  const lock = `${FBS_REPORT_QUEUE_FILE}.migration.lock`;
  let fd;
  try { fd = fs.openSync(lock, "wx", 0o600); } catch (err) { if (err.code !== "EEXIST") console.error(`[telegram_notifier] Cannot lock legacy FBS queue: ${err.message}`); return; }
  const moved = `${FBS_REPORT_QUEUE_FILE}.migrating-${uniquePart()}`;
  try {
    try { fs.renameSync(FBS_REPORT_QUEUE_FILE, moved); } catch (err) { if (err.code === "ENOENT") return; throw err; }
    const reports = JSON.parse(fs.readFileSync(moved, "utf8"));
    if (!Array.isArray(reports)) throw new Error("legacy queue is not an array");
    for (const report of reports) writeSpoolReport(report);
    fs.unlinkSync(moved);
    console.error(`[telegram_notifier] Migrated ${reports.length} legacy FBS report(s) to spool queue`);
  } catch (err) {
    console.error(`[telegram_notifier] Failed to migrate legacy FBS queue: ${err.message}`);
    try { if (fs.existsSync(moved) && !fs.existsSync(FBS_REPORT_QUEUE_FILE)) fs.renameSync(moved, FBS_REPORT_QUEUE_FILE); } catch (_) {}
  } finally {
    if (fd !== undefined) fs.closeSync(fd);
    try { fs.unlinkSync(lock); } catch (_) {}
  }
}
function queueFbsBroadcastReport(report) {
  try { migrateLegacyFbsQueue(); writeSpoolReport({ ...report, completedAt: new Date().toISOString() }); return true; }
  catch (err) { console.error(`[telegram_notifier] Failed to queue FBS report: ${err.message}`); return false; }
}

async function sendFbsWarehouseReport({ marketplace = "Ozon", warehouseName = "Склад", totalSku = 0, activeSku = 0, marketplaceStockSku = null, marketplaceTotalPieces = null, durationSec = null, historyKey = null }) {
  return queueFbsBroadcastReport({ marketplace, warehouseName, totalSku, activeSku, marketplaceStockSku, marketplaceTotalPieces, durationSec, historyKey });
}
async function sendFbsMultiWarehouseReport({ supplier = "Ферон", marketplace = "Ozon", totalSku = 0, warehouses = [], durationSec = null }) {
  const result = [];
  for (const warehouse of warehouses) result.push(queueFbsBroadcastReport({ supplier, marketplace, warehouseName: warehouse.warehouseName || warehouse.name || "Склад", totalSku, activeSku: warehouse.activeSku, marketplaceStockSku: warehouse.marketplaceStockSku, marketplaceTotalPieces: warehouse.marketplaceTotalPieces, durationSec }));
  return result.every(Boolean);
}
function formatFbsReportBlock(report) {
  const completed = new Date(report.completedAt);
  const valid = !Number.isNaN(completed.getTime());
  const date = valid ? completed.toLocaleDateString("ru-RU", { timeZone: "Europe/Samara" }) : "—";
  const time = valid ? completed.toLocaleTimeString("ru-RU", { timeZone: "Europe/Samara", hour12: false }) : "—";
  const market = escapeTelegramHtml(truncate(report.marketplace || "Маркетплейс", 400));
  const supplier = report.supplier ? `, ${escapeTelegramHtml(truncate(report.supplier, 400))}` : "";
  const warehouse = escapeTelegramHtml(truncate(report.warehouseName || "Склад", 1000));
  const lines = [`🏪 <b>${market}${supplier} — ${warehouse}</b>`, `⏰ Трансляция завершена: <code>${date} ${time}</code>`, `Транслировалось: <b>${Number(report.activeSku || 0).toLocaleString("ru-RU")}</b> из <b>${Number(report.totalSku || 0).toLocaleString("ru-RU")}</b> SKU`];
  if (report.marketplaceStockSku !== null && report.marketplaceStockSku !== undefined) {
    const stock = Number(report.marketplaceStockSku || 0).toLocaleString("ru-RU");
    const pieces = Number(report.marketplaceTotalPieces || 0).toLocaleString("ru-RU");
    lines.push(Number(report.marketplaceTotalPieces || 0) > 0 ? `Остатки ${market}: <b>${stock}</b> SKU, <b>${pieces}</b> шт.` : `Остатки ${market}: <b>${stock}</b> SKU`);
  }
  return lines.join("\n");
}
function formatFbsBroadcastDigestChunks(reports, maxLength = TELEGRAM_SAFE_MESSAGE_LENGTH) {
  const limit = Math.min(TELEGRAM_MESSAGE_LIMIT - 1, Math.max(200, maxLength));
  const header = "📦 <b>Сводка трансляций остатков</b>";
  const chunks = [];
  let text = header, entries = [];
  for (const report of reports) {
    let block = formatFbsReportBlock(report);
    const available = limit - header.length - 2;
    if (block.length > available) block = `${block.slice(0, available - 1)}…`;
    if (entries.length && `${text}\n\n${block}`.length > limit) { chunks.push({ text, reports: entries }); text = `${header}\n\n${block}`; entries = [report]; }
    else { text = `${text}\n\n${block}`; entries.push(report); }
  }
  if (entries.length) chunks.push({ text, reports: entries });
  return chunks;
}
function formatFbsBroadcastDigest(reports) { return formatFbsBroadcastDigestChunks(reports).map((chunk) => chunk.text).join("\n\n"); }
function claim(file) {
  const claimed = `${file}.claim-${process.pid}-${Math.random().toString(16).slice(2)}`;
  try { fs.renameSync(file, claimed); return claimed; } catch (err) { if (err.code === "ENOENT") return null; throw err; }
}
function releaseClaim(file) {
  try { fs.renameSync(file, file.replace(/\.claim-[^.]+$/, "")); } catch (err) { console.error(`[telegram_notifier] Failed to release FBS queue claim: ${err.message}`); }
}
async function sendQueuedFbsBroadcastSummary() {
  migrateLegacyFbsQueue();
  let names;
  try { names = fs.readdirSync(FBS_REPORT_SPOOL_DIR).filter((name) => name.endsWith(".json")).sort(); } catch (err) { if (err.code === "ENOENT") return false; throw err; }
  const reports = [];
  for (const name of names) {
    const claimed = claim(path.join(FBS_REPORT_SPOOL_DIR, name));
    if (!claimed) continue;
    try { reports.push({ ...JSON.parse(fs.readFileSync(claimed, "utf8")), __claimFile: claimed }); }
    catch (err) { console.error(`[telegram_notifier] Invalid FBS spool entry ${path.basename(claimed)}: ${err.message}`); releaseClaim(claimed); }
  }
  if (!reports.length) return false;
  const chunks = formatFbsBroadcastDigestChunks(reports);
  for (let index = 0; index < chunks.length; index += 1) {
    const chunk = chunks[index];
    if (!await sendTelegramMessage(chunk.text, "HTML")) {
      for (let remaining = index; remaining < chunks.length; remaining += 1) for (const report of chunks[remaining].reports) releaseClaim(report.__claimFile);
      return false;
    }
    for (const report of chunk.reports) try { fs.unlinkSync(report.__claimFile); } catch (err) { console.error(`[telegram_notifier] Sent FBS report could not be removed: ${err.message}`); }
  }
  return true;
}
async function sendFbsBroadcastReport(options) {
  if (options.warehouseName) return sendFbsWarehouseReport(options);
  if (Array.isArray(options.warehouses) && options.warehouses.length) return sendFbsMultiWarehouseReport(options);
  return sendFbsWarehouseReport({ marketplace: options.supplier || "ФБС", warehouseName: options.supplier || "ФБС", totalSku: options.totalSku, activeSku: options.activeSku, durationSec: options.durationSec });
}
module.exports = { TELEGRAM_MESSAGE_LIMIT, TELEGRAM_SAFE_MESSAGE_LENGTH, escapeTelegramHtml, sendTelegramMessage, sendTelegramAlert, sendFbsWarehouseReport, sendFbsMultiWarehouseReport, sendFbsBroadcastReport, recordAndCompareFbsStats, queueFbsBroadcastReport, formatFbsBroadcastDigest, formatFbsBroadcastDigestChunks, sendQueuedFbsBroadcastSummary };
