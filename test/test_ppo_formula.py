import gspread
from google.oauth2.service_account import Credentials
import config

scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file(config.GSHEETS_CREDS_FILE, scopes=scopes)
ss = gspread.authorize(creds).open_by_key(config.SPREADSHEET_ID)
ws = ss.worksheet("ТЗ")
formula = r'''={"TEST";ARRAYFORMULA(IF(A2:A="";"";IFERROR(SUMIF(REGEXREPLACE(SUBSTITUTE(UPPER(TO_TEXT(PPO!Q3:Q));"Ё";"Е");"[^0-9A-ZА-Я]";"");REGEXREPLACE(SUBSTITUTE(UPPER(REGEXREPLACE(TO_TEXT(A2:A);"-[0-9]+$";""));"Ё";"Е");"[^0-9A-ZА-Я]";"");ARRAYFORMULA(IFERROR(VALUE(SUBSTITUTE(PPO!P3:P;" ";""));0)));0)))}'''
ws.update(range_name="AQ1", values=[[formula]], raw=False)
print(ws.get("AQ1:AQ10", value_render_option="UNFORMATTED_VALUE"))
print(ws.get("AQ22:AQ22", value_render_option="UNFORMATTED_VALUE"))
print(ws.get("AQ7163:AQ7163", value_render_option="UNFORMATTED_VALUE"))
