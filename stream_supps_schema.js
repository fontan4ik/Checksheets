/**
 * Единая схема листа StreamSupps для Apps Script и локальных Node-скриптов.
 *
 * Колонка всегда определяется по видимому заголовку. Числовой индекс,
 * возвращаемый resolver-ом, является только техническим адресом уже найденной
 * колонки и никогда не используется как fallback.
 */
const STREAM_SUPPS_HEADERS = Object.freeze({
  offerId: "Артикул продавца",
  model: "Артикул производителя",
  brand: "brand",
  ozonSku: "SKU OZON",
  chrtId: ["chrtid", "chrlid"],
  feronMsk: "FER MSK",
  feronSmr: "FER SMR",
  feronNsb: "FER NSB",
  feronEkb: "FER EKB",
  podorozhnikFbs: "ПОДОРОЖНИК ФБС",
  feronFbs: "ФЕРОН ФБС",
  feronNsbFbs: "НОВОСИБИРСК ФЕРОН",
  feronEkbFbs: "ЕКБ Ферон",
  etmNsb: "ETM NSB",
  etmSmr: "ЭТМ САМАРА",
  etmCode: "CODES",
  rsSmr: "RS SMR",
  reserve: "РЕЗЕРВ",
  wbVoltmirTotal: "WB ВОЛЬТМИР ИТОГ",
});

function normalizeStreamSuppsHeader(value) {
  return String(value === undefined || value === null ? "" : value)
    .trim()
    .toLowerCase()
    .replace(/ё/g, "е");
}

function resolveStreamSuppsColumns(headers, schema, sheetName = "StreamSupps") {
  const normalizedHeaders = (headers || []).map(normalizeStreamSuppsHeader);
  const columns = {};

  Object.entries(schema).forEach(([field, definition]) => {
    const names = Array.isArray(definition) ? definition : [definition];
    const wanted = new Set(names.map(normalizeStreamSuppsHeader));
    const matches = normalizedHeaders
      .map((header, index) => wanted.has(header) ? index + 1 : 0)
      .filter(Boolean);

    if (matches.length === 0) {
      throw new Error(
        `Лист "${sheetName}": для поля "${field}" не найден заголовок "${names.join(" / ")}"`,
      );
    }
    if (matches.length !== 1) {
      throw new Error(
        `Лист "${sheetName}": заголовок для поля "${field}" дублируется в колонках ${matches.join(", ")}`,
      );
    }

    columns[field] = matches[0];
  });

  return columns;
}

if (typeof module !== "undefined") {
  module.exports = {
    STREAM_SUPPS_HEADERS,
    normalizeStreamSuppsHeader,
    resolveStreamSuppsColumns,
  };
}
