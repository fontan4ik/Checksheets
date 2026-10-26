"""Verify the exported XLSX rows and identifiers without an authoring library."""
import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FILE = ROOT / 'outputs/certificate_export_20261026/Товары_без_подтверждённых_документов_Ozon_WB_2026-10-26.xlsx'
data = json.loads((HERE / 'export_data.json').read_text())
ns = {'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
with zipfile.ZipFile(FILE) as z:
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    names = [e.attrib['name'] for e in wb.find('m:sheets', ns)]
    assert names == ['Ozon', 'WB'], names
    strings = []
    if 'xl/sharedStrings.xml' in z.namelist():
        strings = [''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml'))]
    def value(c):
        v = c.find('m:v', ns)
        if c.get('t') == 's':
            return strings[int(v.text)]
        if c.get('t') == 'inlineStr':
            return ''.join(c.find('m:is', ns).itertext())
        return v.text if v is not None else ''
    checks = {}
    for i, name in enumerate(names, 1):
        doc = ET.fromstring(z.read(f'xl/worksheets/sheet{i}.xml'))
        byrow = {}
        for row in doc.findall('m:sheetData/m:row', ns):
            assert all(c.get('t') != 'e' for c in row), 'Excel error cell'
            byrow[int(row.get('r'))] = {c.get('r'):value(c) for c in row}
        expected = data['sheets'][name]
        actual_ids = []
        for j, row in enumerate(expected, 9):
            cells = byrow[j]
            assert cells.get(f'A{j}') == row[0], (name, j, 'article mismatch')
            assert cells.get(f'B{j}') == row[1], (name, j, 'reason mismatch')
            assert cells.get(f'G{j}') == row[6], (name, j, 'ID mismatch')
            actual_ids.append(cells[f'G{j}'])
        assert len(actual_ids) == len(set(actual_ids))
        assert max(byrow) == len(expected) + 8
        pane = doc.find('m:sheetViews/m:sheetView/m:pane', ns)
        assert pane is not None, 'Missing frozen panes'
        checks[name] = {'rows': len(expected), 'all_articles_reasons_and_ids_match':True, 'pane':pane.attrib}
    assert len([n for n in z.namelist() if n.startswith('xl/tables/table') and n.endswith('.xml')]) == 2
result = {'file': str(FILE), 'bytes': FILE.stat().st_size, 'checks':checks}
(HERE / 'export_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
