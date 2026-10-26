import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const out = path.join(root, 'outputs/certificate_export_20261026');
const data = JSON.parse(await fs.readFile(path.join(here, 'export_data.json'), 'utf8'));
await fs.mkdir(out, {recursive: true});
const wb = Workbook.create();
const widths = [23, 66, 33, 19, 62, 35, 23, 26, 60, 65, 75, 65, 65, 60, 35, 30];
const col = i => String.fromCharCode(65 + i);
const shorten = (s, limit=700) => {
  if (typeof s !== 'string' || s.length <= limit) return s;
  const cut = s.lastIndexOf('\n', limit);
  return s.slice(0, cut > limit / 2 ? cut : limit) + '\nДополнительные материалы сохранены в журнале проверки.';
};

for (const [platform, rawRows] of Object.entries(data.sheets)) {
  const sheet = wb.worksheets.add(platform);
  sheet.showGridLines = false;
  sheet.tabColor = platform === 'Ozon' ? '#2450A4' : '#6D3588';
  const rows = rawRows.map(row => row.map((value, i) => [8,9,10,13].includes(i) ? shorten(value) : value));
  const end = rows.length + 8;
  const range = sheet.getRange(`A1:P${end}`);
  range.format.font = {name:'Arial', size:10, color:'#172B4D'};
  range.format.verticalAlignment = 'top';
  range.format.rowHeight = 18;
  for (let i=0; i<widths.length; i++) sheet.getRange(`${col(i)}1:${col(i)}${end}`).format.columnWidth = widths[i];
  sheet.getRange('A2').values = [[`${platform}: товары без действующего одобренного документа`]];
  sheet.getRange('A2').format.font = {name:'Arial', size:14, bold:true, color:'#172B4D'};
  sheet.getRange('A2:P2').format.rowHeight = 24;
  const checked = platform === 'Ozon' ? data.checked.ozon_certificates : data.checked.wb_catalog;
  sheet.getRange('A3').values = [[`Проверка API: ${checked.slice(0,19).replace('T',' ')} UTC. Список: ${rows.length} карточек, ${data.counts[platform].unique_articles} уникальных артикулов.`]];
  sheet.getRange('A4').values = [[platform === 'Ozon'
    ? `Архивных карточек в списке: ${data.counts.Ozon.archived}. Товары с одобренным действующим документом исключены; полнота комплекта по всем регламентам не оценивалась.`
    : 'Текущий каталог без корзины. Включены проверка, отказы и признак «Документы не требуются»; обоснованность освобождения не подтверждена.']];
  sheet.getRange('A5').values = [['Статусы площадок обновлены 26.10.2026. Причины поиска и проверки применимости взяты из накопленных материалов по 24.10.2026.']];
  sheet.getRange('A6').values = [[platform === 'WB'
    ? 'WB: отказное письмо не загружают. При подтверждённом освобождении используют признак «Документы не требуются».'
    : 'Отказное письмо: необходимость проверяется по точной модели и обязательным требованиям. Оно не заменяет обязательный сертификат или декларацию.']];
  sheet.getRange('A3:P6').format.font = {name:'Arial', size:10, color:'#526477'};
  sheet.getRange('A3:P6').format.wrapText = false;
  sheet.getRange('A7').values = [[`Правила площадки: ${data.platform_docs[platform]}`]];
  sheet.getRange('A7:P7').format.font = {name:'Arial', size:10, color:'#526477'};
  sheet.getRange('A8:P8').values = [data.headers];
  sheet.getRange(`A9:P${end}`).values = rows.map(row => row.map(v => typeof v === 'string' && v.startsWith('=') ? `'${v}` : v));
  sheet.getRange(`A9:P${end}`).format.wrapText = true;
  sheet.getRange(`A9:A${end}`).setNumberFormat('@');
  sheet.getRange(`F9:H${end}`).setNumberFormat('@');
  // Reason and identifiers remain immediately visible; evidence is to the right.
  for (let i=0; i<rows.length; i++) {
    const lines = Math.max(...rows[i].map((v,j) => String(v ?? '').split('\n').reduce((n,line) => n + Math.max(1,Math.ceil(line.length / Math.max(12,widths[j]-3))), 0)));
    sheet.getRange(`A${i+9}:P${i+9}`).format.rowHeight = Math.min(409, Math.max(48, lines * 13 + 8));
  }
  const table = sheet.tables.add(`A8:P${end}`, true, `${platform}MissingDocuments`);
  table.showFilterButton = true;
  table.style = 'TableStyleMedium2';
  sheet.getRange('A8:P8').format = {fill:'#243B53', font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'}, horizontalAlignment:'center',verticalAlignment:'center',wrapText:true,rowHeight:32};
  sheet.getRange(`C9:C${end}`).conditionalFormats.add('containsText',{text:'отклон',format:{fill:'#FDE8E7',font:{color:'#9B1C1C'}}});
  sheet.getRange(`C9:C${end}`).conditionalFormats.add('containsText',{text:'На проверке',format:{fill:'#FFF2CC',font:{color:'#795500'}}});
  sheet.freezePanes.freezeRows(8);
  sheet.freezePanes.freezeColumns(1);
}
wb.recalculate();
for (const platform of ['Ozon','WB']) {
  const result = await wb.inspect({kind:'region',sheetId:platform,range:'A8:F11',maxChars:1800,tableMaxRows:4,tableMaxCols:6});
  console.log(result.ndjson);
  const img = await wb.render({sheetName:platform,range:'A2:E11',scale:1,format:'png'});
  await fs.writeFile(path.join(here, `${platform}_preview.png`),new Uint8Array(await img.arrayBuffer()));
}
const errors = await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!',options:{useRegex:true,maxResults:10},maxChars:1000});
console.log(errors.ndjson);
const filename = path.join(out,'Товары_без_подтверждённых_документов_Ozon_WB_2026-10-26.xlsx');
await (await SpreadsheetFile.exportXlsx(wb)).save(filename);
console.log(JSON.stringify({file:filename,counts:data.counts}));
