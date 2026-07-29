import http.client
import socket
import time

import gspread
import requests
from google.oauth2.service_account import Credentials

import config


TRANSIENT_HTTP_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
TRANSIENT_ERROR_TEXT = (
    "RemoteDisconnected",
    "Connection aborted",
    "Connection reset",
    "Broken pipe",
    "Read timed out",
    "The service is currently unavailable",
    "Internal error encountered",
)


def normalize_header(value):
    """Normalize a Google Sheets header for stable schema matching."""
    return str(value or "").strip().lower().replace("ё", "е")


def resolve_header_columns(headers, schema, sheet_name="worksheet"):
    """Resolve logical field names to one-and-only-one header columns.

    ``schema`` maps internal field names to their visible sheet headers.  A
    missing or duplicated header is an unsafe sheet layout, so this function
    raises before any caller can clear or write data.
    """
    normalized_to_columns = {}
    for column, header in enumerate(headers, start=1):
        normalized = normalize_header(header)
        if normalized:
            normalized_to_columns.setdefault(normalized, []).append(column)

    resolved = {}
    for field_name, header_name in schema.items():
        normalized = normalize_header(header_name)
        columns = normalized_to_columns.get(normalized, [])
        if not columns:
            raise ValueError(
                f"Sheet '{sheet_name}': header '{header_name}' for field "
                f"'{field_name}' was not found"
            )
        if len(columns) != 1:
            raise ValueError(
                f"Sheet '{sheet_name}': header '{header_name}' for field "
                f"'{field_name}' is duplicated in columns {columns}"
            )
        resolved[field_name] = columns[0]
        print(
            f"Sheet schema: {sheet_name} -> {field_name} -> "
            f"'{header_name}' -> column {columns[0]}"
        )
    return resolved


def get_header_columns(worksheet, schema, sheet_name=None):
    """Read row 1 once and resolve a strict logical schema against it."""
    return resolve_header_columns(
        _row_values(worksheet, 1),
        schema,
        sheet_name or getattr(worksheet, "title", "worksheet"),
    )


def _is_transient_gsheet_error(exc):
    """Return True for Google Sheets/network failures worth retrying."""
    if isinstance(
        exc,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            http.client.RemoteDisconnected,
            ConnectionResetError,
            BrokenPipeError,
            TimeoutError,
            socket.timeout,
        ),
    ):
        return True

    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code in TRANSIENT_HTTP_STATUS_CODES:
        return True

    message = str(exc)
    return any(fragment in message for fragment in TRANSIENT_ERROR_TEXT)


def _retry_gsheet_call(label, func, max_attempts=6, base_delay=2.0):
    """Run a Google Sheets API call with exponential backoff for transient disconnects."""
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not _is_transient_gsheet_error(exc):
                raise

            delay = min(base_delay * (2 ** (attempt - 1)), 30.0)
            print(
                f"Google Sheets transient error during {label} "
                f"(attempt {attempt}/{max_attempts}): {type(exc).__name__}: {exc}. "
                f"Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)

    raise RuntimeError("Google Sheets retry loop exited unexpectedly")


def get_gsheet_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(config.GSHEETS_CREDS_FILE, scopes=scopes)
    return gspread.authorize(creds)


def get_worksheet(sheet_name):
    if config.SPREADSHEET_ID == "YOUR_SPREADSHEET_ID":
        raise ValueError("Please set SPREADSHEET_ID in config.py")
    client = get_gsheet_client()
    spreadsheet = _retry_gsheet_call(
        f"open spreadsheet {config.SPREADSHEET_ID}",
        lambda: client.open_by_key(config.SPREADSHEET_ID),
    )
    return _retry_gsheet_call(f"open worksheet {sheet_name}", lambda: spreadsheet.worksheet(sheet_name))


def _row_values(worksheet, row):
    return _retry_gsheet_call(f"read row {row}", lambda: worksheet.row_values(row))


def update_column_by_header(worksheet, header_name, values, start_row=2):
    """
    Updates a specific column identified by its header name.
    values should be a list of single-item lists: [[v1], [v2], ...]
    """
    if not values:
        return

    col_index = resolve_header_columns(
        _row_values(worksheet, 1),
        {"target": header_name},
        getattr(worksheet, "title", "worksheet"),
    )["target"]

    range_label = f"{gspread.utils.rowcol_to_a1(start_row, col_index)}:{gspread.utils.rowcol_to_a1(start_row + len(values) - 1, col_index)}"
    _retry_gsheet_call(
        f"update column '{header_name}' range {range_label}",
        lambda: worksheet.update(range_label, values),
    )


def clear_column(worksheet, header_name, start_row=2):
    """
    Clears all data in a specific column starting from start_row.
    """
    if isinstance(header_name, int):
        raise ValueError("clear_column requires a header name, not a column number")
    col_index = resolve_header_columns(
        _row_values(worksheet, 1),
        {"target": header_name},
        getattr(worksheet, "title", "worksheet"),
    )["target"]

    clear_column_at_index(worksheet, col_index, start_row=start_row)


def clear_column_at_index(worksheet, col_index, start_row=2):
    """Clear a column already resolved from a validated sheet schema."""
    col_index = int(col_index)
    last_row = worksheet.row_count
    if last_row < start_row:
        return

    col_letter = gspread.utils.rowcol_to_a1(1, col_index).strip('1')
    range_label = f"{col_letter}{start_row}:{col_letter}{last_row}"
    _retry_gsheet_call(
        f"clear column {col_index} range {range_label}",
        lambda: worksheet.batch_clear([range_label]),
    )


def update_column(worksheet, col_num, values, start_row=2):
    """
    Updates a specific column by column number (1-based).
    values should be a list of single-item lists: [[v1], [v2], ...]
    """
    if not values:
        return

    col_index = int(col_num)
    range_label = f"{gspread.utils.rowcol_to_a1(start_row, col_index)}:{gspread.utils.rowcol_to_a1(start_row + len(values) - 1, col_index)}"
    _retry_gsheet_call(
        f"update column {col_index} range {range_label}",
        lambda: worksheet.update(range_label, values),
    )
