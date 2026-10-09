import { unzipSync } from "file:///Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/sites/iek-operator/node_modules/fflate/lib/node.cjs";
import { SaxesParser } from "file:///Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/sites/iek-operator/node_modules/saxes/saxes.js";

export const REQUIRED_HEADERS = new Set(["артикул", "артикул iek", "артикул поставщика", "номенклатурный номер", "код товара", "sku", "article", "vendor code"]);
const MAX_BYTES = 5 * 1024 * 1024;
const MAX_ROWS = 5000;
const MAX_COLUMNS = 64;
const MAX_CELL_TEXT = 512;
const ARTICLE_PATTERN = /^[A-Za-zА-Яа-яЁё0-9]+(?:[-_][A-Za-zА-Яа-яЁё0-9]+)*$/;
const MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
const PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships";
const MAX_UNCOMPRESSED = 16 * 1024 * 1024;

const asText = (value) => String(value ?? "").replace(/\uFEFF/g, "").trim();
const normalizeHeader = (value) => asText(value).toLocaleLowerCase("ru-RU").replace(/ё/g, "е").replace(/[._-]+/g, " ").replace(/\s+/g, " ");

function parseXml(source) {
  const stack = [];
  const root = { name: "#document", attrs: {}, children: [], text: "" };
  const parser = new SaxesParser({ xmlns: true });
  parser.on("opentag", (tag) => {
    const node = { name: tag.local, namespace: tag.uri, attrs: Object.fromEntries(Object.entries(tag.attributes).map(([key, value]) => [key, value.value])), children: [], text: "" };
    (stack.at(-1) || root).children.push(node);
    stack.push(node);
  });
  parser.on("text", (text) => { if (stack.length) stack.at(-1).text += text; });
  parser.on("cdata", (text) => { if (stack.length) stack.at(-1).text += text; });
  parser.on("closetag", () => { stack.pop(); });
  parser.write(source).close();
  return root.children[0] || root;
}

const descendants = (node, name, namespace = MAIN_NS) => {
  const found = [];
  for (const child of node.children || []) {
    if (child.name === name && (!namespace || child.namespace === namespace)) found.push(child);
    found.push(...descendants(child, name, namespace));
  }
  return found;
};
const child = (node, name, namespace = MAIN_NS) => (node.children || []).find((entry) => entry.name === name && (!namespace || entry.namespace === namespace));

function decodeXmlText(value) {
  return value.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos);/gi, (_match, entity) => {
    const named = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };
    if (entity[0] !== "#") return named[entity.toLowerCase()] || "";
    const code = entity[1].toLowerCase() === "x" ? Number.parseInt(entity.slice(2), 16) : Number.parseInt(entity.slice(1), 10);
    try { return String.fromCodePoint(code); } catch { return ""; }
  });
}

function excelColumnToIndex(value) {
  const match = value.match(/^[A-Z]+/i)?.[0];
  if (!match) return -1;
  let result = 0;
  for (const letter of match.toUpperCase()) result = result * 26 + letter.charCodeAt(0) - 64;
  return result - 1;
}

function sharedStringNodes(xml) {
  const root = parseXml(xml);
  return descendants(root, "si").map((item) => descendants(item, "t").map((part) => part.text).join(""));
}

function parseRows(xml, sharedStrings) {
  const root = parseXml(xml);
  const rows = [];
  const sheetData = descendants(root, "sheetData")[0];
  if (!sheetData) throw new Error("Workbook worksheet data is missing.");
  for (const rowNode of (sheetData.children || []).filter((entry) => entry.name === "row")) {
    const rowNumber = Number(rowNode.attrs.r || rows.length + 1);
    if (!Number.isSafeInteger(rowNumber) || rowNumber < 1 || rowNumber > MAX_ROWS + 20) throw new Error(`Workbook row number ${rowNode.attrs.r} is out of bounds.`);
    const values = [];
    for (const cell of (rowNode.children || []).filter((entry) => entry.name === "c")) {
      const index = excelColumnToIndex(cell.attrs.r || "");
      if (index < 0 || index >= MAX_COLUMNS) throw new Error("Workbook has too many columns.");
      const type = cell.attrs.t || "n";
      const valueNode = child(cell, "v");
      let value = valueNode?.text ?? "";
      if (type === "s") value = sharedStrings[Number(value)] ?? "";
      else if (type === "inlineStr") value = descendants(cell, "t").map((part) => part.text).join("");
      else if (type === "str") value = decodeXmlText(value);
      value = asText(value);
      if (value.length > MAX_CELL_TEXT) throw new Error(`Cell in row ${rowNumber} exceeds the allowed length.`);
      values[index] = value;
    }
    rows.push({ rowNumber, values });
    if (rows.length > MAX_ROWS + 1) throw new Error(`Workbook exceeds the ${MAX_ROWS}-row limit.`);
  }
  return rows;
}

function resolveWorksheetPath(workbook, rels) {
  const workbookRoot = parseXml(workbook);
  const sheet = descendants(workbookRoot, "sheet")[0];
  if (!sheet) throw new Error("Workbook has no worksheet.");
  const relId = Object.entries(sheet.attrs).find(([name]) => name === "id" || name.endsWith(":id"))?.[1];
  const relRoot = parseXml(rels);
  const relation = descendants(relRoot, "Relationship", PKG_REL_NS).find((entry) => entry.attrs.Id === relId);
  const target = relation?.attrs.Target;
  if (!target || relation.attrs.TargetMode === "External") throw new Error("Workbook worksheet relationship is invalid.");
  const base = target.startsWith("/") ? "" : "xl/";
  const cleaned = target.replace(/^\//, "");
  const parts = [];
  for (const part of `${base}${cleaned}`.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") { if (!parts.length) throw new Error("Workbook worksheet path is invalid."); parts.pop(); }
    else parts.push(part);
  }
  return parts.join("/");
}

function parseSpreadsheet(bytes) {
  let files;
  try { files = unzipSync(new Uint8Array(bytes), { filter: (file) => !file.name.startsWith("../") && !file.name.startsWith("/") }); }
  catch { throw new Error("The file is not a valid .xlsx workbook."); }
  const entries = Object.entries(files);
  const totalSize = entries.reduce((sum, [, content]) => sum + content.length, 0);
  if (!entries.length || totalSize > MAX_UNCOMPRESSED) throw new Error("Workbook expands beyond the allowed size.");
  for (const required of ["[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"]) if (!files[required]) throw new Error("The file is not a valid .xlsx workbook.");
  const text = (name) => files[name] ? new TextDecoder("utf-8", { fatal: true }).decode(files[name]) : "";
  const sharedStrings = files["xl/sharedStrings.xml"] ? sharedStringNodes(text("xl/sharedStrings.xml")) : [];
  const worksheetPath = resolveWorksheetPath(text("xl/workbook.xml"), text("xl/_rels/workbook.xml.rels"));
  if (!files[worksheetPath]) throw new Error("Workbook worksheet is missing.");
  return parseRows(text(worksheetPath), sharedStrings);
}

function validateRows(rows) {
  if (!rows.length) throw new Error("No rows were found in the input.");
  const nonEmptyRows = rows.filter((row) => row.values.some((value) => asText(value) !== ""));
  if (!nonEmptyRows.length) throw new Error("No non-empty rows were found in the input.");
  let header;
  let column;
  for (const row of nonEmptyRows.slice(0, Math.min(5, nonEmptyRows.length))) {
    const matches = row.values.map(normalizeHeader).map((value, index) => REQUIRED_HEADERS.has(value) ? index : -1).filter((index) => index >= 0);
    if (matches.length > 1) throw new Error(`Multiple article columns found in row ${row.rowNumber}.`);
    if (matches.length === 1) {
      if (header) throw new Error("Multiple article-header rows found in the first five rows.");
      header = row;
      column = matches[0];
    }
  }
  if (!header) {
    const candidates = nonEmptyRows.filter((row) => row.values.filter((value) => asText(value) !== "").length > 1);
    if (candidates.length) throw new Error("Could not determine the article column. Add a clear header such as ‘Артикул’ or ‘Артикул IEK’. ");
    column = nonEmptyRows[0].values.findIndex((value) => asText(value) !== "");
    header = { rowNumber: nonEmptyRows[0].rowNumber - 1, values: [] };
  }
  const errors = [];
  const articles = [];
  const duplicates = [];
  const seen = new Set();
  for (const row of nonEmptyRows) {
    if (row.rowNumber <= header.rowNumber) continue;
    const value = asText(row.values[column]);
    if (!value) continue;
    if (!ARTICLE_PATTERN.test(value)) errors.push({ lines: [row.rowNumber], value, message: "Артикул должен содержать только буквы, цифры, дефисы и подчёркивания." });
    else if (seen.has(value.toUpperCase())) duplicates.push(value);
    else { seen.add(value.toUpperCase()); articles.push(value); }
  }
  if (!articles.length && !errors.length) throw new Error("No supplier article values were found in the selected column.");
  return { articles, duplicates, errors, columnIndex: column, headerRow: header.values.length ? header.rowNumber : null };
}

export async function parseArticleUpload(file) {
  if (!file || typeof file.arrayBuffer !== "function") throw new Error("Upload one .xlsx file.");
  if (file.size > MAX_BYTES) throw new Error("The Excel file exceeds the 5 MB limit.");
  if (file.type && file.type !== "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" && file.type !== "application/octet-stream") throw new Error("Only .xlsx workbooks are supported.");
  return validateRows(parseSpreadsheet(await file.arrayBuffer()));
}

export function parseManualArticles(values) {
  if (!Array.isArray(values) || values.length > MAX_ROWS) throw new Error("Submit between 1 and 5000 article lines.");
  const articles = [];
  const duplicates = [];
  const errors = [];
  const seen = new Set();
  values.forEach((value, index) => {
    const item = asText(value);
    if (!item) return;
    if (item.length > MAX_CELL_TEXT || !ARTICLE_PATTERN.test(item)) errors.push({ lines: [index + 1], value: item.slice(0, MAX_CELL_TEXT), message: "Артикул должен содержать только буквы, цифры, дефисы и подчёркивания." });
    else if (seen.has(item.toUpperCase())) duplicates.push(item);
    else { seen.add(item.toUpperCase()); articles.push(item); }
  });
  if (!articles.length && !errors.length) throw new Error("Enter at least one supplier article.");
  return { articles, duplicates, errors };
}
