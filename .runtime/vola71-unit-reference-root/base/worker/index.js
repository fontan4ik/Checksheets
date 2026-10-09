import { resolveImportIdentities, resolveOfferId } from "./article-id.js";
import { parseArticleUpload, parseManualArticles } from "./articles.js";

const ARTICLES = [
  "KKME11-012-230-10",
  "KKME11-018-230-10",
  "KKME11-009-230-10",
  "KKME21-025-110-10",
  "KKME31-040-230-11",
];
const VERIFIED_KMIE_THREE_POLE_ARTICLES = new Set(ARTICLES);
const VERIFIED_KMIE_95A_ARTICLE = "KKME41-095-230-11";
const VERIFIED_KMIE_CONTACTOR_ARTICLES = new Set([...ARTICLES, VERIFIED_KMIE_95A_ARTICLE]);
const OZON_APPROVED = {
  descriptionCategoryId: 17028654,
  typeId: 99040,
  vat: "0.22",
  feacn: "8536490000",
  isMarked: true,
};
const OZON_LIVE_RECONCILIATION_BLOCKER = "Локальная проверка не выполняет live Ozon info/list/schema reconciliation; создание остаётся выключенным.";
const OZON_CREATE_DISABLED_BLOCKER = "Seller create/import is disabled unless OZON_SELLER_CREATE_ENABLED is exactly \"true\".";
const OZON_API_BASE = "https://api-seller.ozon.ru";
const OZON_PRODUCT_INFO_LIST = "/v3/product/info/list";
const OZON_PRODUCT_INFO_DESCRIPTION = "/v1/product/info/description";
const OZON_PRODUCT_INFO_ATTRIBUTES = "/v4/product/info/attributes";
const OZON_PRODUCT_PRICES = "/v5/product/info/prices";
const OZON_PRODUCT_PICTURES = "/v2/product/pictures/info";
const OZON_CATEGORY_ATTRIBUTES = "/v1/description-category/attribute";
const OZON_CATEGORY_ATTRIBUTE_VALUES = "/v1/description-category/attribute/values/search";
const VERIFIED_OZON_DICTIONARIES = { brand: 5643327, contactorType: 99040, poles3: 41843, ip20: 83627, currentTypeAc: 970749122, feacn: 971400163 };
const OZON_DICTIONARY_SEARCH_NAMES = { 85: "Generica", 8229: "Контактор", 10818: "3", 6980: "IP20", 10819: "Переменный", 22232: "8536490000" };
const OZON_PRODUCT_IMPORT = "/v3/product/import";
const OZON_PRODUCT_IMPORT_INFO = "/v1/product/import/info";
const OZON_PRODUCT_PICTURES_INFO = "/v2/product/pictures/info";
const OZON_PRODUCT_PICTURES_IMPORT = "/v1/product/pictures/import";
const OZON_SUPPORTED_LOCAL_ARTICLES = new Set(["KKME11-012-230-10", "KKME11-018-230-10", "KKME11-009-230-10", "KKME21-025-110-10", "KKME31-040-230-11", "KKME41-095-230-11"]);
const OZON_CONFIRMED_REQUIRED_ETIM = {
  coilVoltage: "EF003978",
  nominalCurrentA: "EF001392",
  ipRating: "EF005474",
  controlCurrentType: "EF008242",
};

const noStore = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };
const publicRead = { "Cache-Control": "public, max-age=30, stale-while-revalidate=60", "X-Content-Type-Options": "nosniff" };
const json = (body, status = 200) => Response.json(body, { status, headers: noStore });
const number = (value) => {
  if (value && typeof value === "object") value = value.value ?? value.individual;
  if (value === "" || value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const text = (value) => typeof value === "string" || typeof value === "number" ? String(value).trim() : "";

const OPERATOR_COOKIE = "__Host-iek_operator";
const OPERATOR_SESSION_SECONDS = 8 * 60 * 60;
const isOperatorTokenConfigured = (env) => typeof env.OZON_OPERATOR_TOKEN === "string" && env.OZON_OPERATOR_TOKEN.length >= 32;

function base64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}

function fromBase64Url(value) {
  const binary = atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4));
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function operatorPrincipal(env) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(env.OZON_OPERATOR_TOKEN)));
  return `site-operator:${[...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

async function signOperatorSession(env) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(env.OZON_OPERATOR_TOKEN), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const payload = base64Url(new TextEncoder().encode(JSON.stringify({ sub: await operatorPrincipal(env), exp: Math.floor(Date.now() / 1000) + OPERATOR_SESSION_SECONDS })));
  const signature = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(payload)));
  return `${payload}.${base64Url(signature)}`;
}

async function readOperatorSession(request, env) {
  if (!isOperatorTokenConfigured(env)) return null;
  const cookie = request.headers.get("cookie")?.split(";").map((part) => part.trim()).find((part) => part.startsWith(`${OPERATOR_COOKIE}=`));
  const value = cookie?.slice(OPERATOR_COOKIE.length + 1) || "";
  const [payload, signature, extra] = value.split(".");
  if (!payload || !signature || extra !== undefined) return null;
  try {
    const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(env.OZON_OPERATOR_TOKEN), { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
    if (!await crypto.subtle.verify("HMAC", key, fromBase64Url(signature), new TextEncoder().encode(payload))) return null;
    const claims = JSON.parse(new TextDecoder().decode(fromBase64Url(payload)));
    if (!Number.isInteger(claims.exp) || claims.exp <= Date.now() / 1000 || claims.sub !== await operatorPrincipal(env)) return null;
    return claims.sub;
  } catch { return null; }
}

function sameSecret(candidate, expected) {
  const a = new TextEncoder().encode(candidate);
  const b = new TextEncoder().encode(expected);
  let difference = a.length ^ b.length;
  for (let index = 0; index < 512; index += 1) difference |= (a[index] || 0) ^ (b[index] || 0);
  return difference === 0;
}

function parseRow(row) {
  return {
    article: row.article,
    listingArticle: row.listing_article,
    supplier: JSON.parse(row.supplier_json || "{}"),
    overrides: JSON.parse(row.overrides_json || "{}"),
    validation: JSON.parse(row.validation_json || "null"),
    updatedAt: row.updated_at,
  };
}

async function seed(db) {
  const now = new Date().toISOString();
  await db.batch(ARTICLES.map((article) => db.prepare("INSERT OR IGNORE INTO operator_records (article, listing_article, supplier_json, overrides_json, validation_json, updated_at) VALUES (?, ?, '{}', '{}', 'null', ?)").bind(article, `${article}-1`, now)));
}

async function getRecord(db, article) {
  const row = await db.prepare("SELECT * FROM operator_records WHERE article = ?").bind(article).first();
  return row ? parseRow(row) : null;
}

async function listRecords(db, { publicOnly = false } = {}) {
  const query = publicOnly
    ? "SELECT article, listing_article, supplier_json, updated_at FROM operator_records ORDER BY article"
    : "SELECT * FROM operator_records ORDER BY article";
  const result = await db.prepare(query).all();
  return (result.results || []).map((row) => {
    const record = parseRow(row);
    if (!publicOnly) return record;
    const { article, listingArticle, supplier, updatedAt } = record;
    return { article, listingArticle, supplier, updatedAt };
  });
}

async function recordEvent(db, article, eventType, detail) {
  await db.prepare("INSERT INTO operator_events (article, event_type, detail_json, created_at) VALUES (?, ?, ?, ?)")
    .bind(article, eventType, JSON.stringify(detail), new Date().toISOString()).run();
}

async function listEvents(db) {
  const result = await db.prepare("SELECT article, event_type, detail_json, created_at FROM operator_events ORDER BY id DESC LIMIT 12").all();
  return result.results || [];
}

function cookiesFrom(headers) {
  const all = typeof headers.getSetCookie === "function" ? headers.getSetCookie().join("; ") : (headers.get("set-cookie") || "");
  const pairs = [];
  for (const name of ["kc-access", "kc-state", "bp-access", "bp-state"]) {
    const match = all.match(new RegExp(`(?:^|[,; ]+)${name}=([^;,]+)`, "i"));
    if (match) pairs.push(`${name}=${match[1]}`);
  }
  const valid = pairs.some((pair) => pair.startsWith("kc-access=")) && pairs.some((pair) => pair.startsWith("kc-state="))
    || pairs.some((pair) => pair.startsWith("bp-access=")) && pairs.some((pair) => pair.startsWith("bp-state="));
  if (!valid) throw new Error("IEK login did not establish its documented session cookies");
  return pairs.join("; ");
}

async function supplierSession(apiKey, fetcher = fetch) {
  const login = await fetcher("https://bp.iek.ru/oauth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
    body: new URLSearchParams({ username: "ticket", password: apiKey }),
  });
  if (!login.ok) throw new Error(`IEK login returned HTTP ${login.status}`);
  return cookiesFrom(login.headers);
}

async function readSupplier(article, cookie, fetcher = fetch) {
  const response = await fetcher(`https://bp.iek.ru/api/catalog/v1/client/products/${encodeURIComponent(article)}`, {
    headers: { Accept: "application/json", Cookie: cookie },
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`IEK product ${article} returned HTTP ${response.status}`);
  const body = await response.json();
  const product = body?.product && typeof body.product === "object" ? body.product : body;
  if (text(product.article) !== article) throw new Error(`IEK response article did not exactly match ${article}`);
  return normalizeSupplier(product);
}

function logisticValue(product, names) {
  const expected = new Set(names.map((x) => x.toLocaleLowerCase("ru-RU")));
  for (const item of product.logisticParams || []) {
    if (!expected.has(text(item.nameOrig || item.name).toLocaleLowerCase("ru-RU"))) continue;
    const value = item.value;
    return value && typeof value === "object" ? value.individual ?? null : value ?? null;
  }
  return null;
}

function firstValue(...values) {
  return values.find((value) => value !== undefined && value !== null && value !== "") ?? null;
}

function etimFeatureValue(features, names) {
  const expected = new Set(names.map((name) => name.toLocaleLowerCase("ru-RU")));
  const feature = features.find((item) => expected.has(text(item.name || item.key || item.code).toLocaleLowerCase("ru-RU")));
  return feature ? firstValue(feature.value, feature.values) : null;
}

function etimFeatureById(features, id) {
  return features.find((feature) => text(feature.id).toUpperCase() === id) || null;
}

function sourceDecimal(value) {
  if (typeof value === "string") value = value.trim().replace(",", ".");
  if (typeof value === "string" && value.trim() === "") return null;
  return number(value);
}

function normalizedDimension(p, keys, aliases, etimNames, unitNames, fallbackValues = []) {
  for (const key of keys) {
    if (p[key] === undefined || p[key] === null || p[key] === "") continue;
    const value = sourceDecimal(p[key]);
    const declaredUnit = text(p[`${key}Unit`] || p[`${key}_unit`]).toLowerCase();
    const conventionalCmKey = /cm$/i.test(key) || /_cm$/i.test(key);
    if (declaredUnit === "cm" || conventionalCmKey) return value === null ? null : value * 10;
    if (["mm", "millimeter", "millimeters"].includes(declaredUnit)) return value;
    return value;
  }
  for (const item of p.logisticParams || []) {
    const sourceName = text(item.nameOrig || item.name);
    const normalizedSourceName = sourceName.toLocaleLowerCase("ru-RU").replaceAll("_cm", "_см");
    if (!aliases.some((alias) => normalizedSourceName === alias.toLocaleLowerCase("ru-RU"))) continue;
    const value = sourceDecimal(item.value && typeof item.value === "object" ? item.value.individual : item.value);
    const nestedIndividualUnit = text(item.value && typeof item.value === "object" ? item.value.unit : "");
    const unit = text(item.unit || nestedIndividualUnit || item.name || item.nameOrig);
    const inferredKg = /Вес|Масса|weight/i.test(sourceName) && /кг|kg/i.test(unit);
    if (value !== null && inferredKg) return value;
    const explicitCm = /см/i.test(sourceName) || /см/i.test(unit);
    const explicitMm = /мм/i.test(sourceName) || /мм/i.test(unit);
    if (value === null) return null;
    if (aliases.includes("gross_weight_kg") && /г|gram/i.test(text(item.unit))) return value;
    return explicitCm ? value * 10 : explicitMm ? value : null;
  }
  for (const fallback of fallbackValues) {
    if (fallback === null || fallback === undefined || fallback === "") continue;
    const value = sourceDecimal(fallback.value);
    if (value === null) continue;
    const sourceUnit = text(fallback.unit).toLowerCase();
    const cm = sourceUnit === "cm" || sourceUnit === "см";
    const mm = sourceUnit === "mm" || sourceUnit === "мм";
    const grams = sourceUnit === "g" || sourceUnit === "г";
    const kg = sourceUnit === "kg" || sourceUnit === "кг";
    return cm ? value * 10 : kg ? value * 1000 : value;
  }
  const feature = (Array.isArray(p.etim?.features) ? p.etim.features : []).find((entry) => etimNames.some((name) => text(entry.name).toLocaleLowerCase("ru-RU") === name.toLocaleLowerCase("ru-RU")));
  if (!feature) return null;
  const value = sourceDecimal(feature.value);
  const unit = text(feature.unit).toLowerCase();
  return value === null ? null : ["mm", "мм"].includes(unit) ? value : ["cm", "см"].includes(unit) ? value * 10 : null;
}

export function normalizeSupplier(p) {
  const images = [];
  for (const candidate of [p.imageUrls, p.imageUrl, p.images]) {
    for (const entry of Array.isArray(candidate) ? candidate : candidate ? [candidate] : []) {
      const url = text(typeof entry === "object" ? entry.url : entry);
      if (url && /^https:\/\//i.test(url) && !images.includes(url)) images.push(url);
    }
  }
  const etim = p.etim;
  const features = Array.isArray(etim) ? etim : etim?.features || etim?.characteristics || p.characteristics || [];
  const rows = (Array.isArray(features) ? features : []).filter((f) => f && (text(f.name || f.key) || text(f.value)));
  const pack = p.logisticParamsData?.singlePackage;
  const logistics = Array.isArray(p.logisticParams) ? p.logisticParams : [];
  const packageRow = logistics.find((item) => /individual|индивидуальн/i.test(text(item.nameOrig || item.name)));
  const packageData = pack || (packageRow?.value && typeof packageRow.value === "object" ? packageRow.value : null);
  const multiplicity = p.multiplicity ?? p.warehouseData?.find?.((w) => w?.multiplicity !== undefined)?.multiplicity ?? pack?.multiplicity ?? null;
  const get = (key, names) => number(p[key]) ?? number(logisticValue(p, names));
  const barcode = text(firstValue(p.barcode, p.gtin, p.ean, p.ean13, p.barcodeValue, p.gtin13,
    logisticValue(p, ["Штрихкод", "Штрихкод товара", "EAN", "EAN13", "GTIN", "GTIN-13", "barcode", "ean", "gtin"]),
    etimFeatureValue(rows, ["Штрихкод", "EAN", "EAN13", "GTIN", "GTIN-13"])));
  const dimension = (keys, aliases, etimNames, packageValues = [], unitKind = "mm") => normalizedDimension(
    p, keys, aliases, etimNames, [], packageValues.map((value) => ({ value, unit: unitKind }))
  );
  const article = text(p.article);
  const coilFeature = etimFeatureById(rows, "EF003978");
  const powerFeature = etimFeatureById(rows, "EF001364");
  const coilVoltage = sourceDecimal(firstValue(p.coilVoltage, coilFeature?.value));
  const ac3PowerKwAt400V = sourceDecimal(firstValue(p.ac3PowerKwAt400V, powerFeature?.value));
  return {
    article,
    shortName: text(p.shortName || p.nameRu || p.name),
    name: text(p.name || p.shortName || p.nameRu) || p.article,
    brand: text(p.tm || p.brand),
    description: text(p.description),
    barcode,
    photos: images,
    photoCount: images.length,
    etim: rows.map((f) => ({ id: text(f.id || f.etimId || f.code), name: text(f.name || f.key), value: f.value ?? f.values ?? null, unit: text(f.unit) })),
    etimCount: rows.length,
    multiplicity: number(multiplicity),
    priceRrc: number(p.priceRrc),
    sourceBrand: text(p.tm || p.brand),
    technical: {
      coilVoltage,
      coilVoltageEvidence: coilVoltage === null ? null : "IEK ETIM EF003978 (AC control-supply voltage, 50 Hz)",
      nominalCurrentA: sourceDecimal(etimFeatureById(rows, "EF001392")?.value),
      ipRating: text(etimFeatureById(rows, "EF005474")?.value) || null,
      controlCurrentType: text(etimFeatureById(rows, "EF008242")?.value) || null,
      ac3PowerKwAt400V,
      ac3PowerSourceFeature: powerFeature ? { id: powerFeature.id, name: powerFeature.name, value: powerFeature.value, unit: powerFeature.unit } : null,
      ac3PowerCondition: ac3PowerKwAt400V === null ? null : "AC-3, 400 V",
      catalogMainPoles: VERIFIED_KMIE_CONTACTOR_ARTICLES.has(article) ? 3 : null,
      auxiliaryContacts: null,
      sourceAnomalies: ["IEK power NO/NC ETIM values conflict with exact KMIE catalog; do not infer poles from auxiliary contacts"],
    },
    feacn: text(p.feacn || p.tnVed || p.tn_ved),
    isMarked: typeof p.isMarked === "boolean" ? p.isMarked : null,
    currency: text(p.currency || p.currencyCode),
    length: dimension(["lengthMm", "length_mm", "lengthCm", "length_cm", "length", "depth"], ["l_см", "length_cm", "Длина", "Длина упаковки", "Длина, мм"], ["Длина", "Длина упаковки"], packageData ? [packageData.lengthMm, packageData.length_mm, packageData.length, packageData.depth] : []),
    width: dimension(["widthMm", "width_mm", "widthCm", "width_cm", "width"], ["b_см", "width_cm", "Ширина", "Ширина упаковки", "Ширина, мм"], ["Ширина", "Ширина упаковки"], packageData ? [packageData.widthMm, packageData.width_mm, packageData.width] : []),
    height: dimension(["heightMm", "height_mm", "heightCm", "height_cm", "height"], ["h_см", "height_cm", "Высота", "Высота упаковки", "Высота, мм"], ["Высота", "Высота упаковки"], packageData ? [packageData.heightMm, packageData.height_mm, packageData.height] : []),
    weight: dimension(["weightBrutto", "grossWeight", "gross_weight_kg", "weight"], ["ВесБрутто", "gross_weight_kg", "Вес брутто", "Масса брутто"], ["Вес брутто", "Масса брутто"], packageData ? [packageData.weightGrams, packageData.weight_g, packageData.weight] : [], "weight-grams"),
    fetchedAt: new Date().toISOString(),
  };
}

function validateDryRun(record, requestedMarket) {
  const s = record.supplier || {};
  const o = record.overrides || {};
  const value = (key) => o[key] !== undefined && o[key] !== "" ? o[key] : s[key];
  const barcode = text(value("barcode"));
  const dims = { length: number(value("length")), width: number(value("width")), height: number(value("height")), weight: number(value("weight")) };
  const price = number(o.sellerPrice);
  const wbSubjectId = number(o.wbSubjectId);
  const ozonCategoryId = number(o.ozonCategoryId);
  const ozonTypeId = number(o.ozonTypeId);
  const ozonVat = text(o.ozonVat);
  const blockers = [];
  const wbBlockers = [];
  const ozonBlockers = [];
  if (!/^\d{8,14}$/.test(barcode)) blockers.push("Нужен подтверждённый штрихкод GTIN длиной 8–14 цифр.");
  if (Object.values(dims).some((v) => !(v > 0))) blockers.push("Нужны положительные индивидуальные размеры упаковки и вес брутто.");
  if (!s.photos?.length) blockers.push("В ответе IEK нет проверяемых HTTPS-фотографий.");
  if (requestedMarket !== "wb" && !OZON_SUPPORTED_LOCAL_ARTICLES.has(text(record.article))) ozonBlockers.push("Для этого IEK артикула нет подтверждённого category/type mapping; нельзя назначать категорию контактора по аналогии.");
  if (!(price > 0)) blockers.push("Укажите цену продавца; рекомендованная цена IEK не используется автоматически.");
  if (requestedMarket !== "ozon" && !(wbSubjectId > 0)) wbBlockers.push("Не сопоставлен предмет Wildberries по актуальному каталогу.");
  if (requestedMarket !== "wb" && (!(ozonCategoryId > 0) || !(ozonTypeId > 0))) ozonBlockers.push("Не сопоставлены category_id и type_id Ozon по актуальному каталогу.");
  if (requestedMarket !== "wb" && !ozonVat) ozonBlockers.push("Не подтверждена ставка НДС для продавца в Ozon.");
  const wb = {
    endpoint: "POST /content/v2/cards/upload",
    vendorCode: record.listingArticle,
    subjectID: wbSubjectId || null,
    variants: [{ vendorCode: record.listingArticle, title: s.name || record.article, brand: s.brand || "IEK", barcode: barcode || null,
      dimensions: { length: dims.length, width: dims.width, height: dims.height, weightBrutto: dims.weight }, photos: s.photos || [], characteristics: [] }],
    liveSchemaValidation: "not_performed",
    submission: "disabled",
  };
  const ozonAttributes = [];
  const addAttribute = (id, value) => { if (value !== undefined && value !== null && value !== "") ozonAttributes.push({ id, values: [{ value: String(value) }] }); };
  addAttribute(8229, s.typeName || "Контактор");
  addAttribute(9048, s.shortName || s.name);
  addAttribute(22232, s.feacn);
  addAttribute(85, s.brand || "IEK");
  if (typeof s.isMarked === "boolean") addAttribute(23536, s.isMarked);
  if (requestedMarket !== "wb" && ozonVat === "0.22") ozonBlockers.push("VAT 0.22 was documented for comparable products, but the recorded Ozon import was rejected as vat_invalid; exact current accepted value is not verified.");
  if (requestedMarket !== "wb" && price > 0) ozonBlockers.push("A prior Ozon import was rejected as price_out_of_range; accepted range for this seller/category is not verified.");
  const ozon = {
    endpoint: "POST /v3/product/import",
    items: [{ offer_id: record.listingArticle, name: s.name || record.article, description: s.description || "", images: s.photos || [], barcode: barcode || undefined,
      price: price ? String(price) : undefined, vat: ozonVat || undefined, description_category_id: ozonCategoryId || undefined, type_id: ozonTypeId || undefined, attributes: ozonAttributes }],
    liveSchemaValidation: "not_performed",
    submission: "disabled",
  };
  if (requestedMarket !== "ozon") wbBlockers.push(...blockers);
  if (requestedMarket !== "wb") ozonBlockers.push(...blockers);
  if (requestedMarket !== "ozon") wbBlockers.push("Предмет и обязательные атрибуты нужно проверить по актуальному каталогу WB; live-проверка не выполнялась.");
  if (requestedMarket !== "wb") ozonBlockers.push("Категорию, тип, обязательные атрибуты и словари нужно проверить по актуальному каталогу Ozon; live-проверка не выполнялась.");
  const marketResults = {
    wb: requestedMarket === "ozon" ? { status: "not_requested", blockers: [], payload: null } : { status: wbBlockers.length ? "blocked" : "awaiting_live_validation", blockers: [...new Set(wbBlockers)], payload: wb },
    ozon: requestedMarket === "wb" ? { status: "not_requested", blockers: [], payload: null } : { status: ozonBlockers.length ? "blocked" : "awaiting_live_validation", blockers: [...new Set(ozonBlockers)], payload: ozon },
  };
  return { status: "blocked", checkedAt: new Date().toISOString(), scope: requestedMarket, blockers: [...new Set([...marketResults.wb.blockers, ...marketResults.ozon.blockers])], wb: marketResults.wb, ozon: marketResults.ozon, payloads: { wb, ozon }, submission: "disabled" };
}

function importPayload(source, articles) {
  return { source, articles };
}

function payloadMatches(previous, expected) {
  try {
    const stored = JSON.parse(previous.records_json || "[]");
    if (Array.isArray(stored)) return JSON.stringify(stored) === JSON.stringify(expected.articles);
    return stored?.source === expected.source && JSON.stringify(stored.articles || []) === JSON.stringify(expected.articles);
  } catch {
    return false;
  }
}

function replayImportStart(previous, expected) {
  if (!payloadMatches(previous, expected)) {
    return json({ message: "Ключ повтора уже использован с другим списком артикулов." }, 409);
  }
  return json({ runId: previous.id, status: previous.status, existing: true });
}

function importRunStatus(items) {
  if (items.some((item) => item.status === "queued" || item.status === "processing")) return "queued";
  if (items.some((item) => item.status === "uncertain")) return "uncertain";
  if (items.some((item) => item.status === "failed")) return "failed";
  if (items.some((item) => item.status === "blocked")) return "blocked";
  return items.length ? "complete" : "blocked";
}

async function refreshImportRunStatus(db, runId, now = new Date().toISOString()) {
  const items = await db.prepare("SELECT status FROM import_items WHERE run_id=?").bind(runId).all();
  const status = importRunStatus(items.results || []);
  await db.prepare("UPDATE import_runs SET status=?, updated_at=? WHERE id=?").bind(status, now, runId).run();
  return status;
}

async function loadImportIdentityRecords(db, values) {
  const records = new Map();
  const sources = new Set();
  for (const value of values) {
    sources.add(value);
    const suffix = value.match(/^(.+)-([0-9]+)$/);
    if (suffix) sources.add(suffix[1]);
  }
  const candidates = [...sources];
  for (let offset = 0; offset < candidates.length; offset += 100) {
    const chunk = candidates.slice(offset, offset + 100);
    const placeholders = chunk.map(() => "?").join(",");
    const result = await db.prepare(`SELECT * FROM operator_records WHERE article IN (${placeholders})`).bind(...chunk).all();
    for (const row of result.results || []) records.set(row.article, parseRow(row));
  }
  return records;
}

function hasSupplierSnapshot(record) {
  return Boolean(record?.supplier?.fetchedAt && record.supplier.article === record.article);
}

function hasKnownSupplierIdentity(input, records) {
  return [...records.values()].some((record) => hasSupplierSnapshot(record)
    && (input === record.article || input.startsWith(`${record.article}-`)));
}

async function saveSupplierIdentity(db, records, article, supplier) {
  const existing = records.get(article) || await getRecord(db, article);
  const hasMultiplicity = Number.isSafeInteger(supplier.multiplicity) && supplier.multiplicity >= 1;
  const listingArticle = hasMultiplicity ? resolveOfferId(article, supplier.multiplicity) : existing?.listingArticle || article;
  const record = { article, listingArticle, supplier, overrides: existing?.overrides || {}, validation: null, updatedAt: new Date().toISOString() };
  records.set(article, record);
  if (!hasMultiplicity) return;

  const now = record.updatedAt;
  if (existing) {
    await db.prepare("UPDATE operator_records SET listing_article = ?, supplier_json = ?, validation_json = 'null', updated_at = ? WHERE article = ?")
      .bind(listingArticle, JSON.stringify(supplier), now, article).run();
  } else {
    await db.prepare("INSERT INTO operator_records (article, listing_article, supplier_json, overrides_json, validation_json, updated_at) VALUES (?, ?, ?, '{}', 'null', ?)")
      .bind(article, listingArticle, JSON.stringify(supplier), now).run();
  }
}

async function prepareImportIdentityRecords(db, values, env) {
  const records = await loadImportIdentityRecords(db, values);
  const fetcher = env.FETCH || fetch;
  let cookie;
  const read = async (article) => {
    if (!env.IEK_API_KEY) throw new Error("IEK_API_KEY is not configured for supplier lookup.");
    if (!cookie) cookie = await supplierSession(env.IEK_API_KEY, fetcher);
    const supplier = await readSupplier(article, cookie, fetcher);
    if (supplier) await saveSupplierIdentity(db, records, article, supplier);
    return supplier;
  };

  for (const input of values) {
    if (hasKnownSupplierIdentity(input, records)) continue;
    const direct = await read(input);
    if (direct) continue;
    const suffix = input.match(/^(.+)-([0-9]+)$/);
    if (!suffix || !/^[1-9][0-9]*$/.test(suffix[2]) || !Number.isSafeInteger(Number(suffix[2]))) continue;
    const sourceArticle = suffix[1];
    if (hasKnownSupplierIdentity(sourceArticle, records)) continue;
    await read(sourceArticle);
  }
  return records;
}

function ozonAttribute(id, value, dictionaryValueId = 0) {
  return { id, complex_id: 0, values: [{ dictionary_value_id: dictionaryValueId, value: String(value) }] };
}

function ozonLocalPayload(record, supplier, listingArticle) {
  const name = text(supplier.name || supplier.shortName) || record.article;
  const brand = text(supplier.sourceBrand || supplier.brand);
  const item = {
    offer_id: listingArticle,
    name,
    description: text(supplier.description),
    images: supplier.photos || [],
    barcode: text(supplier.barcode) || undefined,
    price: number(supplier.priceRrc) ? String(number(supplier.priceRrc)) : undefined,
    vat: OZON_APPROVED.vat,
    description_category_id: OZON_APPROVED.descriptionCategoryId,
    type_id: OZON_APPROVED.typeId,
    attributes: [
      ozonAttribute(8229, "Контактор", VERIFIED_OZON_DICTIONARIES.contactorType),
      ozonAttribute(9048, name),
      ozonAttribute(22232, text(supplier.feacn), VERIFIED_OZON_DICTIONARIES.feacn),
      ozonAttribute(85, brand, VERIFIED_OZON_DICTIONARIES.brand),
      ...(text(supplier.description) ? [ozonAttribute(4191, text(supplier.description))] : []),
    ],
  };
  if (VERIFIED_KMIE_CONTACTOR_ARTICLES.has(record.article)) item.attributes.push(ozonAttribute(10818, "3", VERIFIED_OZON_DICTIONARIES.poles3));
  if (Number.isInteger(supplier.technical?.coilVoltage)) item.attributes.push(ozonAttribute(20958, supplier.technical.coilVoltage));
  if (Number.isFinite(supplier.technical?.ac3PowerKwAt400V)) item.attributes.push(ozonAttribute(7225, supplier.technical.ac3PowerKwAt400V));
  if (Number.isFinite(supplier.technical?.nominalCurrentA)) item.attributes.push(ozonAttribute(5776, supplier.technical.nominalCurrentA));
  if (supplier.technical?.ipRating === "IP20") item.attributes.push(ozonAttribute(6980, "IP20", VERIFIED_OZON_DICTIONARIES.ip20));
  if (supplier.technical?.controlCurrentType === "Переменный (AC)") item.attributes.push(ozonAttribute(10819, "Переменный", VERIFIED_OZON_DICTIONARIES.currentTypeAc));
  if (Number.isFinite(number(supplier.multiplicity))) item.attributes.push(ozonAttribute(8962, number(supplier.multiplicity)));
  // Verified IEK manufacturer KMIE table lists Ue=230/400/660 V for these exact
  // six models. 660 is a supported nominal working-voltage value, distinct from
  // coil voltage (20958) and insulation Ui; keep both in the annotation.
  if (VERIFIED_KMIE_CONTACTOR_ARTICLES.has(record.article)) {
    item.attributes.push(ozonAttribute(10823, 660));
    const annotation = item.attributes.find((attribute) => attribute.id === 4191);
    const mainVoltageText = "Номинальное рабочее напряжение главной цепи Ue: 230/400/660 В (IEK KMIE, точная модель).";
    item.description = `${text(item.description)}\n\n${mainVoltageText}`.trim();
    if (annotation) annotation.values[0].value = `${annotation.values[0].value}\n\n${mainVoltageText}`;
    else item.attributes.push(ozonAttribute(4191, mainVoltageText));
  }
  if (supplier.currency && supplier.currency !== "RUB") item.price = undefined;
  if (Number.isFinite(supplier.technical?.coilVoltage)) {
    const textValue = `Напряжение катушки управления: ${supplier.technical.coilVoltage} В.`;
    item.description = `${text(item.description)}\n\n${textValue}`.trim();
    const annotation = item.attributes.find((attribute) => attribute.id === 4191);
    if (annotation) annotation.values[0].value = `${annotation.values[0].value}\n\n${textValue}`;
    else item.attributes.push(ozonAttribute(4191, textValue));
  }
  if (Number.isFinite(supplier.technical?.ac3PowerKwAt400V)) {
    const textValue = `Мощность контактора для категории применения AC-3 при напряжении 400 В: ${supplier.technical.ac3PowerKwAt400V} кВт.`;
    item.description = `${text(item.description)}\n\n${textValue}`.trim();
    const annotation = item.attributes.find((attribute) => attribute.id === 4191);
    if (annotation) annotation.values[0].value = `${annotation.values[0].value}\n\n${textValue}`;
    else item.attributes.push(ozonAttribute(4191, textValue));
  }
  if (typeof supplier.isMarked === "boolean") item.attributes.push(ozonAttribute(23536, supplier.isMarked));
  const length = number(supplier.length);
  const width = number(supplier.width);
  const height = number(supplier.height);
  const weight = number(supplier.weight);
  if (length > 0 && width > 0 && height > 0 && weight > 0) {
    item.depth = Math.round(length);
    item.width = Math.round(width);
    item.height = Math.round(height);
    item.weight = Math.round(weight * 1000);
    item.dimension_unit = "mm";
    item.weight_unit = "g";
  }
  return {
    endpoint: "POST /v3/product/import",
    submission: "disabled",
    validation: "local_deterministic_only",
    items: [item],
  };
}

function validateOzonLocalItem(article, record, duplicateOfferIds = new Set(), resolvedListingArticle = null) {
  const blockers = [];
  const supplier = record?.supplier || {};
  const savedListingArticle = record?.listingArticle || article;
  let listingArticle = resolvedListingArticle || savedListingArticle;
  let canonicalOffer = null;
  if (!record) blockers.push("Нет локальной operator_records записи для артикула; сначала нужен безопасный refresh IEK.");
  if (!Object.keys(supplier).length || !supplier.fetchedAt) blockers.push("Нет локально сохранённых данных IEK для проверки Ozon payload.");
  if (supplier.article !== article) blockers.push("Локальные данные IEK не подтверждают точный исходный артикул.");
  if (!text(supplier.sourceBrand || supplier.brand)) blockers.push("Нет подтверждённого бренда поставщика для заполнения карточки.");
  if (supplier.currency && supplier.currency !== "RUB") blockers.push(`Неподдерживаемая валюта цены IEK: ${supplier.currency}.`);
  try {
    canonicalOffer = resolveOfferId(article, supplier.multiplicity);
    if (savedListingArticle !== canonicalOffer) blockers.push(`Сохранённый offer_id ${savedListingArticle} не совпадает с каноническим ${canonicalOffer}.`);
    listingArticle = canonicalOffer;
  } catch (error) {
    blockers.push(String(error?.message || "Не удалось определить канонический offer_id."));
  }
  if (duplicateOfferIds.has(listingArticle)) blockers.push(`Дублирующий Ozon offer_id в запуске: ${listingArticle}.`);
  if (!/^\d{8,14}$/.test(text(supplier.barcode))) blockers.push("Нет подтверждённого IEK GTIN/barcode длиной 8-14 цифр.");
  if (!Array.isArray(supplier.photos) || !supplier.photos.some((url) => /^https:\/\//i.test(text(url)))) blockers.push("Нет локально сохранённой HTTPS-фотографии IEK для Ozon.");
  if (!OZON_SUPPORTED_LOCAL_ARTICLES.has(article)) blockers.push("Для этого IEK артикула нет подтверждённого mapping категории/типа Ozon; число ETIM полей не заменяет классификацию.");
  const actualEtim = Array.isArray(supplier.etim) ? supplier.etim : [];
  const actualEtimIds = new Set(actualEtim.map((feature) => text(feature.id)).filter(Boolean));
  const requiredEtimFactsUnverifiable = actualEtim.length > 0 && actualEtimIds.size === 0;
  for (const [fact, etimId] of Object.entries(OZON_CONFIRMED_REQUIRED_ETIM)) {
    const value = supplier.technical?.[fact];
    if (value === undefined || value === null || value === "" || requiredEtimFactsUnverifiable || actualEtimIds.size > 0 && !actualEtimIds.has(etimId)) {
      blockers.push(`Нет подтверждённого ETIM source fact ${etimId} для required product field ${fact}.`);
    }
  }
  if (!(number(supplier.priceRrc) > 0)) blockers.push("Нет положительной IEK RRC для approved seller price policy.");
  const packDimensions = ["length", "width", "height"].map((field) => number(supplier[field]));
  const packWeight = number(supplier.weight);
  if (packDimensions.some((value) => !(value > 0)) || !(packWeight > 0)) blockers.push("Нет проверенных положительных индивидуальных размеров упаковки и веса IEK, корректно нормализованных из исходных единиц.");
  if (text(supplier.feacn) !== OZON_APPROVED.feacn) blockers.push(`IEK feacn должен быть ${OZON_APPROVED.feacn} для локального Ozon payload.`);
  if (supplier.isMarked !== OZON_APPROVED.isMarked) blockers.push("IEK isMarked=true должен быть локально подтверждён для Ozon attribute 23536.");
  blockers.push(OZON_LIVE_RECONCILIATION_BLOCKER);
  const payload = ozonLocalPayload({ article }, supplier, listingArticle);
  const onlyLiveReconciliationMissing = blockers.length === 1 && blockers[0] === OZON_LIVE_RECONCILIATION_BLOCKER;
  return {
    article,
    listingArticle,
    status: "blocked",
    stage: onlyLiveReconciliationMissing ? "live_reconciliation_required" : "local_validation",
    supplier,
    payload,
    error: {
      message: onlyLiveReconciliationMissing ? "Локальный Ozon payload собран; live reconciliation не выполнен, создание выключено." : "Локальная проверка Ozon не пройдена.",
      blockers: [...new Set(blockers)],
    },
  };
}

function validateOzonImportItems(recordsByArticle, identities) {
  const offerIds = identities.map((identity) => identity.listingArticle);
  const duplicates = new Set(offerIds.filter((offerId, index) => offerIds.indexOf(offerId) !== index));
  return identities.map((identity) => validateOzonLocalItem(identity.article, identity.record || recordsByArticle.get(identity.article), duplicates, identity.listingArticle));
}

function queueImportItem(item) {
  const blockers = item.error?.blockers || [];
  const localBlockers = blockers.filter((blocker) => blocker !== OZON_LIVE_RECONCILIATION_BLOCKER);
  if (item.stage === "live_reconciliation_required" && localBlockers.length === 0) {
    return { ...item, status: "queued", stage: "read_only_reconciliation", error: null };
  }
  return item;
}

function parseJson(value, fallback) {
  try { return JSON.parse(value || ""); } catch { return fallback; }
}

async function ozonSellerPost(env, path, body) {
  const fetcher = env.FETCH || fetch;
  const stage = path === OZON_PRODUCT_IMPORT
    ? "seller_create_submission"
    : path === OZON_PRODUCT_IMPORT_INFO
      ? "seller_create_polling"
      : path === OZON_PRODUCT_PICTURES_IMPORT
        ? "seller_photo_update"
      : "read_only_reconciliation";
  const response = await fetcher(`${OZON_API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Client-Id": String(env.OZON_CLIENT_ID || ""),
      "Api-Key": String(env.OZON_API_KEY || ""),
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    const safePart = (value) => {
      if (typeof value !== "string" && typeof value !== "number") return "";
      return String(value).replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, 140);
    };
    const code = safePart(errorBody?.code ?? errorBody?.error?.code);
    const message = safePart(errorBody?.message ?? errorBody?.error?.message);
    const error = new Error(`Ozon Seller ${path} returned HTTP ${response.status}${code ? ` (${code})` : ""}${message ? `: ${message}` : ""}`);
    error.stage = stage;
    throw error;
  }
  try {
    return await response.json();
  } catch {
    const error = new Error(`Ozon Seller ${path} returned invalid JSON.`);
    error.stage = stage;
    throw error;
  }
}

async function ozonReadOnlyPost(env, path, body) {
  return ozonSellerPost(env, path, body);
}

async function resolveOzonDictionaries(env, payloadItem) {
  const resolved = new Map();
  const schemaBody = await ozonReadOnlyPost(env, OZON_CATEGORY_ATTRIBUTES, {
    description_category_id: payloadItem.description_category_id,
    type_id: payloadItem.type_id,
    language: "RU",
  });
  const dictionaryAttrs = new Set(schemaAttributes(schemaBody)
    .filter((schema) => Number(schema.dictionary_id) > 0)
    .map((schema) => Number(schema.id)));
  for (const attribute of payloadItem.attributes || []) {
    const id = Number(attribute.id);
    if (!dictionaryAttrs.has(id)) continue;
    const expected = attribute.values?.[0];
    const search = id === 10818 ? null : await ozonReadOnlyPost(env, OZON_CATEGORY_ATTRIBUTE_VALUES, {
      description_category_id: payloadItem.description_category_id,
      type_id: payloadItem.type_id,
      attribute_id: id,
      value: OZON_DICTIONARY_SEARCH_NAMES[id] || text(expected?.value),
      limit: 100,
    });
    const values = Array.isArray(search?.result) ? search.result : Array.isArray(search?.result?.values) ? search.result.values : Array.isArray(search?.values) ? search.values : [];
    const expectedValue = text(OZON_DICTIONARY_SEARCH_NAMES[id] || expected?.value).trim().toLocaleLowerCase("ru");
    const code = id === 22232 ? text(expected?.value).match(/^\d{10,14}/)?.[0] : null;
    let allValues = [...values];
    if (id === 10818) {
      let lastValueId = 0;
      for (let page = 0; page < 20; page += 1) {
        const pageBody = await ozonReadOnlyPost(env, "/v1/description-category/attribute/values", {
          description_category_id: payloadItem.description_category_id,
          type_id: payloadItem.type_id,
          attribute_id: id,
          last_value_id: lastValueId,
          limit: 1000,
        });
        const pageValues = Array.isArray(pageBody?.result?.values) ? pageBody.result.values : Array.isArray(pageBody?.result) ? pageBody.result : [];
        allValues.push(...pageValues);
        const hasNext = pageBody?.result?.has_next === true || pageBody?.has_next === true;
        const nextId = Number(pageBody?.result?.last_value_id ?? pageBody?.last_value_id ?? pageValues.at(-1)?.id ?? 0);
        if (!hasNext || !Number.isFinite(nextId) || nextId <= lastValueId) break;
        lastValueId = nextId;
      }
    }
    const exact = allValues.filter((row) => {
      const label = text(row.value || row.name).trim();
      return code ? label.match(/^\d{10,14}/)?.[0] === code : label.toLocaleLowerCase("ru") === expectedValue;
    });
    const verified = exact.find((row) => Number(row.id || row.dictionary_value_id) === Number(expected?.dictionary_value_id)) || exact[0];
    if (verified && Number(verified.id || verified.dictionary_value_id) > 0) {
      resolved.set(id, { value: text(verified.value || verified.name), id: Number(verified.id || verified.dictionary_value_id) });
    }
  }
  return resolved;
}

function applyOzonDictionaries(payloadItem, dictionaryMap) {
  for (const attribute of payloadItem.attributes || []) {
    const found = dictionaryMap.get(Number(attribute.id));
    if (!found) continue;
    for (const value of attribute.values || []) {
      value.value = found.value;
      value.dictionary_value_id = found.id;
    }
  }
  return payloadItem;
}

function productInfoItems(body) {
  return body?.items || body?.result?.items || body?.result || [];
}

function productIdFromInfo(body, offerId) {
  const items = Array.isArray(productInfoItems(body)) ? productInfoItems(body) : [];
  const product = items.find((item) => text(item.offer_id || item.offerId) === offerId) || null;
  const productId = product?.product_id ?? product?.id;
  return productId === undefined || productId === null || productId === "" ? null : String(productId);
}

function productIdFromReadback(description, attributes, fallback) {
  const candidates = [description?.result?.id, description?.result?.product_id, attributes?.product_id, attributes?.id, fallback];
  const id = candidates.find((value) => value !== undefined && value !== null && value !== "");
  return id === undefined ? null : String(id);
}

function schemaAttributes(body) {
  const raw = body?.result || body?.attributes || [];
  const list = Array.isArray(raw) ? raw : raw.attributes || raw.items || [];
  return Array.isArray(list) ? list : [];
}

export function missingRequiredAttributes(schemaBody, payloadItem, { dictionariesValidated = new Set() } = {}) {
  const attributes = payloadItem.attributes || [];
  return schemaAttributes(schemaBody)
    .filter((schema) => schema?.is_required === true || schema?.required === true)
    .filter((schema) => Number.isFinite(Number(schema.id)))
    .filter((schema) => {
      const value = attributes.find((entry) => Number(entry.id) === Number(schema.id));
      const dictionaryId = Number(schema.dictionary_id) || 0;
      return !value || !Array.isArray(value.values) || value.values.length === 0 || value.values.some((entry) => {
        const raw = entry?.value;
        if (typeof raw !== "string" || raw.trim() === "") return true;
        if (schema.type === "Integer" && !/^-?\d+$/.test(raw)) return true;
        if (schema.type === "Decimal" && !/^-?(?:\d+|\d*\.\d+)$/.test(raw)) return true;
        if (schema.type === "Boolean" && !["true", "false"].includes(raw.toLowerCase())) return true;
        if (dictionaryId > 0 && (!(Number(entry.dictionary_value_id) > 0) || dictionariesValidated.size > 0 && !dictionariesValidated.has(Number(schema.id)))) return true;
        return false;
      });
    })
    .map((schema) => ({ id: Number(schema.id), name: text(schema.name) || null }));
}

function unwrappedProduct(body) {
  if (Array.isArray(body?.result)) return body.result[0] || null;
  if (body?.result && typeof body.result === "object") return body.result;
  if (Array.isArray(body?.items)) return body.items[0] || null;
  return null;
}

function actualAttribute(product, id) {
  return (Array.isArray(product?.attributes) ? product.attributes : []).find((entry) => Number(entry.id) === id) || null;
}

function compareOzonReadback(expected, product, prices, pictureResponse, categorySchema) {
  const differences = [];
  const expectedAttrs = Array.isArray(expected.attributes) ? expected.attributes : [];
  const expectedValue = (id) => expectedAttrs.find((entry) => Number(entry.id) === id)?.values?.[0]?.value;
  const compare = (field, wanted, actual) => { if (String(wanted ?? "") !== String(actual ?? "")) differences.push({ field, expected: wanted ?? null, actual: actual ?? null }); };
  compare("offer_id", expected.offer_id, product?.offer_id);
  compare("name", expected.name, product?.name);
  compare("description_category_id", expected.description_category_id, product?.description_category_id);
  compare("type_id", expected.type_id, product?.type_id);
  const schemaRequired = new Set(schemaAttributes(categorySchema).filter((entry) => entry?.is_required === true || entry?.required === true).map((entry) => Number(entry.id)));
  const expectedById = new Map(expectedAttrs.map((entry) => [Number(entry.id), entry]));
  for (const id of schemaRequired) if (!expectedById.has(id)) differences.push({ field: `required_attribute_${id}`, expected: "present in prepared payload", actual: "missing" });
  if (product?.description !== undefined) compare("description", expected.description, product.description);
  else differences.push({ field: "description", expected: expected.description ?? "", actual: null });
  for (const term of ["Напряжение катушки управления:", "Номинальная коммутируемая мощность при категории применения AC-3 и напряжении 400 В:"]) {
    if (String(expected.description || "").includes(term) && !String(product?.description || "").includes(term)) differences.push({ field: "technical_description", expected: term, actual: "missing" });
  }
  const actualAttrs = product?.attributes || product?.result?.attributes || [];
  const expectedIdByAttr = new Map(expectedAttrs.map((entry) => [Number(entry.id), entry]));
  const expectedMainVoltage = expectedIdByAttr.get(10823)?.values?.[0];
  const actualMainVoltage = actualAttribute({ attributes: actualAttrs }, 10823)?.values?.[0];
  if (expectedMainVoltage) {
    compare("attribute_10823_main_voltage", expectedMainVoltage.value, actualMainVoltage?.value);
    if (Number(actualMainVoltage?.value) !== Number(expectedMainVoltage.value)) differences.push({ field: "attribute_10823_main_voltage_type", expected: "supported numeric main-circuit voltage", actual: actualMainVoltage?.value ?? null });
  } else if (actualMainVoltage) {
    differences.push({ field: "attribute_10823_unverified", expected: "absent for unsupported SKU", actual: actualMainVoltage.value ?? "present" });
  }
  const actualModel = actualAttribute({ attributes: actualAttrs }, 9048)?.values?.[0]?.value;
  const expectedModel = expectedIdByAttr.get(9048)?.values?.[0]?.value;
  if (expectedModel !== undefined) compare("attribute_9048", expectedModel, actualModel);
  const expectedAnnotation = expectedIdByAttr.get(4191)?.values?.[0]?.value;
  if (expectedAnnotation !== undefined) compare("attribute_4191", expectedAnnotation, actualAttribute({ attributes: actualAttrs }, 4191)?.values?.[0]?.value);
  const expectedType = expectedIdByAttr.get(8229)?.values?.[0];
  if (expectedType) {
    const actualType = actualAttribute({ attributes: actualAttrs }, 8229)?.values?.[0];
    compare("attribute_8229", expectedType.value, actualType?.value);
    if (Number(expectedType.dictionary_value_id) > 0 && Number(actualType?.dictionary_value_id) !== Number(expectedType.dictionary_value_id)) differences.push({ field: "attribute_8229_dictionary", expected: expectedType.dictionary_value_id, actual: actualType?.dictionary_value_id ?? null });
  }
  const actualCurrency = product?.currency_code || product?.currency || prices?.currency_code || prices?.result?.currency_code;
  if (actualCurrency && text(actualCurrency) !== "RUB") differences.push({ field: "currency", expected: "RUB", actual: actualCurrency });
  const barcodeAttr = actualAttrs.find((attribute) => /barcode|штрихкод/i.test(text(attribute.name)));
  const actualBarcode = product?.barcodes?.[0] ?? product?.barcode ?? barcodeAttr?.values?.[0]?.value;
  if (expected.barcode !== undefined) compare("barcode", expected.barcode, actualBarcode);
  for (const id of [85, 8229, 9048, 4191, 10818, 10823, 20958, 7225, 5776, 6980, 10819, 8962, 23536, 22232]) {
    const expectedAttr = expectedAttrs.find((entry) => Number(entry.id) === id);
    if (!expectedAttr) continue;
    const actual = actualAttribute({ attributes: actualAttrs }, id);
    const expectedEntry = expectedAttr.values?.[0];
    const actualEntry = actual?.values?.[0];
    compare(`attribute_${id}`, expectedEntry?.value, actualEntry?.value);
    if (Number(expectedEntry?.dictionary_value_id) > 0 && Number(actualEntry?.dictionary_value_id) !== Number(expectedEntry.dictionary_value_id)) differences.push({ field: `attribute_${id}_dictionary`, expected: expectedEntry.dictionary_value_id, actual: actualEntry?.dictionary_value_id ?? null });
  }
  for (const field of ["depth", "width", "height", "weight"]) {
    if (expected[field] !== undefined && Number(product?.[field]) !== Number(expected[field])) differences.push({ field, expected: Number(expected[field]), actual: Number.isFinite(Number(product[field])) ? Number(product[field]) : null });
  }
  const dimensionUnit = product?.dimension_unit ?? product?.dimensions?.unit ?? product?.depth_unit;
  const weightUnit = product?.weight_unit ?? product?.weight?.unit;
  if (dimensionUnit !== undefined && text(expected.dimension_unit || "mm") !== text(dimensionUnit)) differences.push({ field: "dimension_unit", expected: expected.dimension_unit || "mm", actual: dimensionUnit || null });
  if (weightUnit !== undefined && text(expected.weight_unit || "g") !== text(weightUnit)) differences.push({ field: "weight_unit", expected: expected.weight_unit || "g", actual: weightUnit || null });
  const priceRows = prices?.items || prices?.result?.items || [];
  const expectedProductId = String(product?.id || product?.product_id || "");
  const expectedOfferId = text(expected.offer_id);
  const row = priceRows.find((entry) => text(entry.offer_id) === expectedOfferId && (!entry.product_id && !entry.id || String(entry.product_id || entry.id) === expectedProductId)) || null;
  if (!row) differences.push({ field: "seller_price_row", expected: expected.offer_id, actual: "missing_exact_offer" });
  if (row && text(row.currency_code || row.currency || row.price?.currency_code || "RUB") !== "RUB") differences.push({ field: "currency", expected: "RUB", actual: row.currency_code || row.currency || row.price?.currency_code || null });
  const priceValue = row?.price?.price ?? row?.price;
  const sellerPrice = priceValue === undefined || priceValue === null || priceValue === "" ? null : Number(priceValue);
  if (expected.price !== undefined && (!Number.isFinite(sellerPrice) || sellerPrice !== Number(expected.price))) differences.push({ field: "seller_price", expected: Number(expected.price), actual: Number.isFinite(sellerPrice) ? sellerPrice : null });
  const actualVat = row?.price?.vat ?? row?.price?.vat_rate ?? row?.vat ?? null;
  if (expected.vat !== undefined && text(actualVat) !== text(expected.vat)) differences.push({ field: "vat", expected: expected.vat, actual: actualVat });
  const pictureItems = pictureResponse?.items || pictureResponse?.result?.items || [];
  const picture = pictureItems.find((entry) => String(entry.product_id) === String(product?.id || product?.product_id)) || null;
  if (!picture) differences.push({ field: "picture_product", expected: String(product?.id || product?.product_id), actual: "missing_exact_product" });
  const actualPictures = [...photoUrls(picture?.primary_photo), ...photoUrls(picture?.photo)];
  const sourcePhotos = expected.images || [];
  const reportedPhotoErrors = Array.isArray(picture?.errors) ? picture.errors : [];
  const uniquePictures = [...new Set(actualPictures)];
  if (actualPictures.length !== sourcePhotos.length || uniquePictures.length !== actualPictures.length || reportedPhotoErrors.length) differences.push({ field: "images", expectedCount: sourcePhotos.length, actualCount: actualPictures.length, duplicateCount: actualPictures.length - uniquePictures.length, errors: reportedPhotoErrors });
  const primary = photoUrls(picture?.primary_photo);
  if (!primary.length || primary.length !== 1) differences.push({ field: "primary_image", expected: "exactly one primary photo", actual: primary });

  const taskItem = product?.taskItem || product?.validation || {};
  const validationFailure = ozonValidationErrors(taskItem);
  if (validationFailure) differences.push({ field: "product_validation", expected: "no blocking validation errors", actual: validationFailure });
  return differences;
}

async function verifyOzonProduct(env, item, productId) {
  const payload = parseJson(item.payload_json, null);
  const expected = payload?.items?.[0];
  if (!expected) throw new Error("No saved expected payload exists for product readback.");
  const offerId = text(item.listing_article || expected.offer_id);
  const [descriptionBody, attributesBody, prices, pictures, categorySchema] = await Promise.all([
    ozonReadOnlyPost(env, OZON_PRODUCT_INFO_DESCRIPTION, { product_id: Number(productId) }),
    ozonReadOnlyPost(env, OZON_PRODUCT_INFO_ATTRIBUTES, { filter: { product_id: [String(productId)] }, limit: 100 }),
    ozonReadOnlyPost(env, OZON_PRODUCT_PRICES, { filter: { product_id: [Number(productId)] }, limit: 100 }),
    ozonReadOnlyPost(env, OZON_PRODUCT_PICTURES_INFO, { product_id: [Number(productId)] }),
    ozonReadOnlyPost(env, OZON_CATEGORY_ATTRIBUTES, { description_category_id: expected.description_category_id, type_id: expected.type_id, language: "RU" }),
  ]);
  const descriptionRows = descriptionBody?.result && !Array.isArray(descriptionBody.result) ? [descriptionBody.result] : Array.isArray(descriptionBody?.result) ? descriptionBody.result : [];
  const description = descriptionRows.find((entry) => String(entry.id || entry.product_id) === String(productId)) || null;
  if (!description) return { differences: [{ field: "product_description", expected: "readable product", actual: null }], checkedAt: new Date().toISOString() };
  const attrProducts = attributesBody?.result || attributesBody?.items || [];
  const attributes = Array.isArray(attrProducts) ? attrProducts.find((entry) => String(entry.product_id || entry.id) === String(productId)) || null : null;
  if (!attributes) return { differences: [{ field: "attribute_product", expected: String(productId), actual: "missing_exact_product" }], checkedAt: new Date().toISOString() };
  const product = { ...description, ...(attributes || {}) };
  const returnedProductId = productIdFromReadback(description, attributes, productId);
  if (returnedProductId !== String(productId)) return { differences: [{ field: "product_id", expected: String(productId), actual: returnedProductId }], checkedAt: new Date().toISOString() };
  const differences = compareOzonReadback(expected, product, prices, pictures, categorySchema);
  const schema = schemaAttributes(categorySchema);
  const dictionarySchemaById = new Map(schema.filter((entry) => Number(entry.dictionary_id) > 0).map((entry) => [Number(entry.id), entry]));
  for (const expectedAttr of expected.attributes || []) {
    const id = Number(expectedAttr.id);
    const schemaAttr = schema.find((entry) => Number(entry.id) === id);
    const expectedValueItem = expectedAttr.values?.[0];
    const expectedValue = expectedValueItem?.value;
    if (typeof expectedValue !== "string" || expectedValue.trim() === "") {
      differences.push({ field: `attribute_${id}_expected`, expected: expectedValue ?? null, actual: "empty_or_non_string" });
      continue;
    }
    if (schemaAttr?.type === "Integer" && !/^-?\d+$/.test(expectedValue)) differences.push({ field: `attribute_${id}_type`, expected: "Integer", actual: expectedValue });
    if (schemaAttr?.type === "Decimal" && !/^-?(?:\d+|\d*\.\d+)$/.test(expectedValue)) differences.push({ field: `attribute_${id}_type`, expected: "Decimal", actual: expectedValue });
    if (schemaAttr?.type === "Boolean" && !["true", "false"].includes(expectedValue.toLowerCase())) differences.push({ field: `attribute_${id}_type`, expected: "Boolean", actual: expectedValue });
    const dictionarySchema = dictionarySchemaById.get(id);
    if (dictionarySchema && Number(expectedValueItem.dictionary_value_id) <= 0) differences.push({ field: `attribute_${id}_dictionary`, expected: "dictionary id required", actual: expectedValueItem.dictionary_value_id ?? null });
  }
  const expectedBrand = (expected.attributes || []).find((entry) => Number(entry.id) === 85)?.values?.[0];
  const dictionaryRows = categorySchema?.dictionaries || categorySchema?.result?.dictionaries || [];
  const brandDictionary = dictionaryRows.find((entry) => Number(entry.attribute_id || entry.attributeId) === 85)?.values || [];
  if (brandDictionary.length && !brandDictionary.some((entry) => Number(entry.id) === Number(expectedBrand?.dictionary_value_id) && text(entry.value) === text(expectedBrand?.value))) differences.push({ field: "brand_dictionary", expected: expectedBrand || null, actual: "not in current schema dictionary" });
  return { differences, checkedAt: new Date().toISOString(), offerId };
}

export async function reconcileOzonReadOnly(env, item) {
  const payload = parseJson(item.payload_json, null);
  const payloadItem = payload?.items?.[0];
  if (!payloadItem) throw new Error("No prepared Ozon payload is stored for read-only reconciliation.");
  const offerId = text(item.listing_article || payloadItem.offer_id);
  const infoBody = await ozonReadOnlyPost(env, OZON_PRODUCT_INFO_LIST, { offer_id: [offerId] });
  const productId = productIdFromInfo(infoBody, offerId);
  const infoItems = productInfoItems(infoBody);
  const existingInfoItem = (Array.isArray(infoItems) ? infoItems : []).find((entry) => text(entry.offer_id || entry.offerId) === offerId) || null;
  const schemaBody = await ozonReadOnlyPost(env, OZON_CATEGORY_ATTRIBUTES, {
    description_category_id: payloadItem.description_category_id,
    type_id: payloadItem.type_id,
    language: "RU",
  });
  const dictionaries = await resolveOzonDictionaries(env, payloadItem);
  applyOzonDictionaries(payloadItem, dictionaries);
  const requiredDictionaryIds = new Set(schemaAttributes(schemaBody)
    .filter((schema) => Number(schema.dictionary_id) > 0 && (schema.is_required === true || schema.required === true))
    .map((schema) => Number(schema.id)));
  const submittedDictionaryIds = new Set((payloadItem.attributes || [])
    .filter((attribute) => Number(schemaAttributes(schemaBody).find((schema) => Number(schema.id) === Number(attribute.id))?.dictionary_id) > 0)
    .map((attribute) => Number(attribute.id)));
  const validationDictionaryIds = new Set([...requiredDictionaryIds, ...submittedDictionaryIds]);
  const missing = missingRequiredAttributes(schemaBody, payloadItem, { dictionariesValidated: validationDictionaryIds });
  const unresolvedDictionaries = [...validationDictionaryIds].filter((id) => !dictionaries.has(id));
  for (const id of unresolvedDictionaries) missing.push({ id, name: text(schemaAttributes(schemaBody).find((schema) => Number(schema.id) === id)?.name) || null, reason: "official_dictionary_lookup_unresolved" });
  const technical = parseJson(item.supplier_json, {})?.technical || {};
  for (const [id, value] of [[20958, technical.coilVoltage], [7225, technical.ac3PowerKwAt400V]]) {
    if (value === null || value === undefined) continue;
    const attribute = schemaAttributes(schemaBody).find((entry) => Number(entry.id) === id);
    const validType = id === 20958 ? attribute?.type === "Integer" && Number.isInteger(Number(value)) : attribute?.type === "Decimal";
    if (!attribute || !validType) missing.push({ id, name: text(attribute?.name) || null, reason: "schema_type_or_source_value_invalid" });
  }
  const checkedAt = new Date().toISOString();
  const nextPayload = {
    ...payload,
    readOnlyReconciliation: {
      checkedAt,
      productInfo: existingInfoItem ? { endpoint: `POST ${OZON_PRODUCT_INFO_LIST}`, productId, offerId, ...existingInfoItem } : { endpoint: `POST ${OZON_PRODUCT_INFO_LIST}`, productId, offerId },
      schema: { endpoint: `POST ${OZON_CATEGORY_ATTRIBUTES}`, dictionaryLookupEndpoint: `POST ${OZON_CATEGORY_ATTRIBUTE_VALUES}`, resolvedDictionaries: [...dictionaries.entries()], missingRequiredAttributes: missing },
      sellerCreate: "not_evaluated",
    },
  };
  return { productId, payload: nextPayload, payloadItem, missingRequiredAttributes: missing, offerId };
}

function missingRequiredAttributeBlockers(missing) {
  return missing.map((attribute) => `Missing required Ozon attribute ${attribute.id}${attribute.name ? ` (${attribute.name})` : ""}.`);
}

async function submitOzonSellerCreate(env, payloadItem) {
  const body = await ozonSellerPost(env, OZON_PRODUCT_IMPORT, { items: [payloadItem] });
  const taskId = body?.result?.task_id;
  if (taskId === undefined || taskId === null || taskId === "") {
    const error = new Error("Ozon import response did not include result.task_id.");
    error.stage = "seller_create_submission";
    throw error;
  }
  return String(taskId);
}

function importInfoItems(body) {
  const items = body?.result?.items || [];
  return Array.isArray(items) ? items : [];
}

function importInfoItemForOffer(body, offerId) {
  return importInfoItems(body).find((entry) => text(entry.offer_id || entry.offerId) === offerId) || null;
}

function importInfoFailure(item) {
  const errors = Array.isArray(item?.errors) ? item.errors : [];
  const blocking = errors.filter((entry) => {
    const code = text(entry?.code || entry?.status).toLowerCase();
    const level = text(entry?.error_level || entry?.level || entry?.severity).toUpperCase();
    return level.includes("ERROR") || level.includes("FATAL") || entry?.is_blocking === true || entry?.isBlocking === true || !["value_found_by_synonym", "pics_http_error", "some_image_failed"].includes(code);
  });
  if (blocking.length) return blocking;
  const status = text(item?.status).toLowerCase();
  return /fail|error|reject|declin/.test(status) ? [{ status: item?.status || "failed" }] : [];
}

export async function pollOzonSellerCreate(env, item) {
  const taskId = Number(item.ozon_task_id);
  if (!Number.isSafeInteger(taskId) || taskId <= 0) throw new Error("Stored Ozon task id is not a safe positive integer.");
  const payload = parseJson(item.payload_json, null);
  const payloadItem = payload?.items?.[0];
  const offerId = text(item.listing_article || payloadItem?.offer_id);
  const body = await ozonSellerPost(env, OZON_PRODUCT_IMPORT_INFO, { task_id: taskId });
  const infoItem = importInfoItemForOffer(body, offerId);
  const checkedAt = new Date().toISOString();
  const nextPayload = {
    ...payload,
    sellerCreate: {
      ...(payload?.sellerCreate || {}),
      endpoint: `POST ${OZON_PRODUCT_IMPORT}`,
      taskInfoEndpoint: `POST ${OZON_PRODUCT_IMPORT_INFO}`,
      taskId: String(item.ozon_task_id),
      lastCheckedAt: checkedAt,
      taskItem: infoItem,
    },
  };
  if (!infoItem) return { status: "queued", stage: "seller_create_polling", productId: item.product_id || null, taskId: String(item.ozon_task_id), payload: nextPayload, error: null };
  if (text(infoItem.status).toLowerCase() === "imported") {
    const productId = infoItem.product_id ?? infoItem.id;
    if (productId === undefined || productId === null || productId === "") throw new Error("Ozon import task is imported but product_id is missing.");
    const verified = await verifyOzonProduct(env, item, String(productId));
    nextPayload.sellerCreate.readback = verified;
    if (verified.differences.length) return { status: "failed", stage: "seller_create_verification", productId: String(productId), taskId: String(item.ozon_task_id), payload: nextPayload, error: { message: "Imported product did not pass persisted-field verification.", differences: verified.differences } };
    const freshInfoBody = await ozonReadOnlyPost(env, OZON_PRODUCT_INFO_LIST, { offer_id: [offerId] });
    const freshInfoItems = productInfoItems(freshInfoBody);
    const productInfo = (Array.isArray(freshInfoItems) ? freshInfoItems : []).find((entry) => text(entry.offer_id || entry.offerId) === offerId) || null;
    const validationFailure = ozonValidationErrors(productInfo);
    nextPayload.sellerCreate.productInfo = productInfo;
    if (!productInfo || String(productInfo.product_id || productInfo.id || "") !== String(productId)) return { status: "failed", stage: "seller_create_validation", productId: String(productId), taskId: String(item.ozon_task_id), payload: nextPayload, error: { message: "Ozon imported product has no matching fresh product-info record.", productInfo } };
    if (validationFailure) return { status: "failed", stage: "seller_create_validation", productId: String(productId), taskId: String(item.ozon_task_id), payload: nextPayload, error: { message: "Fresh Ozon product-info reports failed product validation after import.", validation: validationFailure } };
    const readback = await verifyOzonProduct(env, { ...item, payload_json: JSON.stringify(nextPayload) }, String(productId));
    nextPayload.sellerCreate.readback = readback;
    if (readback.differences.length) return { status: "failed", stage: "seller_create_verification", productId: String(productId), taskId: String(item.ozon_task_id), payload: nextPayload, error: { message: "Ozon imported product failed persisted-field verification.", differences: readback.differences } };
    return { status: "complete", stage: "seller_create_verified", productId: String(productId), taskId: String(item.ozon_task_id), payload: nextPayload, error: null };
  }
  const failure = importInfoFailure(infoItem);
  if (failure.length) {
    return {
      status: "failed",
      stage: "seller_create_polling",
      productId: item.product_id || null,
      taskId: String(item.ozon_task_id),
      payload: nextPayload,
      error: { message: "Ozon Seller create task failed.", errors: failure },
    };
  }
  return { status: "queued", stage: "seller_create_polling", productId: item.product_id || null, taskId: String(item.ozon_task_id), payload: nextPayload, error: null };
}

function safePhotoUrl(value) {
  const url = text(value);
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && !parsed.username && !parsed.password ? url : "";
  } catch { return ""; }
}

function photoInfoItem(body, productId) {
  const items = body?.items || body?.result?.items || [];
  return Array.isArray(items) ? items.find((entry) => String(entry.product_id) === String(productId)) || null : null;
}

function photoUrls(value) {
  return Array.isArray(value) ? value.map(safePhotoUrl).filter(Boolean) : [];
}

function photoSnapshot(infoItem, sourcePhotos) {
  const primaryPhotos = photoUrls(infoItem?.primary_photo).slice(0, 1);
  const photos = photoUrls(infoItem?.photo);
  const errors = (Array.isArray(infoItem?.errors) ? infoItem.errors : []).map((entry) => {
    const index = sourcePhotos.indexOf(text(entry?.url));
    return {
      sourcePhotoIndex: index >= 0 ? index + 1 : null,
      message: text(entry?.message).slice(0, 220) || "Ozon image processing failed.",
    };
  });
  return { primaryPhotos, photos, total: new Set([...primaryPhotos, ...photos]).size, errors };
}

function photoUpdatePayload(payload, photoUpdate) {
  return {
    ...payload,
    sellerCreate: {
      ...(payload?.sellerCreate || {}),
      photoUpdate,
    },
  };
}

async function persistCompleteItemPayload(db, runId, item, payload) {
  const payloadJson = JSON.stringify(payload);
  const result = await db.prepare("UPDATE import_items SET payload_json=?, updated_at=? WHERE run_id=? AND article=? AND listing_article=? AND status='complete' AND payload_json=?")
    .bind(payloadJson, new Date().toISOString(), runId, item.article, item.listing_article, item.payload_json).run();
  return { changes: result.meta?.changes || 0, item: { ...item, payload_json: payloadJson } };
}

async function updateImportItem(db, runId, item, result, now = new Date().toISOString(), claimToken = null) {
  const query = claimToken
    ? "UPDATE import_items SET status=?, stage=?, error_json=?, product_id=?, ozon_task_id=?, attempts=attempts+1, updated_at=?, payload_json=?, claim_token=NULL, claim_started_at=NULL WHERE run_id=? AND article=? AND listing_article=? AND claim_token=? AND (ozon_task_id IS NULL OR ozon_task_id=?)"
    : "UPDATE import_items SET status=?, stage=?, error_json=?, product_id=?, ozon_task_id=?, attempts=attempts+1, updated_at=?, payload_json=? WHERE run_id=? AND article=? AND listing_article=?";
  const values = [result.status, result.stage, result.error ? JSON.stringify(result.error) : null, result.productId || null, result.taskId || item.ozon_task_id || null, now, JSON.stringify(result.payload || parseJson(item.payload_json, null)), runId, item.article, item.listing_article];

  const saved = await db.prepare(query).bind(...(claimToken ? [...values, claimToken, result.taskId || item.ozon_task_id || null] : values)).run();
  return saved.meta?.changes || 0;
}

function ozonValidationErrors(productInfo) {
  const statuses = productInfo?.statuses && typeof productInfo.statuses === "object" ? productInfo.statuses : {};
  const validationStatus = text(statuses.validation_status || statuses.validationStatus || productInfo?.validation_status || productInfo?.validationStatus).toLowerCase();
  const errors = Array.isArray(productInfo?.errors) ? productInfo.errors : [];
  const statusLevel = text(statuses.error_level || statuses.errorLevel || statuses.level).toUpperCase();
  const errorLevel = text(productInfo?.error_level || productInfo?.errorLevel || statusLevel).toUpperCase();
  const blockingErrors = errors.filter((entry) => {
    const level = text(entry?.error_level || entry?.level || entry?.severity).toUpperCase();
    return ["ERROR", "FATAL", "CRITICAL"].includes(level) || level.endsWith("_ERROR") || level.endsWith("_FATAL") || level.endsWith("_CRITICAL") || entry?.is_blocking === true || entry?.isBlocking === true;
  });
  const topLevelIsBlocking = ["ERROR", "FATAL", "CRITICAL"].includes(errorLevel) || errorLevel.endsWith("_ERROR") || errorLevel.endsWith("_FATAL") || errorLevel.endsWith("_CRITICAL");
  if (["failed", "error", "invalid", "rejected"].includes(validationStatus) || topLevelIsBlocking || blockingErrors.length) {
    return { validationStatus, errorLevel: errorLevel || null, errors: blockingErrors.length ? blockingErrors : errors };
  }
  return null;
}

export async function processImportItem(env, item, { runId, claimToken } = {}) {
  if (item.ozon_task_id) return pollOzonSellerCreate(env, item);
  const reconciliation = await reconcileOzonReadOnly(env, item);
  if (reconciliation.missingRequiredAttributes.length) {
    return {
      status: "blocked",
      stage: "read_only_reconciliation",
      productId: reconciliation.productId,
      taskId: item.ozon_task_id || null,
      payload: { ...reconciliation.payload, readOnlyReconciliation: { ...reconciliation.payload.readOnlyReconciliation, sellerCreate: "blocked_missing_required_attributes" } },
      error: {
        message: "Read-only Ozon schema reconciliation found missing required attributes.",
        blockers: missingRequiredAttributeBlockers(reconciliation.missingRequiredAttributes),
      },
    };
  }
  if (reconciliation.productId) {
    const localBlockers = parseJson(item.validation_json, null)?.error?.blockers || [];
    if (localBlockers.length) {
      return { status: "blocked", stage: "local_validation", productId: reconciliation.productId, taskId: item.ozon_task_id || null, payload: reconciliation.payload, error: { message: "Local source validation is incomplete; existing product is not accepted without complete expected data.", blockers: localBlockers } };
    }
    const validationFailure = ozonValidationErrors(reconciliation.payload.readOnlyReconciliation.productInfo);
    if (validationFailure) {
      return { status: "failed", stage: "existing_product_validation", productId: reconciliation.productId, taskId: item.ozon_task_id || null, payload: reconciliation.payload, error: { message: "Ozon reports failed product validation despite a matching product id.", validation: validationFailure } };
    }
    const readback = await verifyOzonProduct(env, { ...item, payload_json: JSON.stringify(reconciliation.payload) }, reconciliation.productId);
    const payload = { ...reconciliation.payload, readOnlyReconciliation: { ...reconciliation.payload.readOnlyReconciliation, readback } };
    if (readback.differences.length) {
      return { status: "failed", stage: "existing_product_verification", productId: reconciliation.productId, taskId: item.ozon_task_id || null, payload, error: { message: "Existing Ozon product differs from current IEK and approved expected fields.", differences: readback.differences } };
    }
    return {
      status: "complete",
      stage: "existing_product_verified",
      productId: reconciliation.productId,
      taskId: item.ozon_task_id || null,
      payload: { ...payload, readOnlyReconciliation: { ...payload.readOnlyReconciliation, sellerCreate: "skipped_existing_product" } },
      error: null,
    };
  }
  if (env.OZON_SELLER_CREATE_ENABLED !== "true") {
    return {
      status: "blocked",
      stage: "seller_create_disabled",
      productId: null,
      taskId: item.ozon_task_id || null,
      payload: { ...reconciliation.payload, readOnlyReconciliation: { ...reconciliation.payload.readOnlyReconciliation, sellerCreate: "disabled" } },
      error: { message: "Read-only Ozon reconciliation completed; seller create remains disabled.", blockers: [OZON_CREATE_DISABLED_BLOCKER] },
    };
  }
  const intentAt = new Date().toISOString();
  const intentPayload = { ...reconciliation.payload, submissionIntent: { endpoint: `POST ${OZON_PRODUCT_IMPORT}`, payload: { items: [reconciliation.payloadItem] } }, sellerCreate: { endpoint: `POST ${OZON_PRODUCT_IMPORT}`, state: "submission_uncertain", intentAt } };
  const intent = await env.DB.prepare("UPDATE import_items SET status='processing',stage='seller_create_submission_intent',error_json=NULL,payload_json=?,submission_intent_at=?,updated_at=? WHERE run_id=? AND article=? AND listing_article=? AND claim_token=? AND submission_intent_at IS NULL")
    .bind(JSON.stringify(intentPayload), intentAt, intentAt, runId, item.article, item.listing_article, claimToken).run();
  if (!(intent.meta?.changes > 0)) throw Object.assign(new Error("Import claim lost before external submission."), { stage: "seller_create_submission_uncertain" });
  let taskId;
  try { taskId = await submitOzonSellerCreate(env, reconciliation.payloadItem); }
  catch (error) {
    const beforeSubmit = error?.stage === "seller_create_submission" && String(error.message || "").includes("did not include result.task_id");
    if (beforeSubmit) {
      await env.DB.prepare("UPDATE import_items SET status='failed',stage='seller_create_submission',error_json=?,submission_intent_at=NULL,claim_token=NULL,claim_started_at=NULL,updated_at=? WHERE run_id=? AND article=? AND listing_article=? AND claim_token=? AND submission_intent_at=?")
        .bind(JSON.stringify({ message: "Provider rejected the request before returning a task receipt; safe retry remains available." }), new Date().toISOString(), runId, item.article, item.listing_article, claimToken, intentAt).run();
      throw error;
    }
    await env.DB.prepare("UPDATE import_items SET status='uncertain',stage='seller_create_submission_uncertain',error_json=?,claim_token=NULL,claim_started_at=NULL,updated_at=? WHERE run_id=? AND article=? AND listing_article=? AND claim_token=? AND submission_intent_at=?")
      .bind(JSON.stringify({ message: "Provider submission outcome is unknown; reconcile before resubmission.", attentionRequired: true }), new Date().toISOString(), runId, item.article, item.listing_article, claimToken, intentAt).run();
    throw Object.assign(new Error("Ozon submit outcome is uncertain; automatic retry is disabled."), { stage: "seller_create_submission_uncertain" });
  }
  if (!taskId) {
    await env.DB.prepare("UPDATE import_items SET status='uncertain',stage='seller_create_submission_uncertain',error_json=?,claim_token=NULL,claim_started_at=NULL,updated_at=? WHERE run_id=? AND article=? AND listing_article=? AND claim_token=? AND submission_intent_at=?")
      .bind(JSON.stringify({ message: "Provider returned no task receipt; reconcile before resubmission.", attentionRequired: true }), new Date().toISOString(), runId, item.article, item.listing_article, claimToken, intentAt).run();
    throw Object.assign(new Error("Ozon returned no receipt; automatic retry is disabled."), { stage: "seller_create_submission_uncertain" });
  }
  const receipt = await env.DB.prepare("UPDATE import_items SET status='queued',stage='seller_create_polling',error_json=NULL,ozon_task_id=?,payload_json=?,updated_at=?,claim_token=NULL,claim_started_at=NULL WHERE run_id=? AND article=? AND listing_article=? AND claim_token=? AND submission_intent_at=? AND ozon_task_id IS NULL")
    .bind(String(taskId), JSON.stringify({ ...reconciliation.payload, submissionIntent: intentPayload.submissionIntent, readOnlyReconciliation: { ...reconciliation.payload.readOnlyReconciliation, sellerCreate: "submitted" }, sellerCreate: { endpoint: `POST ${OZON_PRODUCT_IMPORT}`, taskInfoEndpoint: `POST ${OZON_PRODUCT_IMPORT_INFO}`, state: "receipt_saved", taskId: String(taskId), submittedAt: new Date().toISOString() } }), new Date().toISOString(), runId, item.article, item.listing_article, claimToken, intentAt).run();
  if (!(receipt.meta?.changes > 0)) throw Object.assign(new Error("Accepted Ozon import receipt could not be persisted; reconcile before retry."), { stage: "seller_create_submission_uncertain" });
  return {
    status: "queued",
    stage: "seller_create_polling",
    productId: null,
    taskId,
    payload: {
      ...reconciliation.payload,
      readOnlyReconciliation: { ...reconciliation.payload.readOnlyReconciliation, sellerCreate: "submitted" },
      sellerCreate: { endpoint: `POST ${OZON_PRODUCT_IMPORT}`, taskInfoEndpoint: `POST ${OZON_PRODUCT_IMPORT_INFO}`, taskId, submittedAt: new Date().toISOString() },
    },
    error: null,
  };
}

export async function handle(request, env) {
  const url = new URL(request.url);
  if (url.pathname === "/favicon.svg") return new Response(FAVICON, { headers: { ...noStore, "content-type": "image/svg+xml" } });
  if (url.pathname === "/" && request.method === "GET") return new Response(PAGE, { headers: { ...noStore, "content-type": "text/html; charset=utf-8", "Content-Security-Policy": "default-src 'self'; img-src 'self' https: data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'" } });
  if (!url.pathname.startsWith("/api/")) return new Response("Not found", { status: 404, headers: noStore });
  const origin = request.headers.get("origin");
  if (origin && origin !== url.origin) return json({ message: "Запрос должен идти с этой страницы." }, 403);
  if (url.pathname === "/api/operator/session") {
    if (request.method === "DELETE") {
      return new Response(null, { status: 204, headers: { ...noStore, "Set-Cookie": `${OPERATOR_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0` } });
    }
    if (request.method === "POST") {
      if (origin !== url.origin) return json({ message: "Войдите с открытой страницы сайта." }, 403);
      if (!isOperatorTokenConfigured(env)) return json({ message: "Вход оператора ещё не настроен." }, 503);
      const body = await request.json().catch(() => null);
      const token = typeof body?.token === "string" ? body.token : "";
      if (token.length > 512 || !sameSecret(token, env.OZON_OPERATOR_TOKEN)) return json({ message: "Неверный код оператора." }, 401);
      const session = await signOperatorSession(env);
      return new Response(JSON.stringify({ authenticated: true }), { status: 200, headers: { ...noStore, "Content-Type": "application/json; charset=utf-8", "Set-Cookie": `${OPERATOR_COOKIE}=${session}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${OPERATOR_SESSION_SECONDS}` } });
    }
  }
  const operatorSession = await readOperatorSession(request, env);
  // Public Sites do not provide an authenticated-user identity to anonymous
  // visitors. Supplier refresh remains the only anonymous write; the optional
  // signed Site cookie supports approved operators outside ChatGPT.
  const signedInUser = operatorSession || request.headers.get("oai-authenticated-user-id");
  const ozonOperators = new Set(String(env.OZON_OPERATOR_IDS || "").split(",").map((id) => id.trim()).filter(Boolean));
  const isOzonOperator = Boolean(operatorSession || signedInUser && ozonOperators.has(signedInUser));
  if (url.pathname === "/api/operator/session" && request.method === "GET") {
    return json({ configured: isOperatorTokenConfigured(env), authenticated: isOzonOperator });
  }
  const supplierRefresh = url.pathname === "/api/supplier/refresh" && request.method === "POST";
  const publicStateRead = url.pathname === "/api/state" && request.method === "GET";
  if (!signedInUser && !supplierRefresh && !publicStateRead) return json({ message: "Для этой операции нужна авторизация пользователя." }, 401);
  if (url.pathname === "/api/import/start" && request.method === "POST") {
    if (!signedInUser) return json({ message: "Требуется вход оператора." }, 401);
    if (!isOzonOperator) return json({ message: "У пользователя нет прав на импорт Ozon." }, 403);
    if (!env.DB) return json({ message: "Хранилище недоступно." }, 503);
    const body = await request.json().catch(() => null);
    if (!body || !["manual", "xlsx"].includes(body.source) || !Array.isArray(body.articles)) return json({ message: "Некорректный запрос." }, 400);
    const parsed = parseManualArticles(body.articles);
    if (parsed.errors.length) return json({ message: "Исправьте артикулы с ошибками.", errors: parsed.errors }, 400);
    if (!parsed.articles.length) return json({ message: "Пустой список артикулов." }, 400);
    const key = text(body.idempotencyKey);
    if (!/^[A-Za-z0-9_-]{16,128}$/.test(key)) return json({ message: "Нужен валидный ключ повтора." }, 400);
    await seed(env.DB);
    let recordsByArticle;
    try {
      recordsByArticle = await prepareImportIdentityRecords(env.DB, parsed.articles, env);
    } catch (error) {
      const message = String(error?.message || "");
      const missingConfig = message.includes("IEK_API_KEY is not configured");
      const supplierStatus = Number(message.match(/HTTP (\d{3})/)?.[1]) || null;
      return json({
        message: missingConfig ? "Для новых артикулов не настроена защищённая интеграция IEK." : "Не удалось проверить данные артикула в IEK.",
        ...(supplierStatus ? { supplierStatus } : {}),
      }, missingConfig ? 503 : 502);
    }
    const resolved = resolveImportIdentities(parsed.articles, recordsByArticle);
    const importDuplicates = [...parsed.duplicates, ...resolved.duplicates];
    if (resolved.errors.length) return json({ message: "Исправьте артикулы с ошибками.", errors: resolved.errors, duplicates: importDuplicates }, 400);
    if (!resolved.articles.length) return json({ message: "Пустой список артикулов." }, 400);
    const expectedPayload = importPayload(body.source, resolved.articles);
    const previous = await env.DB.prepare("SELECT id, status, records_json FROM import_runs WHERE principal_id=? AND idempotency_key=?").bind(signedInUser, key).first();
    if (previous) return replayImportStart(previous, expectedPayload);
    const id = crypto.randomUUID();
    const now = new Date().toISOString();
    if ((!env.OZON_OPERATOR_IDS && !isOperatorTokenConfigured(env)) || !env.IEK_API_KEY || !env.OZON_CLIENT_ID || !env.OZON_API_KEY) {
      const configError = { message: "Импорт временно заблокирован: администратор не настроил защищённую интеграцию или список операторов." };
      await env.DB.batch([
        env.DB.prepare("INSERT INTO import_runs (id,principal_id,idempotency_key,status,created_at,updated_at,records_json) VALUES (?,?,?,?,?,?,?)")
          .bind(id, signedInUser, key, "blocked", now, now, JSON.stringify(expectedPayload)),
        ...resolved.identities.map((identity) => env.DB.prepare("INSERT INTO import_items (run_id,article,listing_article,status,stage,error_json,updated_at) VALUES (?,?,?,?,?,?,?)")
          .bind(id, identity.article, identity.listingArticle, "blocked", "configuration", JSON.stringify(configError), now)),
      ]);
      return json({ runId:id, status:"blocked", results:resolved.identities.map((identity)=>({article:identity.article,listingArticle:identity.listingArticle,status:"blocked",stage:"configuration",message:configError.message})), duplicates:importDuplicates }, 202);
    }
    try {
      const validatedItems = validateOzonImportItems(recordsByArticle, resolved.identities).map(queueImportItem);
      const runStatus = importRunStatus(validatedItems);
      await env.DB.batch([
        env.DB.prepare("INSERT INTO import_runs (id,principal_id,idempotency_key,status,created_at,updated_at,records_json) VALUES (?,?,?,?,?,?,?)")
          .bind(id, signedInUser, key, runStatus, now, now, JSON.stringify(expectedPayload)),
        ...validatedItems.map((item) => env.DB.prepare("INSERT INTO import_items (run_id,article,listing_article,status,stage,error_json,updated_at,supplier_json,payload_json) VALUES (?,?,?,?,?,?,?,?,?)")
          .bind(id, item.article, item.listingArticle, item.status, item.stage, item.error ? JSON.stringify(item.error) : null, now, JSON.stringify(item.supplier), JSON.stringify(item.payload))),
      ]);
      return json({ runId:id, status:runStatus, results:validatedItems.map((item)=>({article:item.article,listingArticle:item.listingArticle,status:item.status,stage:item.stage,message:item.error?.message || "Ожидает read-only Ozon reconciliation.",blockers:item.error?.blockers || []})), duplicates:importDuplicates }, 202);
    } catch (error) {
      if (String(error?.message||"").includes("UNIQUE constraint")) {
        const previous = await env.DB.prepare("SELECT id, status, records_json FROM import_runs WHERE principal_id=? AND idempotency_key=?").bind(signedInUser,key).first();
        if (previous) return replayImportStart(previous, expectedPayload);
      }
      throw error;
    }
  }

  if (url.pathname.startsWith("/api/import/") && request.method === "GET") {
    if (!signedInUser) return json({ message: "Требуется вход оператора." }, 401);
    if (!isOzonOperator) return json({ message: "У пользователя нет прав на импорт Ozon." }, 403);
    if (!env.DB) return json({message:"Хранилище недоступно."},503);
    const runId=url.pathname.split("/").at(-1);
    const run=await env.DB.prepare("SELECT id,principal_id,status,created_at,updated_at,records_json FROM import_runs WHERE id=?").bind(runId).first();
    if (!run) return json({ message: "Запуск не найден." },404);
    if (run.principal_id !== signedInUser) return json({ message: "Нет доступа к запуску." },403);
    const items=await env.DB.prepare("SELECT article,listing_article,status,stage,error_json,product_id,ozon_task_id,attempts,updated_at,supplier_json,payload_json,submission_intent_at FROM import_items WHERE run_id=? ORDER BY article").bind(runId).all();
    return json({run:{id:run.id,status:run.status,createdAt:run.created_at,updatedAt:run.updated_at},items:(items.results||[]).map(x=>({...x,error:x.error_json?JSON.parse(x.error_json):null,supplier:x.supplier_json?JSON.parse(x.supplier_json):null,payload:x.payload_json?JSON.parse(x.payload_json):null,attentionRequired:x.status==="uncertain"||Boolean(x.submission_intent_at&&!x.ozon_task_id)}))});
  }

  if (url.pathname === "/api/import/process" && request.method === "POST") {
    if (!signedInUser) return json({ message:"Требуется вход оператора." },401);
    if (!isOzonOperator) return json({ message: "У пользователя нет прав на импорт Ozon." },403);
    if (!env.DB) return json({message:"Хранилище недоступно."},503);
    if (!env.OZON_CLIENT_ID || !env.OZON_API_KEY) return json({ message: "Read-only Ozon reconciliation is unavailable: protected Ozon credentials are not configured." }, 503);
    const body=await request.json().catch(()=>null);
    if (!body || !text(body.runId)) return json({message:"Нужен идентификатор запуска."},400);
    const run=await env.DB.prepare("SELECT id,principal_id,status FROM import_runs WHERE id=?").bind(body.runId).first();
    if (!run) return json({message:"Запуск не найден."},404);
    if (run.principal_id!==signedInUser) return json({message:"Нет доступа к запуску."},403);
    const items=await env.DB.prepare("SELECT article,listing_article,status,stage,error_json,product_id,ozon_task_id,attempts,updated_at,supplier_json,payload_json,submission_intent_at,claim_started_at FROM import_items WHERE run_id=? ORDER BY article").bind(run.id).all();
    const staleCutoff = new Date(Date.now() - 5 * 60 * 1000).toISOString();
    const recoverable = (items.results || []).filter((item) => item.status === "queued" || item.status === "processing" && item.claim_started_at && item.claim_started_at < staleCutoff);
    for (const item of recoverable) {
      if (item.status !== "processing") continue;
      if (item.submission_intent_at && !item.ozon_task_id) {
        await env.DB.prepare("UPDATE import_items SET status='uncertain',stage='seller_create_submission_uncertain',error_json=?,claim_token=NULL,claim_started_at=NULL,updated_at=? WHERE run_id=? AND article=? AND listing_article=? AND status='processing' AND submission_intent_at IS NOT NULL AND ozon_task_id IS NULL AND claim_started_at=?")
          .bind(JSON.stringify({ message: "Submission intent survived claim expiry without a task receipt; reconcile before retry.", attentionRequired: true }), new Date().toISOString(), run.id, item.article, item.listing_article, item.claim_started_at).run();
      } else if (item.ozon_task_id) {
        await env.DB.prepare("UPDATE import_items SET status='queued',stage='seller_create_polling',error_json=NULL,claim_token=NULL,claim_started_at=NULL,updated_at=? WHERE run_id=? AND article=? AND listing_article=? AND status='processing' AND claim_started_at=? AND ozon_task_id=?")
          .bind(new Date().toISOString(), run.id, item.article, item.listing_article, item.claim_started_at, item.ozon_task_id).run();
      } else {
        await env.DB.prepare("UPDATE import_items SET status='queued',stage='read_only_reconciliation',claim_token=NULL,claim_started_at=NULL,updated_at=? WHERE run_id=? AND article=? AND listing_article=? AND status='processing' AND claim_started_at=? AND submission_intent_at IS NULL AND ozon_task_id IS NULL")
          .bind(new Date().toISOString(), run.id, item.article, item.listing_article, item.claim_started_at).run();
      }
    }
    const queued=(items.results||[]).filter((item)=>item.status==="queued" || item.status==="processing" && item.ozon_task_id && item.claim_started_at < staleCutoff);
    const processed=[];
    for (const item of queued) {
      const now = new Date().toISOString();
      const claimToken = crypto.randomUUID();
      const pollKnownReceipt = Boolean(item.ozon_task_id);
        const claimed = await env.DB.prepare("UPDATE import_items SET status='processing',stage=?,claim_token=?,claim_started_at=?,updated_at=? WHERE run_id=? AND article=? AND listing_article=? AND (status='queued' OR status='processing' AND claim_started_at=?) AND claim_token IS NULL AND ((ozon_task_id IS NOT NULL AND ozon_task_id=?) OR (ozon_task_id IS NULL AND submission_intent_at IS NULL))")
        .bind(pollKnownReceipt ? "seller_create_polling" : "claimed", claimToken, now, now, run.id, item.article, item.listing_article, item.claim_started_at || null, item.ozon_task_id || null).run();
      if (!(claimed.meta?.changes > 0)) continue;
      try {
        const result = await processImportItem(env, item, { runId: run.id, claimToken });
        if (result.taskId && env.DB.failReceiptWriteOnce) {
          env.DB.failReceiptWriteOnce = false;
          throw Object.assign(new Error("Injected one-shot post-accept receipt persistence failure"), { acceptedTaskId: result.taskId });
        }
        if (await updateImportItem(env.DB, run.id, item, result, now, claimToken)) processed.push({ article:item.article, listingArticle:item.listing_article, status:result.status, stage:result.stage, productId:result.productId, ozonTaskId:result.taskId, message:result.error?.message || "OK", blockers:result.error?.blockers || [] });
      } catch (error) {
        const current = await env.DB.prepare("SELECT status,submission_intent_at,ozon_task_id FROM import_items WHERE run_id=? AND article=? AND listing_article=?").bind(run.id,item.article,item.listing_article).first();
        if (error?.acceptedTaskId && current?.submission_intent_at && !current?.ozon_task_id) {
          await env.DB.prepare("UPDATE import_items SET status='uncertain',stage='seller_create_submission_uncertain',error_json=?,claim_token=NULL,claim_started_at=NULL,updated_at=? WHERE run_id=? AND article=? AND listing_article=? AND claim_token=? AND submission_intent_at IS NOT NULL AND ozon_task_id IS NULL")
            .bind(JSON.stringify({ message: "Provider accepted submission but receipt persistence failed; operator reconciliation required.", attentionRequired: true }), new Date().toISOString(), run.id, item.article, item.listing_article, claimToken).run();
          processed.push({ article:item.article, listingArticle:item.listing_article, status:"uncertain", stage:"seller_create_submission_uncertain", message:"Provider accepted submission but receipt persistence failed; reconcile before retry." });
          continue;
        }
        if (current?.status === "failed" && error?.stage === "seller_create_submission") {
          processed.push({ article:item.article, listingArticle:item.listing_article, status:"failed", stage:"seller_create_submission", message:"Provider rejected submission; retry remains available." });
          continue;
        }
        const failedStage = error?.stage || (item.ozon_task_id ? "seller_create_polling" : "read_only_reconciliation");
        const failure = { message: error?.stage ? String(error.message || "Ozon Seller request failed.").slice(0, 220) : "Read-only Ozon reconciliation failed." };
        if (current?.submission_intent_at && current?.ozon_task_id) {
          await env.DB.prepare("UPDATE import_items SET status='failed',stage='seller_create_polling',error_json=?,claim_token=NULL,claim_started_at=NULL,updated_at=? WHERE run_id=? AND article=? AND listing_article=? AND claim_token=? AND ozon_task_id=?")
            .bind(JSON.stringify({ message: "Polling the saved Ozon receipt failed; retry will poll this receipt without resubmitting.", retryable: true }), new Date().toISOString(), run.id, item.article, item.listing_article, claimToken, current.ozon_task_id).run();
          processed.push({ article:item.article, listingArticle:item.listing_article, status:"failed", stage:"seller_create_polling", message:"Saved Ozon task poll failed; retry preserves the receipt." });
        } else if (current?.submission_intent_at) {
          await env.DB.prepare("UPDATE import_items SET status='uncertain',stage='seller_create_submission_uncertain',error_json=?,claim_token=NULL,claim_started_at=NULL,updated_at=? WHERE run_id=? AND article=? AND listing_article=? AND claim_token=? AND ozon_task_id IS NULL")
            .bind(JSON.stringify({ message: "Submission intent exists without a known receipt; operator reconciliation required.", attentionRequired: true }), new Date().toISOString(), run.id, item.article, item.listing_article, claimToken).run();
          processed.push({ article:item.article, listingArticle:item.listing_article, status:"uncertain", stage:"seller_create_submission_uncertain", message:"Submission outcome unknown; reconcile before retry." });
        } else if (await updateImportItem(env.DB, run.id, item, { status:"failed", stage:failedStage, error:failure, productId:item.product_id || null, taskId:item.ozon_task_id || null, payload:parseJson(item.payload_json, null) }, now, claimToken)) {
          processed.push({ article:item.article, listingArticle:item.listing_article, status:"failed", stage:failedStage, message:failure.message });
        }
      }
    }
    const status = await refreshImportRunStatus(env.DB, run.id);
    return json({ runId:run.id, status, processed:processed.length, results:processed });
  }

  if (url.pathname === "/api/import/retry" && request.method === "POST") {
    if (!signedInUser) return json({ message:"Требуется вход оператора." },401);
    if (!isOzonOperator) return json({ message: "У пользователя нет прав на импорт Ozon." },403);
    const body=await request.json().catch(()=>null);
    if (!body || !text(body.runId)) return json({message:"Нужен идентификатор запуска."},400);
    if (!env.DB) return json({message:"Хранилище недоступно."},503);
    const run=await env.DB.prepare("SELECT id,principal_id FROM import_runs WHERE id=?").bind(body.runId).first();
    if (!run) return json({message:"Запуск не найден."},404);
    if (run.principal_id!==signedInUser) return json({message:"Нет доступа к запуску."},403);
    const now = new Date().toISOString();
    const failedItems = await env.DB.prepare("SELECT article,listing_article,ozon_task_id FROM import_items WHERE run_id=? AND status='failed' ORDER BY article").bind(run.id).all();
    let retried = 0;
    for (const item of failedItems.results || []) {
      const nextStage = item.ozon_task_id ? "seller_create_polling" : "read_only_reconciliation";
      const result = await env.DB.prepare("UPDATE import_items SET status='queued', stage=?, error_json=NULL, updated_at=? WHERE run_id=? AND article=? AND listing_article=? AND status='failed' AND (ozon_task_id IS NOT NULL OR submission_intent_at IS NULL)")
        .bind(nextStage, now, run.id, item.article, item.listing_article).run();
      retried += result.meta?.changes || 0;
    }
    const status = await refreshImportRunStatus(env.DB, run.id, now);
    return json({ runId:run.id, status, retried, message:retried ? "Failed items were queued for Ozon import retry." : "Нет failed items для повтора." });
  }

  if (url.pathname === "/api/import/pictures" && request.method === "POST") {
    if (!isOzonOperator) return json({ message: "У пользователя нет прав на импорт Ozon." },403);
    if (!env.DB) return json({ message: "Хранилище недоступно." },503);
    if (!env.OZON_CLIENT_ID || !env.OZON_API_KEY) return json({ message: "Защищённые credentials Ozon не настроены." },503);
    if (env.OZON_SELLER_CREATE_ENABLED !== "true") return json({ message: "Записи Seller API выключены текущим write gate." },423);
    const body=await request.json().catch(()=>null);
    if (!body || !text(body.runId) || !text(body.listingArticle)) return json({ message: "Нужны run ID и offer ID." },400);
    const run=await env.DB.prepare("SELECT id,principal_id FROM import_runs WHERE id=?").bind(body.runId).first();
    if (!run) return json({ message: "Запуск не найден." },404);
    if (run.principal_id!==signedInUser) return json({ message: "Нет доступа к запуску." },403);
    const rows=await env.DB.prepare("SELECT article,listing_article,status,product_id,ozon_task_id,supplier_json,payload_json FROM import_items WHERE run_id=? ORDER BY article").bind(run.id).all();
    const item=(rows.results||[]).find((entry)=>entry.listing_article===text(body.listingArticle));
    if (!item) return json({ message: "Товар не найден в этом запуске." },404);
    const productId=Number(item.product_id);
    if (item.status!=="complete" || !item.ozon_task_id || !Number.isSafeInteger(productId) || productId<=0) {
      return json({ message: "Фото можно обновить только у уже импортированного товара с сохранённым product_id." },409);
    }
    const payload=parseJson(item.payload_json,null);
    const supplier=parseJson(item.supplier_json,null);
    if (!payload || !supplier || !Array.isArray(supplier.photos)) return json({ message: "В запуске нет сохранённых данных фото IEK." },409);
    const sourcePhotos=photoUrls(supplier.photos);
    const prior=payload?.sellerCreate?.photoUpdate||null;
    const readPhotos=async()=>{
      const result=await ozonReadOnlyPost(env,OZON_PRODUCT_PICTURES_INFO,{product_id:[String(productId)]});
      return photoInfoItem(result,productId);
    };
    let beforeInfo;
    try { beforeInfo=await readPhotos(); }
    catch { return json({ message: "Не удалось проверить текущие изображения товара в Ozon." },502); }
    if (!beforeInfo) return json({ message: "Ozon не вернул изображения сохранённого product_id." },502);
    const before=photoSnapshot(beforeInfo,sourcePhotos);

    if (prior?.submittedAt) {
      const expectedPhotoCount=Number(prior.expectedPhotoCount)||before.total;
      const unresolved=before.errors.filter((error)=>prior.sourcePhotoIndices?.includes(error.sourcePhotoIndex));
      const verified=before.total>=expectedPhotoCount&&!unresolved.length;
      const photoUpdate={...prior,status:verified?"verified":unresolved.length?"failed":"pending",checkedAt:new Date().toISOString(),after:{photoCount:before.total,primaryCount:before.primaryPhotos.length,errors:before.errors}};
      const persisted=await persistCompleteItemPayload(env.DB,run.id,item,photoUpdatePayload(payload,photoUpdate));
      if (!persisted.changes) return json({ message: "Состояние запуска изменилось; обновите страницу перед проверкой фото." },409);
      return json({runId:run.id,listingArticle:item.listing_article,status:photoUpdate.status,photoCount:before.total,expectedPhotoCount,message:verified?"Фото проверены в Ozon.":"Загрузка фото ещё не подтверждена.",updateSent:false});
    }

    const erroredUrls=[...new Set((Array.isArray(beforeInfo.errors)?beforeInfo.errors:[])
      .map((error)=>text(error?.url))
      .filter((imageUrl)=>sourcePhotos.includes(imageUrl)&&safePhotoUrl(imageUrl)))];
    if (!erroredUrls.length) return json({ message: "Ozon не сообщил об ошибке сохранённого URL IEK; повторная отправка не выполнялась.",photoCount:before.total },409);
    const primary=before.primaryPhotos[0];
    const images=[...new Set([primary,...before.photos,...erroredUrls].filter(Boolean))];
    if (!primary || images.length>30) return json({ message: "Набор фото не прошёл локальную проверку; Ozon не вызывался." },409);
    const sourcePhotoIndices=erroredUrls.map((imageUrl)=>sourcePhotos.indexOf(imageUrl)+1);
    const submittedAt=new Date().toISOString();
    const photoUpdate={
      status:"submitting",
      endpoint:`POST ${OZON_PRODUCT_PICTURES_IMPORT}`,
      submittedAt,
      sourcePhotoIndices,
      expectedPhotoCount:images.length,
      before:{photoCount:before.total,primaryCount:before.primaryPhotos.length,errors:before.errors},
    };
    const claimed=await persistCompleteItemPayload(env.DB,run.id,item,photoUpdatePayload(payload,photoUpdate));
    if (!claimed.changes) return json({ message: "Обновление фото уже начато; повторная отправка отменена." },409);

    let importResult;
    try {
      importResult=await ozonSellerPost(env,OZON_PRODUCT_PICTURES_IMPORT,{
        product_id:productId,
        images,
        images360:photoUrls(beforeInfo.photo_360),
        color_image:photoUrls(beforeInfo.color_photo)[0]||"",
      });
    } catch (error) {
      photoUpdate.status="failed";
      photoUpdate.lastError=String(error?.message||"Ozon image update failed.").slice(0,220);
      await persistCompleteItemPayload(env.DB,run.id,claimed.item,photoUpdatePayload(payload,photoUpdate));
      return json({runId:run.id,listingArticle:item.listing_article,status:"failed",message:photoUpdate.lastError,updateSent:true},502);
    }
    photoUpdate.status="pending";
    photoUpdate.resultStates=(Array.isArray(importResult?.result?.pictures)?importResult.result.pictures:[]).slice(0,30).map((picture)=>({
      state:text(picture?.state)||null,
      isPrimary:picture?.is_primary===true,
      is360:picture?.is_360===true,
      isColor:picture?.is_color===true,
    }));
    const submittedPayload=photoUpdatePayload(payload,photoUpdate);
    const submitted=await persistCompleteItemPayload(env.DB,run.id,claimed.item,submittedPayload);
    if (!submitted.changes) return json({ message: "Загрузка отправлена, но запись состояния изменилась; проверьте фото вручную в Ozon." },202);
    try {
      const afterInfo=await readPhotos();
      if (afterInfo) {
        const after=photoSnapshot(afterInfo,sourcePhotos);
        const unresolved=after.errors.filter((error)=>sourcePhotoIndices.includes(error.sourcePhotoIndex));
        const verified=after.total>=images.length&&!unresolved.length;
        photoUpdate.status=verified?"verified":unresolved.length?"failed":"pending";
        photoUpdate.checkedAt=new Date().toISOString();
        photoUpdate.after={photoCount:after.total,primaryCount:after.primaryPhotos.length,errors:after.errors};
      } else {
        photoUpdate.lastCheckError="Ozon did not return the product after image update.";
      }
    } catch {
      photoUpdate.lastCheckError="Could not verify the updated product images yet.";
    }
    const finalPayload=photoUpdatePayload(payload,photoUpdate);
    await persistCompleteItemPayload(env.DB,run.id,submitted.item,finalPayload);
    const verified=photoUpdate.status==="verified";
    return json({
      runId:run.id,
      listingArticle:item.listing_article,
      status:photoUpdate.status,
      photoCount:photoUpdate.after?.photoCount??before.total,
      expectedPhotoCount:images.length,
      sourcePhotoIndices,
      updateSent:true,
      message:verified?"Фото проверены в Ozon.":"Запрос на фото отправлен; подтверждение ещё ожидается.",
    });
  }

  if (url.pathname === "/api/articles/preview" && request.method === "POST") {
    if (!signedInUser) return json({ message: "Войдите как оператор для разбора списка." }, 401);
    try {
      const type = request.headers.get("content-type") || "";
      const parsed = type.toLowerCase().includes("multipart/form-data")
        ? await parseArticleUpload((await request.formData()).get("file"))
        : parseManualArticles((await request.json()).articles);
      return json(parsed, parsed.errors.length && !parsed.articles.length ? 400 : 200);
    } catch (error) { return json({ message: String(error?.message || "Не удалось разобрать список.") }, 400); }
  }
  if (!env.DB) return json({ message: "Хранилище оператора временно недоступно." }, 503);
  if (supplierRefresh) {
    if (request.headers.get("origin") !== url.origin) return json({ message: "Обновление доступно только с этой страницы." }, 403);
    const contentType = request.headers.get("content-type") || "";
    if (!contentType.toLowerCase().startsWith("application/json")) return json({ message: "Ожидается JSON-запрос." }, 415);
    const length = Number(request.headers.get("content-length") || 0);
    if (length > 128) return json({ message: "Слишком большой запрос." }, 413);

  }
  if (url.pathname === "/api/state" && request.method === "GET") {
    const publicState = !signedInUser;
    if (!publicState) await seed(env.DB);
    const records = await listRecords(env.DB, { publicOnly: publicState });
    return Response.json({ records, ...(publicState ? {} : { events: await listEvents(env.DB) }) }, { headers: publicState ? publicRead : noStore });
  }
  if (request.method !== "POST") return json({ message: "Метод не поддерживается." }, 405);
  await seed(env.DB);
  let body;
  try { body = await request.json(); } catch { return json({ message: "Ожидается JSON-запрос." }, 400); }
  if (!body || typeof body !== "object" || typeof body.article !== "string" && !["/api/supplier/refresh"].includes(url.pathname)) return json({ message: "Проверьте поля запроса." }, 400);
  if (url.pathname === "/api/supplier/refresh") {
    if (request.method !== "POST") return json({ message: "Метод не поддерживается." }, 405);
    if (!signedInUser) {
      if (!body || typeof body !== "object" || Array.isArray(body) || Object.keys(body).length !== 0) return json({ message: "Обновление доступно только для фиксированного набора товаров." }, 400);
    }
    if (Object.keys(body).length !== 0) return json({ message: "Обновление доступно только для фиксированного набора товаров." }, 400);
    if (!env.IEK_API_KEY) return json({ message: "Ключ API IEK не настроен в серверном хранилище секретов." }, 503);
    const nowMs = Date.now();
    const lease = crypto.randomUUID();
    const claimed = await env.DB.prepare("UPDATE supplier_refresh_control SET lease_token = ?, lease_expires_at = ? WHERE id = 1 AND (lease_expires_at IS NULL OR lease_expires_at < ? OR lease_token IS NULL) AND (last_started_at IS NULL OR last_started_at <= ?)")
      .bind(lease, nowMs + 120000, nowMs, nowMs - 60000).run();
    if (claimed.meta?.changes !== 1) return json({ message: "Повторите обновление позже." }, 429);
    const marked = await env.DB.prepare("UPDATE supplier_refresh_control SET last_started_at = ? WHERE id = 1 AND lease_token = ?").bind(nowMs, lease).run();
    if (marked.meta?.changes !== 1) {
      await env.DB.prepare("UPDATE supplier_refresh_control SET lease_token = NULL, lease_expires_at = NULL WHERE id = 1 AND lease_token = ?").bind(lease).run();
      return json({ message: "Ограничение обновления временно недоступно. Повторите позже." }, 503);
    }
    const releaseRefresh = () => env.DB.prepare("UPDATE supplier_refresh_control SET lease_token = NULL, lease_expires_at = NULL, last_started_at = NULL WHERE id = 1 AND lease_token = ?").bind(lease).run();
    let refreshSucceeded = false;
    try {
    const cookie = await supplierSession(env.IEK_API_KEY);
    const refreshed = [];
    for (const article of ARTICLES) {
      const supplier = await readSupplier(article, cookie);
      const listingArticle = resolveOfferId(article, supplier.multiplicity);
      supplier.listingArticle = listingArticle;
      refreshed.push({ article, listingArticle, supplier });
    }
    const now = new Date().toISOString();
    await env.DB.batch(refreshed.flatMap(({ article, listingArticle, supplier }) => [
      env.DB.prepare("UPDATE operator_records SET listing_article = ?, supplier_json = ?, validation_json = 'null', updated_at = ? WHERE article = ?")
        .bind(listingArticle, JSON.stringify(supplier), now, article),
      env.DB.prepare("INSERT INTO operator_events (article, event_type, detail_json, created_at) VALUES (?, ?, ?, ?)")
        .bind(article, "supplier_refresh", JSON.stringify({ photoCount: supplier.photoCount, etimCount: supplier.etimCount }), now),
    ]));
    refreshSucceeded = true;
    const publicResponse = !signedInUser;
    return Response.json({ updated: refreshed.length, records: await listRecords(env.DB, { publicOnly: publicResponse }), ...(publicResponse ? {} : { events: await listEvents(env.DB) }) }, { headers: publicResponse ? publicRead : noStore });
    } finally {
      if (!refreshSucceeded) await releaseRefresh();
    }
  }
  if (!ARTICLES.includes(body.article)) return json({ message: "Артикул не входит в согласованный набор из пяти товаров." }, 400);
  const existing = await getRecord(env.DB, body.article);
  if (!existing) return json({ message: "Запись не найдена." }, 404);
  if (url.pathname === "/api/record/save") {
    const o = body.overrides;
    if (!o || typeof o !== "object" || Array.isArray(o)) return json({ message: "Проверьте поля карточки." }, 400);
    const clean = {};
    for (const key of ["barcode", "sellerPrice", "length", "width", "height", "weight", "wbSubjectId", "ozonCategoryId", "ozonTypeId", "ozonVat"]) {
      const v = o[key]; if (v !== undefined) clean[key] = String(v).trim().slice(0, 120);
    }
    await env.DB.prepare("UPDATE operator_records SET overrides_json = ?, validation_json = 'null', updated_at = ? WHERE article = ?")
      .bind(JSON.stringify(clean), new Date().toISOString(), body.article).run();
    await recordEvent(env.DB, body.article, "fields_saved", { fields: Object.keys(clean) });
    return json({ record: await getRecord(env.DB, body.article) });
  }
  if (url.pathname === "/api/import/dry-run") {
    if (!body.overrides || typeof body.overrides !== "object" || Array.isArray(body.overrides)) return json({ message: "Сохраните или заполните поля карточки." }, 400);
    const allowed = new Set(["all", "wb", "ozon"]);
    if (!allowed.has(body.market || "all")) return json({ message: "Выберите WB, Ozon или обе площадки." }, 400);
    existing.overrides = body.overrides;
    const validation = validateDryRun(existing, body.market || "all");
    await env.DB.prepare("UPDATE operator_records SET overrides_json = ?, validation_json = ?, updated_at = ? WHERE article = ?")
      .bind(JSON.stringify(body.overrides), JSON.stringify(validation), new Date().toISOString(), body.article).run();
    await recordEvent(env.DB, body.article, "marketplace_dry_run", { status: validation.status, scope: validation.scope, blockerCount: validation.blockers.length, submission: "disabled" });
    return json({ record: await getRecord(env.DB, body.article) });
  }
  return json({ message: "Неизвестная операция." }, 404);
}

let PAGE = "";
let FAVICON = "";

export default {
  async fetch(request, env) {
    try { return await handle(request, env); }
    catch (error) {
      const id = crypto.randomUUID();
      console.error(JSON.stringify({ event: "operator_request_failed", requestId: id, path: new URL(request.url).pathname, message: String(error?.message || "unknown").slice(0, 250) }));
      return json({ message: "Операция не завершилась. Сохранённые данные оставлены без изменений.", requestId: id }, 502);
    }
  },
  withAssets(page, favicon) { PAGE = page; FAVICON = favicon; return this; },
};
