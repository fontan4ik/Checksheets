import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = "/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/outputs/666042e4-3b0d-4e69-a5e3-116486d11207/Прайс-лист МЮ - ссылки на фото.xlsx";
const specs = [
  { sheet: "Общий прайс-лист", start: "AV", end: "BH", lastRow: 1672 },
  { sheet: "Светодиодные лампы", start: "BI", end: "BU", lastRow: 371 },
  { sheet: "Светильники", start: "BC", end: "BO", lastRow: 1095 },
  { sheet: "Лампы традиционных технологий", start: "AX", end: "BJ", lastRow: 98 },
  { sheet: "Светильники с БАП", start: "BB", end: "BN", lastRow: 38 },
  { sheet: "Декоративный свет", start: "AY", end: "BK", lastRow: 74 },
];

function extractUrl(formula) {
  const match = String(formula || "").match(/^=HYPERLINK\("((?:[^"]|"")*)"/i);
  return match ? match[1].replace(/""/g, '"') : null;
}

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
let totalLinks = 0;
for (const spec of specs) {
  const sheet = workbook.worksheets.getItem(spec.sheet);
  const range = sheet.getRange(spec.start + "2:" + spec.end + spec.lastRow);
  const formulas = range.formulas;
  const values = formulas.map(row => row.map(extractUrl));
  const links = values.flat().filter(value => /^https:\/\//i.test(String(value || ""))).length;
  totalLinks += links;
  range.clear({ applyTo: "contents" });
  range.values = values;
  range.format.numberFormat = "@";
  range.format.font.color = "#0563C1";
  range.format.horizontalAlignment = "left";
  range.format.verticalAlignment = "center";
  range.format.wrapText = false;
  console.log(JSON.stringify({ sheet: spec.sheet, links }));
}

workbook.recalculate();
const preview = await workbook.render({
  sheetName: "Общий прайс-лист",
  range: "AV1:BH8",
  scale: 1.25,
  format: "png",
});
await fs.writeFile(
  "/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/test/photo_enrichment_666042e4-3b0d-4e69-a5e3-116486d11207/final_preview.png",
  new Uint8Array(await preview.arrayBuffer()),
);
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(workbookPath);

const saved = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
const checks = [];
let savedLinks = 0;
for (const spec of specs) {
  const sheet = saved.worksheets.getItem(spec.sheet);
  const range = sheet.getRange(spec.start + "2:" + spec.end + spec.lastRow);
  const values = range.values;
  const formulas = range.formulas;
  const links = values.flat().filter(value => /^https:\/\//i.test(String(value || ""))).length;
  const remainingFormulas = formulas.flat().filter(Boolean).length;
  savedLinks += links;
  checks.push({ sheet: spec.sheet, links, remainingFormulas });
}
if (savedLinks !== totalLinks) throw new Error("Saved URL count did not match written URL count");
if (checks.some(item => item.remainingFormulas > 0)) throw new Error("Photo URL ranges still contain formulas");
console.log("FINAL_URL_CHECK " + JSON.stringify({ totalLinks, checks }));
