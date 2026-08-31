#!/usr/bin/env python3
"""Ежедневное заполнение пустых кодов ЭТМ в листе ``ETM TR``.

Production-путь читает актуальные ``price.csv`` сначала из ``/from_etm/13``,
затем из ``/from_etm/14``. На каждом проходе учитываются только пустые ячейки
колонки ``W`` (заголовок ``Коды ЭТМ``); любое уже непустое значение не меняется.
Строки сопоставляются по ``бренд + модель`` и, если модель не нашлась, по
``бренд + артикул``.

Без ``--write`` скрипт работает в dry-run. Для локальной проверки можно
передать ``--csv`` с CSV-файлом, имеющим колонки ``Код ЭТМ;Артикул;
Производитель``.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import posixpath
import re
import time

import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from ftplib import FTP, FTP_TLS, error_perm
from pathlib import Path
from typing import Iterable

import gspread

import config
import gsheets_utils


SHEET_NAME = "ETM TR"
SHEET_SCHEMA = {
    "article": "art",
    "model": "model",
    "brand": "brand",
    "etm_code": "Коды ЭТМ",
}

FTP_HOST = os.getenv("ETM_FTP_HOST", getattr(config, "ETM_FTP_HOST", "edi.etm.ru"))
FTP_PORT = int(os.getenv("ETM_FTP_PORT", getattr(config, "ETM_FTP_PORT", "21")))
FTP_USER = os.getenv("ETM_FTP_USER", getattr(config, "ETM_FTP_USER", "u_energoservis"))
FTP_PASSWORD = os.getenv("ETM_FTP_PASSWORD", getattr(config, "ETM_FTP_PASSWORD", ""))
FTP_TLS_MODE = os.getenv("ETM_FTP_TLS", getattr(config, "ETM_FTP_TLS", "disable")).strip().lower()
FTP_TIMEOUT = int(os.getenv("ETM_FTP_TIMEOUT", "300"))
FTP_DOWNLOAD_ATTEMPTS = max(1, int(os.getenv("ETM_FTP_DOWNLOAD_ATTEMPTS", "3")))
FTP_DOWNLOAD_BASE_DELAY = max(0.0, float(os.getenv("ETM_FTP_DOWNLOAD_BASE_DELAY", "2")))
_legacy_ftp_dir = os.getenv("ETM_FTP_CODES_DIR")
if _legacy_ftp_dir:
    # Обратная совместимость для ручных диагностических запусков -- один каталог.
    FTP_REMOTE_DIRS = (_legacy_ftp_dir,)
else:
    FTP_REMOTE_DIRS = (
        os.getenv("ETM_FTP_CODES_DIR_13", "/from_etm/13"),
        os.getenv("ETM_FTP_CODES_DIR_14", "/from_etm/14"),
    )
FTP_LOCAL_ROOT = Path(
    os.getenv(
        "ETM_FTP_LOCAL_ROOT",
        str(Path(__file__).resolve().parent / "test" / "tmp" / "etm_ftp_downloads"),
    )
)
FTP_STATE_PATH = Path(
    os.getenv(
        "ETM_CODES_FTP_STATE_PATH",
        str(Path(__file__).resolve().parent / "test" / "tmp" / "etm_codes_ftp_state.json"),
    )
)
FTP_REQUIRE_TODAY = os.getenv("ETM_CODES_FTP_REQUIRE_TODAY", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}

LOG_PATH = Path(__file__).resolve().parent / "logs" / "sync_etm_codes.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)


@dataclass(frozen=True)
class Update:
    row: int
    code: str
    model: str
    article: str
    brand: str
    matched_by: str


@dataclass(frozen=True)
class FtpFile:
    remote_path: str
    size: int | None = None
    modified: str | None = None


def normalize(value: object) -> str:
    """Нормализация ключа без удаления значимых нулей в артикулах."""
    return " ".join(
        str(value or "")
        .replace("\ufeff", "")
        .replace("\xa0", " ")
        .strip()
        .casefold()
        .split()
    )


def normalize_code(value: object) -> str:
    raw = str(value or "").replace("\ufeff", "").strip()
    raw = re.sub(r"\.0+$", "", raw)
    raw = re.sub(r"^ETM", "", raw, flags=re.IGNORECASE).strip()
    return re.sub(r"\D", "", raw)


def resolve_csv_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path(__file__).resolve().parent / path


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "windows-1251", "koi8-r"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _source_columns(fieldnames: list[str] | None) -> dict[str, int]:
    headers = [normalize(header) for header in (fieldnames or [])]
    aliases = {
        "code": {normalize("Код ЭТМ"), "etm code", "etmcode"},
        "article": {normalize("Артикул"), "article", "art"},
        "brand": {normalize("Производитель"), "manufacturer", "brand"},
    }
    result = {}
    for logical_name, candidates in aliases.items():
        matches = [index for index, header in enumerate(headers) if header in candidates]
        if len(matches) != 1:
            raise ValueError(
                f"В FTP-файле не найдена единственная колонка для {logical_name}: "
                f"ожидались {sorted(candidates)}, заголовки={fieldnames!r}"
            )
        result[logical_name] = matches[0]
    return result


def load_mapping_from_bytes(content: bytes, source_name: str = "FTP") -> tuple[dict[tuple[str, str], str], dict[str, int]]:
    """Загрузить уникальное отображение (артикул, бренд) -> код ЭТМ."""
    text = decode_text(content)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";\t,|")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"

    reader = csv.reader(io.StringIO(text), dialect=dialect)
    fieldnames = next(reader, None)
    columns = _source_columns(fieldnames)
    mapping: dict[tuple[str, str], str] = {}
    conflicts: dict[tuple[str, str], set[str]] = defaultdict(set)
    duplicate_rows = 0
    empty_rows = 0
    source_rows = 0

    for row in reader:
        source_rows += 1
        values = list(row)
        article = normalize(values[columns["article"]] if len(values) > columns["article"] else "")
        brand = normalize(values[columns["brand"]] if len(values) > columns["brand"] else "")
        code = normalize_code(values[columns["code"]] if len(values) > columns["code"] else "")
        if not article or not brand or not code:
            empty_rows += 1
            continue

        key = (article, brand)
        previous = mapping.get(key)
        if previous is None:
            mapping[key] = code
        elif previous == code:
            duplicate_rows += 1
        else:
            conflicts[key].update((previous, code))

    if conflicts:
        # Не останавливаем весь дневной sync из-за части плохих строк. Такие
        # ключи исключаются из mapping и безопасно попадут в unmatched.
        for key in conflicts:
            mapping.pop(key, None)
        logging.warning(
            "%s: пропущено конфликтных пар Артикул+Производитель: %s; примеры=%s",
            source_name,
            len(conflicts),
            list(conflicts.items())[:5],
        )

    return mapping, {
        "source_rows": source_rows,
        "mapping_keys": len(mapping),
        "duplicate_rows": duplicate_rows,
        "empty_rows": empty_rows,
        "conflict_keys": len(conflicts),
    }


def load_csv_mapping(path: str | Path) -> tuple[dict[tuple[str, str], str], dict[str, int]]:
    path = resolve_csv_path(path)
    return load_mapping_from_bytes(path.read_bytes(), path.name)


def plan_updates(
    sheet_rows: list[list[str]],
    columns: dict[str, int],
    mapping: dict[tuple[str, str], str],
) -> tuple[list[Update], dict[str, int]]:
    """Планировать заполнение только пустых ячеек кода ЭТМ."""
    updates: list[Update] = []
    stats = {
        "sheet_rows": max(len(sheet_rows) - 1, 0),
        "matched": 0,
        "changed": 0,
        "unchanged": 0,
        "existing": 0,
        "unmatched": 0,
        "ambiguous": 0,
        "missing_keys": 0,
    }

    for row_number, row in enumerate(sheet_rows[1:], start=2):
        def value(logical_name: str) -> str:
            column = columns[logical_name]
            return str(row[column - 1]).strip() if len(row) >= column else ""

        # Критическое правило: любое непустое значение в W считается уже
        # заполненным. Не пытаемся нормализовать или перезаписывать его.
        if value("etm_code"):
            stats["existing"] += 1
            continue

        article = value("article")
        model = value("model")
        brand = value("brand")
        brand_key = normalize(brand)
        if not brand_key or (not normalize(model) and not normalize(article)):
            stats["missing_keys"] += 1
            continue

        candidates = []
        if normalize(model):
            candidates.append(("model", normalize(model)))
        if normalize(article):
            candidates.append(("article", normalize(article)))
        found = [
            (matched_by, mapping[(candidate, brand_key)])
            for matched_by, candidate in candidates
            if (candidate, brand_key) in mapping
        ]

        unique_codes = {code for _, code in found}
        if len(unique_codes) > 1:
            stats["ambiguous"] += 1
            logging.warning(
                "Пропуск строки %s: модель и артикул дают разные коды ЭТМ (%s)",
                row_number,
                sorted(unique_codes),
            )
            continue
        if not found:
            stats["unmatched"] += 1
            continue

        matched_by, code = found[0]
        stats["matched"] += 1
        stats["changed"] += 1
        updates.append(Update(row_number, code, model, article, brand, matched_by))

    return updates, stats


def a1_ranges(updates: Iterable[Update], column: int) -> list[tuple[str, list[list[str]]]]:
    """Сгруппировать соседние изменения в минимальные диапазоны."""
    ordered = sorted(updates, key=lambda item: item.row)
    if not ordered:
        return []
    groups: list[list[Update]] = [[ordered[0]]]
    for update in ordered[1:]:
        if update.row == groups[-1][-1].row + 1:
            groups[-1].append(update)
        else:
            groups.append([update])
    return [
        (
            f"{gspread.utils.rowcol_to_a1(group[0].row, column)}:"
            f"{gspread.utils.rowcol_to_a1(group[-1].row, column)}",
            [[item.code] for item in group],
        )
        for group in groups
    ]


def update_sheet(ws, updates: list[Update], code_column: int) -> int:
    ranges = a1_ranges(updates, code_column)
    if not ranges:
        return 0

    total_rows = sum(len(values) for _, values in ranges)
    logging.info(
        "Пакетная запись %s строк в %s диапазонах одним запросом Google Sheets",
        total_rows,
        len(ranges),
    )

    # Worksheet.batch_update использует один values.batchUpdate request. Важно
    # создавать payload внутри lambda: gspread дописывает имя листа в range,
    # и повторная попытка не должна получить двойной префикс листа.
    def send_batch():
        return ws.batch_update(
            [{"range": range_name, "values": values} for range_name, values in ranges],
            raw=False,
            value_input_option="USER_ENTERED",
        )

    gsheets_utils._retry_gsheet_call(
        "batch update ETM codes",
        send_batch,
        max_attempts=6,
        base_delay=5.0,
    )
    return len(ranges)


def _ftp_password() -> str:
    if FTP_PASSWORD:
        return FTP_PASSWORD
    result = subprocess.run(
        ["security", "find-generic-password", "-a", FTP_USER, "-s", "checksheets_etm_ftp", "-w"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def connect_ftp():
    password = _ftp_password()
    if not FTP_USER or not password:
        raise RuntimeError(
            "Не задан пароль ETM FTP: используйте ETM_FTP_PASSWORD или Keychain "
            "service=checksheets_etm_ftp"
        )
    if FTP_TLS_MODE not in {"auto", "require", "disable"}:
        raise ValueError("ETM_FTP_TLS должен быть auto, require или disable")
    if FTP_TLS_MODE != "disable":
        try:
            ftp_tls = FTP_TLS()
            ftp_tls.connect(FTP_HOST, FTP_PORT, timeout=FTP_TIMEOUT)
            ftp_tls.login(FTP_USER, password)
            ftp_tls.prot_p()
            ftp_tls.set_pasv(True)
            return ftp_tls
        except Exception:
            if FTP_TLS_MODE == "require":
                raise
            logging.warning("FTPS недоступен, используем plain FTP")
    ftp = FTP()
    ftp.connect(FTP_HOST, FTP_PORT, timeout=FTP_TIMEOUT)
    ftp.login(FTP_USER, password)
    ftp.set_pasv(True)
    return ftp


def _mdtm(ftp, remote_path: str) -> str | None:
    try:
        response = ftp.sendcmd(f"MDTM {remote_path}")
    except Exception:
        return None
    match = re.search(r"(\d{14})", response)
    return match.group(1) if match else None


def list_ftp_files(ftp, remote_dir: str) -> list[FtpFile]:
    remote_dir = "/" + remote_dir.strip("/")
    try:
        files = []
        for name, facts in ftp.mlsd(remote_dir):
            if name in {".", ".."} or facts.get("type") != "file":
                continue
            path = posixpath.join(remote_dir, name)
            size = int(facts["size"]) if str(facts.get("size", "")).isdigit() else None
            files.append(FtpFile(path, size, facts.get("modify") or _mdtm(ftp, path)))
        return files
    except Exception:
        pass

    try:
        entries = ftp.nlst(remote_dir)
    except error_perm as exc:
        logging.warning("Не удалось прочитать FTP-каталог %s: %s", remote_dir, exc)
        return []
    result = []
    for entry in entries:
        path = entry if entry.startswith("/") else posixpath.join(remote_dir, entry)
        result.append(FtpFile(path, None, _mdtm(ftp, path)))
    return result


def _ftp_date(modified: str | None) -> str | None:
    return str(modified)[:8] if modified and re.fullmatch(r"\d{14}", modified) else None


def select_ftp_file(files: list[FtpFile]) -> FtpFile | None:
    if not files:
        return None
    if FTP_REQUIRE_TODAY:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        today_files = [item for item in files if _ftp_date(item.modified) == today]
        if today_files:
            files = today_files
        else:
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")
            yesterday_files = [item for item in files if _ftp_date(item.modified) == yesterday]
            if not yesterday_files:
                logging.warning("Нет FTP-файла за сегодня или вчера; обновление отменено")
                return None
            logging.warning("Нет файла за сегодня; используем FTP-файл за вчера")
            files = yesterday_files
    return max(files, key=lambda item: (item.modified or "", item.remote_path))


def download_ftp_file(ftp, ftp_file: FtpFile) -> bytes:
    started_at = time.monotonic()
    chunks: list[bytes] = []
    bytes_received = 0

    def collect(chunk: bytes) -> None:
        nonlocal bytes_received
        bytes_received += len(chunk)
        chunks.append(chunk)

    try:
        ftp.retrbinary(f"RETR {ftp_file.remote_path}", collect)
    except Exception as exc:
        logging.warning(
            "FTP download failed: path=%s bytes=%s duration=%.2fs error=%s(%s)",
            ftp_file.remote_path,
            bytes_received,
            time.monotonic() - started_at,
            type(exc).__name__,
            str(exc) or "<empty>",
        )
        raise

    content = b"".join(chunks)
    logging.info(
        "FTP download complete: path=%s bytes=%s duration=%.2fs",
        ftp_file.remote_path,
        len(content),
        time.monotonic() - started_at,
    )
    return content


def validate_ftp_csv(content: bytes, source_name: str) -> dict[str, object]:
    """Проверить кодировку, заголовок и наличие строк до кеширования источника."""
    text = decode_text(content)
    if not text.strip():
        raise ValueError(f"{source_name}: пустой CSV")

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";\t,|")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"

    reader = csv.reader(io.StringIO(text), dialect=dialect, strict=True)
    fieldnames = next(reader, None)
    _source_columns(fieldnames)
    data_rows = 0
    nonempty_data_rows = 0
    for row in reader:
        data_rows += 1
        if any(str(value).strip() for value in row):
            nonempty_data_rows += 1
    if data_rows == 0 or nonempty_data_rows == 0:
        raise ValueError(f"{source_name}: CSV не содержит строк данных")

    return {
        "header_columns": len(fieldnames or []),
        "data_rows": data_rows,
        "has_data": True,
    }


def save_ftp_cache(ftp_file: FtpFile, content: bytes) -> None:
    """Сохранить только полностью скачанный и проверенный файл атомарно."""
    local_path = FTP_LOCAL_ROOT / ftp_file.remote_path.lstrip("/")
    local_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = local_path.with_name(f".{local_path.name}.tmp")
    temporary.write_bytes(content)
    temporary.replace(local_path)


def _fingerprint(ftp_file: FtpFile) -> dict[str, object]:
    return {
        "remote_path": ftp_file.remote_path,
        "size": ftp_file.size,
        "modified": ftp_file.modified,
    }


def _load_state() -> dict:
    try:
        return json.loads(FTP_STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    FTP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = FTP_STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(FTP_STATE_PATH)


def fetch_ftp_source(remote_dir: str, force: bool = False) -> tuple[bytes, FtpFile] | None:
    # ``force`` оставлен для совместимости с ручными командами. В режиме
    # заполнения только пустых ячеек файл читается каждый день даже если его
    # fingerprint уже встречался: в таблице могли появиться новые пустые W.
    del force
    warehouse = remote_dir.rstrip("/").split("/")[-1]
    last_error: Exception | None = None

    for attempt in range(1, FTP_DOWNLOAD_ATTEMPTS + 1):
        ftp = None
        try:
            # Новое соединение создаётся для каждой попытки, чтобы EOF/обрыв
            # control connection не переносился в следующий retry.
            ftp = connect_ftp()
            ftp_file = select_ftp_file(list_ftp_files(ftp, remote_dir))
            if ftp_file is None:
                logging.warning("Для FTP-каталога %s нет подходящего файла", remote_dir)
                return None
            logging.info(
                "Загрузка FTP-файла склада %s: %s, size=%s, modified=%s, attempt=%s/%s",
                warehouse,
                ftp_file.remote_path,
                ftp_file.size,
                ftp_file.modified,
                attempt,
                FTP_DOWNLOAD_ATTEMPTS,
            )
            content = download_ftp_file(ftp, ftp_file)
            validation = validate_ftp_csv(content, ftp_file.remote_path)
            logging.info(
                "FTP CSV validated: path=%s header_columns=%s data_rows=%s has_data=%s",
                ftp_file.remote_path,
                validation["header_columns"],
                validation["data_rows"],
                validation["has_data"],
            )
            # Кеш и последующий state обновляются только после полной передачи
            # и успешной проверки CSV.
            save_ftp_cache(ftp_file, content)
            return content, ftp_file
        except Exception as exc:
            last_error = exc
            logging.warning(
                "Ошибка загрузки FTP склада %s, попытка %s/%s: %s(%s)",
                warehouse,
                attempt,
                FTP_DOWNLOAD_ATTEMPTS,
                type(exc).__name__,
                str(exc) or "<empty>",
            )
            if attempt < FTP_DOWNLOAD_ATTEMPTS:
                delay = FTP_DOWNLOAD_BASE_DELAY * (2 ** (attempt - 1))
                logging.info(
                    "Повторное подключение к FTP складу %s через %.1f сек",
                    warehouse,
                    delay,
                )
                time.sleep(delay)
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except Exception:
                    ftp.close()

    raise RuntimeError(
        f"Не удалось скачать и проверить FTP-файл склада {warehouse} "
        f"за {FTP_DOWNLOAD_ATTEMPTS} попытки"
    ) from last_error


def _apply_updates_to_memory(sheet_rows: list[list[str]], updates: Iterable[Update], code_column: int) -> None:
    """Отметить в памяти коды из склада 13 перед проходом склада 14."""
    for item in updates:
        row = sheet_rows[item.row - 1]
        if len(row) < code_column:
            row.extend([""] * (code_column - len(row)))
        row[code_column - 1] = item.code


def run(
    csv_path: str | Path | None = None,
    *,
    write: bool = False,
    force: bool = False,
    sample_size: int = 10,
) -> int:
    # Для ручного --csv оставляем один источник. Production-путь всегда
    # проходит источники в порядке 13 -> 14.
    sources: list[tuple[str, bytes, FtpFile | None]] = []
    failures: list[str] = []
    if csv_path is not None:
        mapping, source_stats = load_csv_mapping(csv_path)
        sources.append((f"CSV {resolve_csv_path(csv_path).name}", b"", None))
        csv_source = (mapping, source_stats)
    else:
        csv_source = None
        for remote_dir in FTP_REMOTE_DIRS:
            warehouse = remote_dir.rstrip("/").split("/")[-1]
            try:
                source = fetch_ftp_source(remote_dir, force=force)
            except Exception as exc:
                failures.append(f"склад {warehouse}: {exc}")
                logging.exception("Ошибка загрузки FTP склада %s", warehouse)
                continue
            if source is None:
                failures.append(f"склад {warehouse}: подходящий файл не найден")
                continue
            content, ftp_file = source
            sources.append((f"склад {warehouse}", content, ftp_file))

    if not sources:
        raise RuntimeError("Не удалось получить ни одного источника ETM: " + "; ".join(failures))

    ws = gsheets_utils.get_worksheet(SHEET_NAME)
    sheet_rows = gsheets_utils._retry_gsheet_call(
        f"read all values from {SHEET_NAME}",
        ws.get_all_values,
    )
    if not sheet_rows:
        raise RuntimeError(f"Лист {SHEET_NAME!r} пустой")
    columns = gsheets_utils.resolve_header_columns(sheet_rows[0], SHEET_SCHEMA, SHEET_NAME)

    all_updates: list[Update] = []
    processed_files: dict[str, dict[str, object]] = {}
    for source_label, content, ftp_file in sources:
        if csv_source is not None:
            mapping, source_stats = csv_source
        else:
            assert ftp_file is not None
            mapping, source_stats = load_mapping_from_bytes(content, ftp_file.remote_path)
        updates, source_sheet_stats = plan_updates(sheet_rows, columns, mapping)
        logging.info(
            "%s: источник строк=%s, уникальных пар=%s, дубликатов=%s, пустых строк=%s, конфликтных пар=%s",
            source_label,
            source_stats["source_rows"],
            source_stats["mapping_keys"],
            source_stats["duplicate_rows"],
            source_stats["empty_rows"],
            source_stats["conflict_keys"],
        )
        logging.info(
            "%s: ETM TR строк=%s, совпало=%s, будет заполнено=%s, уже заполнено=%s, "
            "без совпадения=%s, неоднозначных=%s, без ключа=%s",
            source_label,
            source_sheet_stats["sheet_rows"],
            source_sheet_stats["matched"],
            source_sheet_stats["changed"],
            source_sheet_stats["existing"],
            source_sheet_stats["unmatched"],
            source_sheet_stats["ambiguous"],
            source_sheet_stats["missing_keys"],
        )
        for item in updates[:max(sample_size, 0)]:
            logging.info(
                "Пример заполнения: %s, строка %s, matched_by=%s, model=%r, article=%r, brand=%r -> код=%s",
                source_label,
                item.row,
                item.matched_by,
                item.model,
                item.article,
                item.brand,
                item.code,
            )
        all_updates.extend(updates)
        if ftp_file is not None:
            processed_files[source_label] = _fingerprint(ftp_file)
        # После склада 13 эти ячейки становятся непустыми в памяти и не могут
        # быть повторно выбраны складом 14.
        _apply_updates_to_memory(sheet_rows, updates, columns["etm_code"])

    if not write:
        logging.info("Dry-run: Google Sheets не изменялись. Для записи используйте --write.")
        return 1 if failures else 0

    range_count = update_sheet(ws, all_updates, columns["etm_code"])
    if processed_files:
        state = _load_state()
        state["files"] = processed_files
        state["processed_at"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)
    logging.info(
        "Запись завершена: заполнено пустых кодов=%s, диапазонов=%s, ошибок источников=%s",
        len(all_updates),
        range_count,
        len(failures),
    )
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Актуализировать коды ЭТМ в ETM TR из FTP склада 13")
    parser.add_argument("--csv", help="Локальный CSV вместо FTP; для тестов и ручной проверки")
    parser.add_argument("--write", action="store_true", help="Записать изменившиеся коды в Google Sheets")
    parser.add_argument("--force", action="store_true", help="Обработать FTP-файл повторно, даже если он уже отмечен в state")
    parser.add_argument("--sample-size", type=int, default=10, help="Количество примеров изменений в логе")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        raise SystemExit(run(args.csv, write=args.write, force=args.force, sample_size=args.sample_size))
    except Exception as exc:
        logging.exception("CRITICAL ERROR: %s", exc)
        raise SystemExit(1)