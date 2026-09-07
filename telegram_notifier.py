"""Telegram notification module for Checksheets synchronization services."""

from __future__ import annotations

from datetime import datetime
import os
import traceback
from typing import Any

import requests

try:
    import config
    BOT_TOKEN = getattr(config, "TELEGRAM_BOT_TOKEN", "8795048754:AAHXbXFhzTHa6ICvwyQ1sE2pBvb-ZgqZIac")
    CHAT_ID = getattr(config, "TELEGRAM_CHAT_ID", "-5299125247")
except Exception:
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8795048754:AAHXbXFhzTHa6ICvwyQ1sE2pBvb-ZgqZIac")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-5299125247")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def send_telegram_message(
    text: str,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
    timeout: int = 15,
) -> bool:
    """Send text message to configured Telegram chat.
    
    Safe function: never raises an uncaught exception that could crash caller.
    """
    if not BOT_TOKEN or not CHAT_ID:
        print("[telegram_notifier] Missing BOT_TOKEN or CHAT_ID, message not sent.")
        return False

    # Telegram message text length limit is 4096 characters
    if len(text) > 4000:
        text = text[:3950] + "\n... [обрезано]"

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }

    try:
        resp = requests.post(TELEGRAM_API_URL, json=payload, timeout=timeout)
        if resp.status_code != 200:
            print(f"[telegram_notifier] Failed to send message: HTTP {resp.status_code}: {resp.text}")
            return False
        return True
    except Exception as exc:
        print(f"[telegram_notifier] Error sending message to Telegram: {exc}")
        return False


def send_telegram_alert(
    service_name: str,
    error_message: str | Exception,
    details: str | dict[str, Any] | None = None,
) -> bool:
    """Send standardized failure alert to Telegram."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    err_text = str(error_message)
    if isinstance(error_message, Exception) and not details:
        details = traceback.format_exc()

    lines = [
        f"🚨 <b>Сбой синхронизации: {service_name}</b>",
        f"⏰ <b>Время:</b> <code>{now_str}</code>",
        f"❌ <b>Ошибка:</b> <code>{err_text}</code>",
    ]

    if details:
        details_str = str(details)
        if len(details_str) > 1500:
            details_str = details_str[-1500:]  # keep the most recent traceback
        lines.append(f"\n<b>Детали:</b>\n<pre>{details_str}</pre>")

    text = "\n".join(lines)
    return send_telegram_message(text, parse_mode="HTML")
