import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const here=path.dirname(new URL(import.meta.url).pathname);
const d=JSON.parse(await fs.readFile(path.join(here,'matched.json'),'utf8'));
const out=path.resolve(here,'../../outputs/etm_matrix_20261021');
await fs.mkdir(out,{recursive:true});
const wb=Workbook.create();
const m=wb.worksheets.add('Матрица');const b=wb.worksheets.add('По брендам');
const last=8+d.rows.length;
m.getRange(`A8:S${last}`).values=[d.headers,...d.rows];
m.getRange('A2').values=[['Сопоставление Ozon и ЭТМ · 21.10.2026']];
m.getRange('A3').values=[[`Товаров Ozon: ${d.total.toLocaleString('ru-RU')}; с кодами ЭТМ: ${d.bound_products.toLocaleString('ru-RU')}. Проблемные: 1 — нужна проверка, 0 — однозначно.`]];
m.getRange('A4').values=[['Остатки в единицах ЭТМ, без пересчёта в комплекты Ozon. Пусто — нет данных, 0 — нулевой остаток.']];
m.getRange('A5').values=[['Самара: FTP /from_etm/13/price.csv · дата файла 21.10.2026 02:06:21 UTC']];
m.getRange('A6').values=[['Москва: FTP /from_etm/14/price.csv · дата файла 20.10.2026 09:46:13 UTC (последний доступный на FTP)']];
m.getRange(`A8:S${last}`).format.font={name:'Arial',size:10,color:'#172B4D'};
m.getRange(`A9:S${last}`).format.rowHeight=30;
m.getRange(`A8:S${last}`).format.verticalAlignment='center';
const widths={A:30,B:24,C:17,D:20,E:20,F:16,G:29,H:48,I:32,J:24,K:16,L:85,M:85,N:22,O:22,P:18,Q:35,R:38,S:85};
for(const [col,width] of Object.entries(widths))m.getRange(`${col}8:${col}${last}`).format.columnWidth=width;
for(const col of ['A','C','I','N','O','Q'])m.getRange(`${col}9:${col}${last}`).setNumberFormat('@');
m.getRange(`D9:E${last}`).setNumberFormat('#,##0.###');
m.getRange(`G9:M${last}`).format.wrapText=true;m.getRange(`Q9:S${last}`).format.wrapText=true;
m.getRange(`F9:F${last}`).setNumberFormat('0');
m.tables.add(`A8:S${last}`,true,'OzonEtmMatrix');
m.getRange('A8:S8').format={fill:'#254A70',font:{name:'Arial',bold:true,color:'#FFFFFF',size:10},wrapText:true,rowHeight:34,horizontalAlignment:'center'};
m.getRange(`F9:F${last}`).conditionalFormats.add('cellIs',{operator:'equal',formula:1,format:{fill:'#FFF2CC',font:{color:'#7F6000'}}});
m.freezePanes.freezeRows(8);m.freezePanes.freezeColumns(3);
m.showGridLines=false;m.tabColor='#254A70';

const bl=8+d.brand_rows.length;
b.getRange(`A8:F${bl}`).values=[['Бренд Ozon','Всего товаров','Однозначно','Нет в FTP','Проверить бренд','Несколько / конфликт'],...d.brand_rows];
b.getRange('A2').values=[['Покрытие матрицы по брендам']];
b.getRange('A3').values=[[`Источник: Ozon Seller API /v3/product/list, ALL и ARCHIVED; /v3/product/info/list; /v4/product/info/attributes.`]];
b.getRange('A4').values=[[`Выгрузка Ozon: ${d.api_at}; ALL — ${d.total-d.archived}, ARCHIVED — ${d.archived}.`]];
b.getRange('A5').values=[[`FTP: Самара — ${d.source_counts['Самара'].rows.toLocaleString('ru-RU')} строк, Москва — ${d.source_counts['Москва'].rows.toLocaleString('ru-RU')} строк.`]];
b.getRange('A6').values=[['Сравнение по артикулу и бренду. Точный артикул имеет приоритет; затем удаляется один конечный суффикс -число.']];
b.getRange(`A8:F${bl}`).format.font={name:'Arial',size:10,color:'#172B4D'};
b.getRange(`A8:F${bl}`).format.rowHeight=25;b.getRange(`A8:F${bl}`).format.verticalAlignment='center';
b.getRange(`A8:A${bl}`).format.columnWidth=30;b.getRange(`B8:F${bl}`).format.columnWidth=22;
b.getRange(`B9:F${bl}`).setNumberFormat('#,##0');
b.tables.add(`A8:F${bl}`,true,'EtmBrandCoverage');
b.getRange('A8:F8').format={fill:'#254A70',font:{name:'Arial',bold:true,color:'#FFFFFF',size:10},wrapText:true,rowHeight:34,horizontalAlignment:'center'};
const notes=[
 'Наш бренд из Ozon сохранён в матрице и сводке. Пустые бренды оставлены пустыми.',
 'IN HOME = INHOME; Jazzway = JazzWay; Feron = FERON; Фаzа / ФАЗА = ФАZA.',
 'Navigator / ОНЛАЙТ = Navigator Group; Systeme Electric = SE Systeme; Schneider Electric = SE (Schneider).',
 'DEKraft = SE Dekraft; Legrand = Legrand Euro. Регистр, пробелы и типографские варианты дефиса не различаются.',
 'Все найденные коды привязаны, включая спорные. Несколько кодов одного товара показаны отдельными строками с остатками каждого.',
 '«Нет в FTP» означает отсутствие совпадения по этим правилам в двух прайсах, а не отсутствие товара во всём каталоге ЭТМ.',
 'В колонках «Коды-кандидаты» и «Производители кандидатов» показаны совпавшие артикулы, требующие проверки.',
 'Проблемные = 1: другой или отсутствующий бренд, несколько кодов, конфликт данных либо отсутствие совпадения в FTP. Иначе 0.',
 `Матрица: ${d.output_rows} строк для ${d.total} уникальных товаров. Сводка считает товары один раз, без повторов по кодам.`,
 'Остатки перенесены из поля «Количество»; единица указана в колонке «Единица ЭТМ». Склады не суммируются.',
 'Дата последней FTP-выгрузки: Самара 21.10.2026, Москва 20.10.2026. Проверено непосредственно на FTP 21.10.2026.',
];
b.getRange(`A${bl+3}:A${bl+2+notes.length}`).values=notes.map(n=>[n]);
b.getRange(`A${bl+3}:F${bl+2+notes.length}`).format.rowHeight=24;
b.showGridLines=false;b.freezePanes.freezeRows(8);
for(const s of [m,b]){
 s.getRange('A2').format.font={name:'Arial',size:14,bold:true,color:'#172B4D'};
 s.getRange('A2:R6').format.rowHeight=24;
 s.getRange('A3:R6').format.font={name:'Arial',size:10,color:'#43566C'};
}
wb.recalculate();
console.log((await wb.inspect({kind:'region',sheetId:'Матрица',range:'A8:J12',maxChars:2500,tableMaxRows:5,tableMaxCols:10})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',options:{useRegex:true,maxResults:10},maxChars:500})).ndjson);
for(const [sheet,file,range] of [['Матрица','matrix-preview.png','A1:G16'],['По брендам','brands-preview.png','A1:F16']]){
 const preview=await wb.render({sheetName:sheet,range,scale:1.3,format:'png'});
 await fs.writeFile(path.join(out,file),new Uint8Array(await preview.arrayBuffer()));
}
const file=path.join(out,'Сопоставление_Ozon_ЭТМ_21.10.2026.xlsx');
await (await SpreadsheetFile.exportXlsx(wb)).save(file);
console.log(JSON.stringify({output:file,rows:d.total,stats:d.stats}));
