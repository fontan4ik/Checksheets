import fs from "node:fs/promises";
import path from "node:path";
import vm from "node:vm";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const taskDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(taskDir, "../..");
const taskId = "666042e4-3b0d-4e69-a5e3-116486d11207";
const inputPath = "/Users/vladimirgrebennikov/Downloads/2026.09.28 Прайс-лист МЮ (1) (2).xlsx";
const outputDir = path.join(projectRoot, "outputs", taskId);
const outputPath = path.join(outputDir, "Прайс-лист МЮ - ссылки на фото.xlsx");
const eanInputPath = path.join(taskDir, "etm_eans.json");
const etmCachePath = path.join(taskDir, "etm_photo_cache.json");
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

const specs = [
  { name: "Общий прайс-лист", eanCol: "B", nameCol: "C" },
  { name: "Светодиодные лампы", eanCol: "E", nameCol: "F" },
  { name: "Светильники", eanCol: "E", nameCol: "F" },
  { name: "Лампы традиционных технологий", eanCol: "F", nameCol: "G" },
  { name: "Светильники с БАП", eanCol: "E", nameCol: "F" },
  { name: "Декоративный свет", eanCol: "E", nameCol: "F" },
];

function normalizeEan(value) {
  const digits = String(value ?? "").replace(/\D/g, "");
  return digits.replace(/^0+(?=\d)/, "");
}

function photoUrl(value, etm = false) {
  const valueText = String(value ?? "").trim();
  if (!valueText) return null;
  if (/^https?:\/\//i.test(valueText)) return valueText;
  if (valueText.startsWith("//")) return "https:" + valueText;
  if (etm && valueText.startsWith("/")) return "https://cdn.etm.ru" + valueText;
  return null;
}

function uniqueUrls(values, etm = false) {
  const seen = new Set();
  const out = [];
  for (const value of values) {
    const url = photoUrl(value, etm);
    if (url && !seen.has(url)) {
      seen.add(url);
      out.push(url);
    }
  }
  return out;
}

function addPhotos(map, eanValue, urls) {
  const ean = normalizeEan(eanValue);
  if (!ean) return;
  const merged = map.get(ean) || [];
  const seen = new Set(merged);
  for (const url of urls) {
    if (url && !seen.has(url)) {
      merged.push(url);
      seen.add(url);
    }
  }
  if (merged.length) map.set(ean, merged);
}

function columnNumber(letters) {
  let number = 0;
  for (const char of letters) number = number * 26 + char.charCodeAt(0) - 64;
  return number;
}

function columnLetters(number) {
  let result = "";
  while (number > 0) {
    const remainder = (number - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    number = Math.floor((number - 1) / 26);
  }
  return result;
}

function usedRangeEnd(address) {
  const match = String(address).match(/:([A-Z]+)(\d+)$/);
  if (!match) throw new Error("Could not resolve used range: " + address);
  return { col: match[1], row: Number(match[2]) };
}

function contentHash(sheet, address) {
  const range = sheet.getRange(address);
  const values = range.values;
  const formulas = range.formulas;
  const content = values.map((row, r) => row.map((value, c) => {
    const formula = formulas[r]?.[c];
    return formula ? ["formula", formula] : ["value", value];
  }));
  return createHash("sha256").update(JSON.stringify(content)).digest("hex");
}

function responseHeaders(rawHeaders) {
  const headers = {};
  for (const [key, value] of Object.entries(rawHeaders || {})) {
    headers[key] = value;
  }
  if (!Object.keys(headers).some(key => key.toLowerCase() === "content-type")) {
    headers["Content-Type"] = "application/json";
  }
  return headers;
}

async function postJson(url, headers, body, label) {
  const requestHeaders = responseHeaders(headers);
  for (let attempt = 0; attempt < 5; attempt++) {
    let response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: requestHeaders,
        body: JSON.stringify(body),
      });
    } catch (error) {
      if (attempt === 4) throw new Error(label + " network " + (error?.name || "error"));
      await sleep(Math.min(1000 * (2 ** attempt), 16000));
      continue;
    }
    const responseText = await response.text();
    let parsed;
    try {
      parsed = JSON.parse(responseText);
    } catch {
      parsed = null;
    }
    if (response.ok && parsed && typeof parsed === "object") return parsed;
    if ([408, 409, 429, 500, 502, 503, 504].includes(response.status) && attempt < 4) {
      const retryAfter = Number(response.headers.get("retry-after"));
      const delay = Number.isFinite(retryAfter) && retryAfter > 0
        ? retryAfter * 1000
        : Math.min(1000 * (2 ** attempt), 16000);
      await sleep(delay);
      continue;
    }
    throw new Error(label + " HTTP " + response.status);
  }
  throw new Error(label + " retries exhausted");
}

function valuesAsArray(value) {
  if (Array.isArray(value)) return value;
  if (value === null || value === undefined || value === "") return [];
  return [value];
}

function ozonImageUrls(product) {
  const candidates = [];
  candidates.push(...valuesAsArray(product.primary_image));
  candidates.push(...valuesAsArray(product.images));
  return uniqueUrls(candidates.map(value => {
    if (typeof value === "string") return value;
    if (value && typeof value === "object") return value.url || value.image_url || value.src || value.value;
    return null;
  }));
}

async function fetchOzon(headers) {
  const url = "https://api-seller.ozon.ru/v3/product/list";
  let cursor = "";
  const seenCursors = new Set();
  const products = new Map();
  let page = 0;
  for (;;) {
    const body = await postJson(url, headers, {
      filter: { visibility: "ALL" },
      last_id: cursor,
      limit: 1000,
    }, "Ozon product list");
    const result = body.result || {};
    const items = result.items;
    if (!Array.isArray(items)) throw new Error("Ozon product list has no items array");
    page++;
    for (const item of items) {
      const id = item.product_id ?? item.id;
      if (id !== null && id !== undefined && String(id) !== "") products.set(String(id), Number(id));
    }
    const next = String(result.last_id || "");
    if (!items.length || !next) break;
    if (next === cursor || seenCursors.has(next)) throw new Error("Ozon product list cursor repeated");
    seenCursors.add(next);
    cursor = next;
    if (page % 5 === 0) console.log("Ozon catalog: pages " + page + ", products " + products.size);
    await sleep(120);
  }

  const productIds = [...products.values()].filter(value => Number.isSafeInteger(value) && value > 0);
  const photosByEan = new Map();
  let detailsCount = 0;
  for (let offset = 0; offset < productIds.length; offset += 1000) {
    const batch = productIds.slice(offset, offset + 1000);
    const body = await postJson("https://api-seller.ozon.ru/v3/product/info/list", headers, {
      product_id: batch,
    }, "Ozon product details");
    const items = Array.isArray(body.items) ? body.items : body.result?.items;
    if (!Array.isArray(items)) throw new Error("Ozon product details has no items array");
    detailsCount += items.length;
    for (const product of items) {
      const eans = valuesAsArray(product.barcodes);
      const imageUrls = ozonImageUrls(product);
      for (const ean of eans) addPhotos(photosByEan, ean, imageUrls);
    }
    console.log("Ozon details: " + Math.min(offset + batch.length, productIds.length) + "/" + productIds.length);
    await sleep(180);
  }
  return { photosByEan, products: products.size, details: detailsCount };
}

async function fetchWildberries(headers) {
  const url = "https://content-api.wildberries.ru/content/v2/get/cards/list";
  const photosByEan = new Map();
  let cursor = null;
  let page = 0;
  let cardCount = 0;
  const seenCursors = new Set();
  for (;;) {
    const body = await postJson(url, headers, {
      settings: {
        sort: { ascending: true },
        cursor: { limit: 100, ...(cursor || {}) },
        filter: { withPhoto: -1 },
      },
    }, "WB card list");
    const cards = body.cards;
    if (!Array.isArray(cards)) throw new Error("WB card list has no cards array");
    page++;
    cardCount += cards.length;
    for (const card of cards) {
      const photoUrls = uniqueUrls(valuesAsArray(card.photos).map(photo => {
        if (typeof photo === "string") return photo;
        if (!photo || typeof photo !== "object") return null;
        return photo.big || photo.c516x688 || photo.c246x328 || photo.square || photo.tm;
      }));
      const barcodes = [];
      for (const size of valuesAsArray(card.sizes)) {
        if (size && Array.isArray(size.skus)) barcodes.push(...size.skus);
      }
      barcodes.push(...valuesAsArray(card.barcodes));
      for (const barcode of barcodes) addPhotos(photosByEan, barcode, photoUrls);
    }
    if (cards.length < 100) break;
    const next = body.cursor && {
      updatedAt: body.cursor.updatedAt,
      nmID: body.cursor.nmID,
    };
    if (!next?.updatedAt || !next?.nmID) throw new Error("WB cursor missing on a full page");
    const key = String(next.updatedAt) + ":" + String(next.nmID);
    if (seenCursors.has(key)) throw new Error("WB card list cursor repeated");
    seenCursors.add(key);
    cursor = next;
    if (page % 10 === 0) console.log("WB catalog: pages " + page + ", cards " + cardCount);
    await sleep(950);
  }
  return { photosByEan, cards: cardCount, pages: page };
}

function runEtmLookup(eans) {
  return new Promise((resolve, reject) => {
    const pythonCode = [
      "import json, logging, sys, time",
      "from pathlib import Path",
      "logging.disable(logging.CRITICAL)",
      "from resolve_etm_onboarding_codes import make_lookup",
      "source_path, cache_path = Path(sys.argv[1]), Path(sys.argv[2])",
      "codes = json.loads(source_path.read_text(encoding='utf-8'))",
      "cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}",
      "lookup = make_lookup()",
      "def save_cache():",
      "    temp = cache_path.with_suffix(cache_path.suffix + '.tmp')",
      "    temp.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')",
      "    temp.replace(cache_path)",
      "def url_value(value):",
      "    value = str(value or '').strip()",
      "    if value.startswith('https://') or value.startswith('http://'): return value",
      "    if value.startswith('//'): return 'https:' + value",
      "    if value.startswith('/'): return 'https://cdn.etm.ru' + value",
      "    return ''",
      "for index, raw_code in enumerate(codes, 1):",
      "    code = str(raw_code)",
      "    old = cache.get(code)",
      "    if isinstance(old, dict) and 'error' not in old: continue",
      "    try:",
      "        product = lookup(code)",
      "        photos = []",
      "        if isinstance(product, dict):",
      "            entries = product.get('gdsImages') or []",
      "            if isinstance(entries, list):",
      "                for entry in entries:",
      "                    if isinstance(entry, dict):",
      "                        value = url_value(entry.get('gdsImgRef') or entry.get('gdsImgSrc') or entry.get('url'))",
      "                        if value and value not in photos: photos.append(value)",
      "            if not photos:",
      "                value = url_value(product.get('gdsImage'))",
      "                if value: photos.append(value)",
      "        cache[code] = {'photos': photos, 'found': bool(product)}",
      "    except Exception as exc:",
      "        cache[code] = {'photos': [], 'error': type(exc).__name__}",
      "    if index % 20 == 0 or index == len(codes):",
      "        save_cache()",
      "        found = sum(1 for item in cache.values() if item.get('photos'))",
      "        errors = sum(1 for item in cache.values() if item.get('error'))",
      "        print('ETM photos: ' + str(index) + '/' + str(len(codes)) + ', matched ' + str(found) + ', errors ' + str(errors), flush=True)",
      "    if index < len(codes): time.sleep(1.05)",
      "save_cache()",
    ].join("\n");
    const child = spawn("python3", ["-c", pythonCode, eanInputPath, etmCachePath], {
      cwd: projectRoot,
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stdout.on("data", chunk => process.stdout.write(chunk.toString()));
    child.stderr.on("data", chunk => process.stderr.write(chunk.toString()));
    child.on("error", error => reject(new Error("ETM lookup process " + (error?.name || "error"))));
    child.on("close", code => {
      if (code === 0) resolve();
      else reject(new Error("ETM lookup process exited " + code));
    });
  });
}

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const sheetData = [];
const allEans = new Set();
const beforeHashes = new Map();

for (const spec of specs) {
  const sheet = workbook.worksheets.getItem(spec.name);
  if (!sheet) throw new Error("Missing worksheet: " + spec.name);
  const used = sheet.getUsedRange();
  const end = usedRangeEnd(used.address);
  const eanValues = sheet.getRange(spec.eanCol + "2:" + spec.eanCol + end.row).values.flat();
  let lastDataRow = 1;
  for (let i = 0; i < eanValues.length; i++) {
    const normalized = normalizeEan(eanValues[i]);
    if (normalized) {
      allEans.add(normalized);
      lastDataRow = i + 2;
    }
  }
  sheetData.push({ ...spec, usedAddress: used.address, usedEndCol: end.col, lastDataRow });
  beforeHashes.set(spec.name, contentHash(sheet, used.address));
}

const eans = [...allEans];
if (!eans.length) throw new Error("No product EANs found in the workbook");
await fs.mkdir(taskDir, { recursive: true });
await fs.writeFile(eanInputPath, JSON.stringify(eans), "utf8");
console.log("Workbook products: " + eans.length + " unique EANs across " + specs.length + " product sheets");

const sharedSettingsPath = path.join(projectRoot, "Shared_Настройки.js");
const sharedSettings = await fs.readFile(sharedSettingsPath, "utf8");
const context = vm.createContext({});
vm.runInContext(sharedSettings + "\nthis.photoHeaders={ozon:ozonHeaders(),wb:wbHeaders()};", context);
const sourcePromises = [
  fetchOzon(context.photoHeaders.ozon).then(result => {
    const matches = eans.filter(ean => result.photosByEan.has(ean)).length;
    console.log("Ozon catalog finished: " + result.products + " products, " + matches + " workbook EANs with photos");
    return result;
  }),
  fetchWildberries(context.photoHeaders.wb).then(result => {
    const matches = eans.filter(ean => result.photosByEan.has(ean)).length;
    console.log("WB catalog finished: " + result.cards + " cards, " + matches + " workbook EANs with photos");
    return result;
  }),
  runEtmLookup(eans).then(async () => {
    const cache = JSON.parse(await fs.readFile(etmCachePath, "utf8"));
    const photosByEan = new Map();
    for (const [ean, result] of Object.entries(cache)) {
      if (result?.photos?.length) photosByEan.set(normalizeEan(ean), uniqueUrls(result.photos, true));
    }
    console.log("ETM catalog finished: " + photosByEan.size + " barcode matches with photos");
    return { photosByEan, queries: Object.keys(cache).length };
  }),
];

const [ozonSettled, wbSettled, etmSettled] = await Promise.allSettled(sourcePromises);
const apiResults = { ozon: null, wb: null, etm: null };
for (const [name, result] of [["ozon", ozonSettled], ["wb", wbSettled], ["etm", etmSettled]]) {
  if (result.status === "fulfilled") apiResults[name] = result.value;
  else console.log(name.toUpperCase() + " source unavailable: " + (result.reason?.message || result.reason?.name || "error"));
}

const photosByEan = new Map();
const targetEans = new Set(eans);
for (const sourceName of ["etm", "ozon", "wb"]) {
  const source = apiResults[sourceName];
  if (!source) continue;
  for (const [ean, urls] of source.photosByEan) {
    if (targetEans.has(ean)) addPhotos(photosByEan, ean, urls);
  }
}

let maxPhotoCount = 0;
let uniquePhotoLinks = 0;
for (const urls of photosByEan.values()) {
  maxPhotoCount = Math.max(maxPhotoCount, urls.length);
  uniquePhotoLinks += urls.length;
}
const photoColumnCount = Math.max(1, maxPhotoCount);
console.log("Photo matches: " + photosByEan.size + "/" + eans.length + " EANs, " + uniquePhotoLinks + " unique URLs, maximum " + maxPhotoCount + " photos for one item");

const outputHeaders = Array.from({ length: photoColumnCount }, (_, index) => (index + 1) + " фото");
const placement = [];
for (const info of sheetData) {
  const sheet = workbook.worksheets.getItem(info.name);
  const usedEndNumber = columnNumber(info.usedEndCol);
  const startColIndex = usedEndNumber;
  const headerRange = sheet.getRangeByIndexes(0, startColIndex, 1, photoColumnCount);
  headerRange.copyFrom(sheet.getRange("A1"), "all");
  headerRange.values = [outputHeaders];
  headerRange.format.horizontalAlignment = "center";
  headerRange.format.verticalAlignment = "center";
  headerRange.format.wrapText = true;
  headerRange.format.columnWidth = 36;

  const rowCount = Math.max(0, info.lastDataRow - 1);
  if (rowCount) {
    const nameSource = sheet.getRangeByIndexes(1, columnNumber(info.nameCol) - 1, rowCount, 1);
    const eanColumn = sheet.getRange(info.eanCol + "2:" + info.eanCol + info.lastDataRow).values.flat();
    const formulas = Array.from({ length: rowCount }, () => Array(photoColumnCount).fill(""));
    let linkedRows = 0;
    for (let rowIndex = 0; rowIndex < rowCount; rowIndex++) {
      const urls = photosByEan.get(normalizeEan(eanColumn[rowIndex])) || [];
      if (urls.length) linkedRows++;
      for (let colIndex = 0; colIndex < Math.min(urls.length, photoColumnCount); colIndex++) {
        const escaped = urls[colIndex].replace(/"/g, '""');
        formulas[rowIndex][colIndex] = '=HYPERLINK("' + escaped + '","' + escaped + '")';
      }
    }
    for (let colIndex = 0; colIndex < photoColumnCount; colIndex++) {
      const bodyRange = sheet.getRangeByIndexes(1, startColIndex + colIndex, rowCount, 1);
      bodyRange.copyFrom(nameSource, "all");
      bodyRange.clear({ applyTo: "contents" });
      bodyRange.formulas = formulas.map(row => [row[colIndex]]);
      bodyRange.format.columnWidth = 36;
      bodyRange.format.numberFormat = "@";
      bodyRange.format.font.color = "#0563C1";
      bodyRange.format.horizontalAlignment = "left";
      bodyRange.format.verticalAlignment = "center";
      bodyRange.format.wrapText = false;
    }
    placement.push({
      sheet: info.name,
      firstColumn: columnLetters(startColIndex + 1),
      lastColumn: columnLetters(startColIndex + photoColumnCount),
      rows: rowCount,
      linkedRows,
    });
  } else {
    placement.push({
      sheet: info.name,
      firstColumn: columnLetters(startColIndex + 1),
      lastColumn: columnLetters(startColIndex + photoColumnCount),
      rows: 0,
      linkedRows: 0,
    });
  }
}

for (const info of sheetData) {
  const sheet = workbook.worksheets.getItem(info.name);
  const unchangedHash = contentHash(sheet, info.usedAddress);
  if (unchangedHash !== beforeHashes.get(info.name)) {
    throw new Error("Existing values or formulas changed outside the new photo columns: " + info.name);
  }
}

workbook.recalculate();
const verification = [];
const errorPattern = "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!";
for (const info of sheetData) {
  const placed = placement.find(item => item.sheet === info.name);
  const sheet = workbook.worksheets.getItem(info.name);
  const startCol = placed.firstColumn;
  const endCol = placed.lastColumn;
  const endRow = Math.max(1, info.lastDataRow);
  const photoRange = startCol + "1:" + endCol + endRow;
  const formulas = sheet.getRange(photoRange).formulas;
  const formulaCount = formulas.flat().filter(Boolean).length;
  const errors = await workbook.inspect({
    kind: "match",
    sheetId: info.name,
    range: photoRange,
    searchTerm: errorPattern,
    options: { useRegex: true, maxResults: 100 },
    summary: "new photo link cells",
  });
  const errorCount = errors.ndjson.split("\n").filter(line => line.includes("\"kind\":\"match\"")).length;
  verification.push({ sheet: info.name, photoRange, formulaCount, errorCount, linkedRows: placed.linkedRows });
}

const master = sheetData[0];
const masterPlacement = placement[0];
const masterSheet = workbook.worksheets.getItem(master.name);
const masterSampleRange = masterPlacement.firstColumn + "1:" + masterPlacement.lastColumn + "8";
const masterSample = await workbook.inspect({
  kind: "table",
  sheetId: master.name,
  range: masterSampleRange,
  include: "values,formulas",
  tableMaxRows: 8,
  tableMaxCols: 10,
  tableMaxCellChars: 110,
  maxChars: 4000,
});
console.log("Master sample:\n" + masterSample.ndjson);
console.log("Verification: " + JSON.stringify(verification));
console.log("Placement: " + JSON.stringify(placement));

const render = await workbook.render({
  sheetName: master.name,
  range: masterSampleRange,
  scale: 1.5,
  format: "png",
});
await fs.writeFile(path.join(taskDir, "photo_links_preview.png"), new Uint8Array(await render.arrayBuffer()));

await fs.mkdir(outputDir, { recursive: true });
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);

const saved = await SpreadsheetFile.importXlsx(await FileBlob.load(outputPath));
const savedMaster = saved.worksheets.getItem(master.name);
const savedHeaders = savedMaster.getRange(masterPlacement.firstColumn + "1:" + masterPlacement.lastColumn + "1").values[0];
const savedFormulas = savedMaster.getRange(masterPlacement.firstColumn + "2:" + masterPlacement.lastColumn + master.lastDataRow).formulas;
const savedLinkCount = savedFormulas.flat().filter(formula => String(formula || "").toUpperCase().includes("HYPERLINK(")).length;
if (savedHeaders.join("|") !== outputHeaders.join("|")) throw new Error("Saved workbook photo headers did not round-trip");
if (savedLinkCount === 0 && photosByEan.size > 0) throw new Error("Saved workbook lost HYPERLINK formulas");

const finalStats = {
  outputPath,
  masterProducts: eans.length,
  matchedProducts: photosByEan.size,
  maxPhotoColumns: photoColumnCount,
  uniquePhotoLinks,
  sources: {
    etm: apiResults.etm ? eans.filter(ean => apiResults.etm.photosByEan.has(ean)).length : 0,
    ozon: apiResults.ozon ? eans.filter(ean => apiResults.ozon.photosByEan.has(ean)).length : 0,
    wb: apiResults.wb ? eans.filter(ean => apiResults.wb.photosByEan.has(ean)).length : 0,
  },
  savedMasterHeaders: savedHeaders,
  savedSampleLinks: savedLinkCount,
  placement,
  verification,
};
console.log("FINAL_STATS " + JSON.stringify(finalStats));
