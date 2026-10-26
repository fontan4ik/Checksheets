import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const file = "/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/outputs/666042e4-3b0d-4e69-a5e3-116486d11207/Прайс-лист МЮ - ссылки на фото.xlsx";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(file));
for (const [sheetName, rangeAddress] of [
  ["Общий прайс-лист", "AV1:BH8"],
  ["Светильники", "A1:F8"],
]) {
  const sheet = workbook.worksheets.getItem(sheetName);
  const range = sheet.getRange(rangeAddress);
  console.log(JSON.stringify({ sheetName, rangeAddress, values: range.values }));
  const image = await workbook.render({ sheetName, range: rangeAddress, scale: 1, format: "png" });
  await fs.writeFile(
    `/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/test/photo_enrichment_666042e4-3b0d-4e69-a5e3-116486d11207/verify_${sheetName === "Общий прайс-лист" ? "links" : "photos"}.png`,
    new Uint8Array(await image.arrayBuffer()),
  );
}
