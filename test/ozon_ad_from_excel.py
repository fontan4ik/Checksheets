import os
import glob
import pandas as pd
from datetime import datetime

# Excel file path - hardcoded for testing
EXCEL_FILE = r'C:\Users\jilig\Downloads\Telegram Desktop\Оплата_за_заказ_все_товары_Отчёт_по_заказам_15_04_2026.xlsx'

def read_from_excel():
    """Read advertising stats from Excel report"""
    print("Reading from Excel: " + os.path.basename(EXCEL_FILE))
    
    # Read Excel
    df = pd.read_excel(EXCEL_FILE, header=None)
    
    print("Total rows: " + str(len(df)))
    
    # Excel columns:
    # Col 0 = Дата
    # Col 3 = SKU
    # Col 7 = Количество
    # Col 8 = Цена
    # Col 10 = Расход (spend)
    # Col 11 = Выручка (revenue)
    
    # Filter dates: 8-14 April (08.04.2026 - 14.04.2026)
    valid_dates = ['08.04.2026', '09.04.2026', '10.04.2026', '11.04.2026', '12.04.2026', '13.04.2026', '14.04.2026']
    
    stats = {}
    
    for i in range(3, len(df)):  # Skip header rows
        try:
            # Get date
            date_val = df.iloc[i, 0]
            if pd.isna(date_val):
                continue
            
            date_str = str(date_val)
            if date_str not in valid_dates:
                continue
            
            # Get SKU
            sku_val = df.iloc[i, 3]
            if pd.isna(sku_val):
                continue
            
            try:
                sku = int(float(str(sku_val)))
            except:
                continue
            
            # Get values
            try:
                qty = float(str(df.iloc[i, 7]).replace(',', '.')) if pd.notna(df.iloc[i, 7]) else 0
            except:
                qty = 0
            
            try:
                price = float(str(df.iloc[i, 8]).replace(',', '.')) if pd.notna(df.iloc[i, 8]) else 0
            except:
                price = 0
            
            try:
                spend = float(str(df.iloc[i, 10]).replace(',', '.')) if pd.notna(df.iloc[i, 10]) else 0
            except:
                spend = 0
                
            try:
                revenue = float(str(df.iloc[i, 11]).replace(',', '.')) if pd.notna(df.iloc[i, 11]) else 0
            except:
                revenue = 0
            
            # Aggregate by SKU
            if sku not in stats:
                stats[sku] = {'orders': 0, 'spend': 0, 'revenue': 0, 'cost': 0}
            
            # orders = sum of qty (col 7), cost = price * qty
            stats[sku]['orders'] += qty
            stats[sku]['cost'] += price * qty  # Стоимость = цена * кол-во
            stats[sku]['spend'] += spend
            stats[sku]['revenue'] += revenue
            
        except Exception as e:
            continue
    
    print("Parsed: " + str(len(stats)) + " SKUs")
    
    # Show sample
    print("\nSample SKUs:")
    for sku in list(stats.keys())[:5]:
        print("  " + str(sku) + ": orders=" + str(stats[sku]['orders']) + ", spend=" + str(stats[sku]['spend']) + ", revenue=" + str(stats[sku]['revenue']))
    
    return stats

def write_to_sheet(stats):
    """Write to Google Sheets"""
    from google.oauth2 import service_account
    import googleapiclient.discovery
    import time
    
    for attempt in range(5):
        try:
            print("Connecting to Google Sheets (attempt " + str(attempt + 1) + "/5)...")
            
            # Credentials
            creds_file = os.path.join(os.path.dirname(__file__), '..', 'nomadic-bedrock-485314-b0-ff60180040ed.json')
            
            credentials = service_account.Credentials.from_service_account_file(
                creds_file, 
                scopes=['https://www.googleapis.com/auth/spreadsheets']
            )
            
            service = googleapiclient.discovery.build('sheets', 'v4', credentials=credentials)
            
            SHEET_ID = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI'
            
            # Get sheet metadata
            metadata = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
            sheets = metadata.get('sheets', [])
            
            # Find тест sheet (index 2)
            first_sheet = None
            for s in sheets:
                if s['properties']['index'] == 2:
                    first_sheet = s
                    break
            if not first_sheet:
                first_sheet = sheets[0]
            
            first_sheet_title = first_sheet['properties']['title']
            print("Sheet: " + first_sheet_title)
            
            # Read column V (SKU) from sheet
            result = service.spreadsheets().values().get(
                spreadsheetId=SHEET_ID, 
                range=f"'{first_sheet_title}'!V:V"
            ).execute()
            
            sku_values = result.get('values', [])
            sku_list = []
            for row in sku_values[1:]:  # Skip header
                if row and row[0]:
                    sku_list.append(row[0])
            
            print("SKU rows in sheet: " + str(len(sku_list)))
            
            # Prepare data
            ba_data = []
            bb_data = []
            bc_data = []
            
            found = 0
            for sku in sku_list:
                try:
                    sku_int = int(sku)
                except:
                    ba_data.append([0])
                    bb_data.append([0])
                    bc_data.append([0])
                    continue
                
                if sku_int in stats:
                    data = stats[sku_int]
                    ba_data.append([data['orders']])
                    bb_data.append([data['cost']])  # Стоимость = цена * кол-во
                    bc_data.append([data['spend']])  # Расход
                    found += 1
                else:
                    ba_data.append([0])
                    bb_data.append([0])
                    bc_data.append([0])
            
            print("Found matches: " + str(found))
            
            # Write to columns
            start_row = 2
            
            # BA
            range_ba = first_sheet_title + "!BA" + str(start_row) + ":BA" + str(start_row + len(ba_data) - 1)
            service.spreadsheets().values().update(
                spreadsheetId=SHEET_ID, 
                range=range_ba,
                valueInputOption='USER_ENTERED',
                body={'values': ba_data}
            ).execute()
            
            # BB
            range_bb = first_sheet_title + "!BB" + str(start_row) + ":BB" + str(start_row + len(bb_data) - 1)
            service.spreadsheets().values().update(
                spreadsheetId=SHEET_ID, 
                range=range_bb,
                valueInputOption='USER_ENTERED',
                body={'values': bb_data}
            ).execute()
            
            # BC
            range_bc = first_sheet_title + "!BC" + str(start_row) + ":BC" + str(start_row + len(bc_data) - 1)
            service.spreadsheets().values().update(
                spreadsheetId=SHEET_ID, 
                range=range_bc,
                valueInputOption='USER_ENTERED',
                body={'values': bc_data}
            ).execute()
            
            print("Written to BA, BB, BC columns")
            return
            
        except Exception as e:
            print("Error: " + str(e)[:100])
            if attempt < 4:
                time.sleep(5)
            else:
                raise

# Main
if __name__ == '__main__':
    stats = read_from_excel()
    
    # Check for target SKU
    target = 1644174248
    if target in stats:
        print("\n=== Target SKU " + str(target) + " ===")
        print("Orders: " + str(stats[target]['orders']))
        print("Cost: " + str(stats[target]['cost']))  # Стоимость
        print("Spend: " + str(stats[target]['spend']))  # Расход
        print("Revenue: " + str(stats[target]['revenue']))
    
    write_to_sheet(stats)
    print("\nDONE!")