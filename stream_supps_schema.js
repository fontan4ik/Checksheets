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
  wbFeronMoscowTotal: "ФБС ФЕРОН МОСКВА",
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
    const isOccurrenceDefinition = definition && !Array.isArray(definition) && typeof definition === "object";
    const names = isOccurrenceDefinition
      ? [definition.header]
      : (Array.isArray(definition) ? definition : [definition]);
    const occurrence = isOccurrenceDefinition ? Number(definition.occurrence || 1) : null;
    if (occurrence !== null && (!Number.isInteger(occurrence) || occurrence < 1)) {
      throw new Error(
        `Лист "${sheetName}": для поля "${field}" указано некорректное occurrence: ${definition.occurrence}`,
      );
    }
    const wanted = new Set(names.map(normalizeStreamSuppsHeader));
    const matches = normalizedHeaders
      .map((header, index) => wanted.has(header) ? index + 1 : 0)
      .filter(Boolean);

    if (matches.length === 0) {
      throw new Error(
        `Лист "${sheetName}": для поля "${field}" не найден заголовок "${names.join(" / ")}"`,
      );
    }
    if (occurrence !== null) {
      if (matches.length < occurrence) {
        throw new Error(
          `Лист "${sheetName}": заголовок для поля "${field}" найден ${matches.length} раз(а), ` +
          `но требуется occurrence ${occurrence}`,
        );
      }
      columns[field] = matches[occurrence - 1];
      return;
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
