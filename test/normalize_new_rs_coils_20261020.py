"""Normalize only five proven RS metre stocks into complete 305m coils."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import config
import gsheets_utils
from rs_sync_local import fetch_rs_coil_quantities, RS_305M_COIL_MODELS

def main():
    evidence=json.loads((ROOT/'test/new_rs_cable_units_20261020.json').read_text())
    codes={model:row['CODE'] for model,row in evidence['positions'].items()}
    assert set(codes)==RS_305M_COIL_MODELS
    assert evidence['warehouse']==config.RS_WAREHOUSE_ID
    quantities=fetch_rs_coil_quantities(list(codes),codes,config.RS_WAREHOUSE_ID)
    ws=gsheets_utils.get_worksheet('StreamSupps')
    columns=gsheets_utils.get_header_columns(ws,{'stock':'RS SMR','pack':'Х','model':'Артикул производителя'})
    targets=[t for t in json.loads((ROOT/'test/new_stream_targets_20261020.json').read_text()) if t['v'][1] in RS_305M_COIL_MODELS]
    ranges=[f'A{t["row"]}:V{t["row"]}' for t in targets]
    current=ws.batch_get(ranges,value_render_option='UNFORMATTED_VALUE')
    updates=[]
    for t,block in zip(targets,current):
        r=block[0]
        assert r[0]==t['v'][0] and r[columns['model']-1]==t['v'][1] and r[columns['pack']-1]==1
        address=gsheets_utils.gspread.utils.rowcol_to_a1(t['row'],columns['stock'])
        updates.append({'range':address,'values':[[quantities[t['v'][1]]]]})
    report={'quantities':quantities,'columns':columns,'targets':[{'row':t['row'],'offer':t['v'][0],'model':t['v'][1]} for t in targets],'before':current,'updates':updates}
    (ROOT/'test/new_rs_coils_normalization_20261020.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if '--apply' not in sys.argv:
        print(quantities)
        return
    ws.batch_update(updates,value_input_option='RAW')
    after=ws.batch_get([x['range'].split('!')[-1] for x in updates],value_render_option='UNFORMATTED_VALUE')
    assert [x[0][0] for x in after]==[x['values'][0][0] for x in updates]
    print('Verified RS source unit normalization:',quantities)

if __name__=='__main__':
    main()
