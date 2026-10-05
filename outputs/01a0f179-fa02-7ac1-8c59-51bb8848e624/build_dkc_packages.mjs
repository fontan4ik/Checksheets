import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = new URL("./", import.meta.url).pathname;
const resultPath = "/tmp/dkc_package_fetch_result.json";
const result = JSON.parse(await fs.readFile(resultPath, "utf8"));

const keyFor = (article) => String(article ?? "").toUpperCase().replace(/[^A-Z0-9]/g, "");
const packageByArticle = new Map();
const sourceCounts = { ETM: 0, RS: 0, Previous: 0, Missing: 0 };

for (const articleKey of Object.keys(result.articles)) {
  const etm = result.etm[articleKey];
  if (etm?.package) {
    packageByArticle.set(articleKey, etm.package);
    sourceCounts.ETM += 1;
    continue;
  }
  const rsRecords = result.rs[articleKey] ?? [];
  const rsPackage = rsRecords.find((record) => record.package)?.package;
  if (rsPackage) {
    packageByArticle.set(articleKey, rsPackage);
    sourceCounts.RS += 1;
    continue;
  }
  if (result.old_packages[articleKey] !== undefined && result.old_packages[articleKey] !== null && result.old_packages[articleKey] !== "") {
    packageByArticle.set(articleKey, String(result.old_packages[articleKey]));
    sourceCounts.Previous += 1;
    continue;
  }
  packageByArticle.set(articleKey, "нет данных в API");
  sourceCounts.Missing += 1;
}

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("DKC остатки");
sheet.showGridLines = false;

const headers = ["Артикул DKC", "ETM Самара", "РС Самара", "РС Москва", "Кратность упаковки"];
const rows = result.source_rows.map((row) => {
  const article = String(row["Артикул DKC"] ?? "").trim();
  return [
    article,
    Number(row["ETM Самара"] ?? 0),
    Number(row["РС Самара"] ?? 0),
    Number(row["РС Москва"] ?? 0),
    packageByArticle.get(keyFor(article)) ?? "нет данных в API",
  ];
});
const endRow = 6 + rows.length;

sheet.getRange("A2").values = [["DKC — остатки по складам"]];
sheet.mergeCells("A2:E2");
sheet.getRange("A3").values = [["Срез остатков: 03.10.2026 · проверка упаковки: 05.10.2026"]];
sheet.mergeCells("A3:E3");
sheet.getRange("A4").values = [[
  `Включены ${rows.length.toLocaleString("ru-RU")} артикулов с остатком на одном из складов. Кратность: ETM (gdsPacks/minPack); резерв — Русский Свет (PRIMARY_UOM/ITEMS_PER_UNIT). «нет данных в API» означает, что источники не вернули кратность и не подтверждает отсутствие упаковки. Остатки сохранены из среза 03.10.2026.`,
]];
sheet.mergeCells("A4:E4");
sheet.getRange("A6:E6").values = [headers];
sheet.getRange(`A7:E${endRow}`).values = rows;

const table = sheet.tables.add(`A6:E${endRow}`, true, "DKCStocksTable");
table.style = "TableStyleMedium2";
table.showFilterButton = true;

sheet.getRange("A2:E2").format = {
  fill: "#FFFFFF",
  font: { name: "Arial", size: 16, bold: true, color: "#17365D" },
  verticalAlignment: "center",
};
sheet.getRange("A2:E2").format.rowHeight = 28;
sheet.getRange("A3:E3").format = {
  fill: "#FFFFFF",
  font: { name: "Arial", size: 10, color: "#666666" },
  verticalAlignment: "center",
};
sheet.getRange("A3:E3").format.rowHeight = 22;
sheet.getRange("A4:E4").format = {
  fill: "#F4F7FB",
  font: { name: "Arial", size: 9, color: "#404040" },
  wrapText: true,
  verticalAlignment: "center",
};
sheet.getRange("A4:E4").format.rowHeight = 44;
sheet.getRange("A6:E6").format = {
  fill: "#1F4E78",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  verticalAlignment: "center",
  wrapText: true,
};
sheet.getRange("A6:E6").format.rowHeight = 30;
sheet.getRange(`A7:E${endRow}`).format = {
  font: { name: "Arial", size: 10, color: "#202020" },
  verticalAlignment: "center",
};
sheet.getRange(`A7:A${endRow}`).format.numberFormat = "@";
sheet.getRange(`B7:D${endRow}`).format.numberFormat = "#,##0";
sheet.getRange(`E7:E${endRow}`).format.wrapText = false;
sheet.getRange(`A1:A${endRow}`).format.columnWidth = 24;
sheet.getRange(`B1:D${endRow}`).format.columnWidth = 16;
sheet.getRange(`E1:E${endRow}`).format.columnWidth = 24;
sheet.freezePanes.freezeRows(6);

workbook.recalculate();
const preview = await workbook.render({ sheetName: "DKC остатки", range: "A1:E15", scale: 1, format: "png" });
await fs.writeFile("/tmp/dkc_packages_preview.png", new Uint8Array(await preview.arrayBuffer()));

const inspection = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 2500,
  tableMaxRows: 8,
  tableMaxCols: 5,
});
const inspectionText = typeof inspection === "string" ? inspection : (inspection.ndjson ?? JSON.stringify(inspection));
await fs.writeFile(`${outputDir}DKC_остатки_по_складам.xlsx.inspect.ndjson`, inspectionText, "utf8");

const outputPath = `${outputDir}DKC_остатки_по_складам.xlsx`;
const output = await SpreadsheetFile.exportXlsx(workbook);
const tempPath = "/tmp/DKC_остатки_по_складам_updated.xlsx";
await output.save(tempPath);
await fs.rename(tempPath, outputPath);
const stat = await fs.stat(outputPath);
console.log(JSON.stringify({
  outputPath,
  rows: rows.length,
  packageSources: sourceCounts,
  sizeBytes: stat.size,
  previewPath: "/tmp/dkc_packages_preview.png",
}, null, 2));
