from collections import defaultdict
from decimal import Decimal, InvalidOperation
import re
import time

import gspread
from google.oauth2.service_account import Credentials

import config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def article_key(value):
    """Normalize PPO Q / ТЗ A while preserving alphanumeric article identity."""
    text = str(value or "").strip().upper().replace("Ё", "Е")
    # ТЗ A contains a final marketplace/package suffix such as -1, -5, -10.
    text = re.sub(r"-[0-9]+$", "", text)
    return re.sub(r"[^0-9A-ZА-Я]", "", text)


def stock_number(value):
    if value in (None, ""):
        return Decimal("0")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).replace("\u00a0", "").replace(" ", "").strip()
    text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def format_decimal(value):
    value = value.normalize()
    if value == value.to_integral():
        return str(value.quantize(Decimal("1")))
    return format(value, "f").rstrip("0").rstrip(".")


def main():
    creds = Credentials.from_service_account_file(config.GSHEETS_CREDS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    source = spreadsheet.worksheet("PPO")
    target = spreadsheet.worksheet("ТЗ")

    source_rows = source.get("P3:Q", value_render_option="UNFORMATTED_VALUE")
    target_articles = target.get("A2:A", value_render_option="UNFORMATTED_VALUE")

    source_totals = defaultdict(Decimal)
    source_rows_by_key = defaultdict(list)
    for row_number, row in enumerate(source_rows, start=3):
        stock = row[0] if len(row) > 0 else ""
        article = row[1] if len(row) > 1 else ""
        key = article_key(article)
        if key:
            source_totals[key] += stock_number(stock)
            source_rows_by_key[key].append((row_number, article, stock))

    target_rows_by_key = defaultdict(list)
    for row_number, row in enumerate(target_articles, start=2):
        article = row[0] if row else ""
        key = article_key(article)
        if key:
            target_rows_by_key[key].append(row_number)

    source_keys = set(source_totals)
    target_keys = set(target_rows_by_key)
    covered_keys = source_keys & target_keys
    missing_keys = source_keys - target_keys

    formula = r'''={
  "ОСТАТОК PPO";
  ARRAYFORMULA(
    IF(A2:A="";"";
      IFERROR(
        VLOOKUP(
          REGEXREPLACE(
            SUBSTITUTE(UPPER(REGEXREPLACE(TO_TEXT(A2:A);"-[0-9]+$";""));"Ё";"Е");
            "[^0-9A-ZА-Я]";""
          );
          QUERY(
            {
              REGEXREPLACE(
                SUBSTITUTE(UPPER(REGEXREPLACE(TO_TEXT(PPO!Q3:Q);"-[0-9]+$";""));"Ё";"Е");
                "[^0-9A-ZА-Я]";""
              )\
              ARRAYFORMULA(IFERROR(NUMBERVALUE(TO_TEXT(PPO!P3:P);",";" ");0))
            };
            "select Col1, sum(Col2) where Col1 is not null group by Col1 label sum(Col2) ''";
            0
          );
          2;
          FALSE
        );
        0
      )
    )
  )
}'''

    old_formula = target.get("AQ1", value_render_option="FORMULA")
    target.update("AQ1", [[formula]], raw=False)
    time.sleep(8)

    formula_readback = target.get("AQ1", value_render_option="FORMULA")
    rendered = target.get("AQ1:AQ" + str(max(2, target.row_count)), value_render_option="UNFORMATTED_VALUE")

    # Verify first target row for every covered source key against the aggregate.
    values_by_target_row = {
        row_number: (rendered[row_number - 1][0] if row_number - 1 < len(rendered) and rendered[row_number - 1] else "")
        for key in covered_keys
        for row_number in target_rows_by_key[key]
    }
    mismatches = []
    for key in sorted(covered_keys):
        expected = source_totals[key]
        for row_number in target_rows_by_key[key]:
            actual = stock_number(values_by_target_row.get(row_number, ""))
            if actual != expected:
                mismatches.append((key, row_number, format_decimal(expected), format_decimal(actual)))
                if len(mismatches) >= 10:
                    break
        if len(mismatches) >= 10:
            break

    print("source_rows", len(source_rows))
    print("source_unique_keys", len(source_keys))
    print("source_duplicate_keys", sum(1 for rows in source_rows_by_key.values() if len(rows) > 1))
    print("target_article_rows", sum(len(v) for v in target_rows_by_key.values()))
    print("source_keys_covered_by_target", len(covered_keys))
    print("source_keys_missing_in_target", len(missing_keys))
    print("missing_key_sample", sorted(missing_keys)[:20])
    print("formula_readback", formula_readback)
    print("aggregate_mismatches", mismatches)
    print("old_formula", old_formula)


if __name__ == "__main__":
    main()
