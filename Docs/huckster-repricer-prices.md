# Huckster Repraiser → Checksheets: цены

## Источник

Официальная документация Huckster:
<https://wiki.huckster.ru/prochie-instrukcii/rukovodstvo-polzovatelya-po-rabote-s-api-repraisera-huckster>

API base URL: `https://wbs.e-teleport.ru`.

## Используемые методы

1. `POST /md5` — получает MD5-хэш пароля.
2. `POST /auth/credentials` — получает краткоживущую `SessionId`.
3. `POST /markets/integrations/accounts/list` — определяет кабинеты и `shop_id`.
4. `POST /markets/integrations/repricer/items/list` — получает товары стратегии «Удержание РРЦ».

Документация указывает передачу сессии в исходящем заголовке `set-cookie: ss-id=<SessionId>`. В коде используется именно этот формат.

## Маппинг в таблицу

| Колонка | Поле Huckster | Смысл |
|---|---|---|
| BN (66) | `market_price` | текущая цена на маркетплейсе |
| BO (67) | `upload_price` | цена, подготовленная/загруженная Huckster; используется как рекомендуемая |

Сопоставление товаров: сначала колонка V (`SKU Ozon`), затем колонка A (`offer_id`) как fallback. Обновляются только BN и BO листа `ТЕСТ`.

## Безопасность и запуск

- Логин и пароль не находятся в репозитории и не выводятся в лог.
- Credentials должны быть записаны в Script Properties под ключами `HUCKSTER_USER_NAME` и `HUCKSTER_PASSWORD`.
- Если кабинетов Ozon несколько, нужно задать `HUCKSTER_SHOP_ID`; автоматический выбор в таком случае отключён.
- Скрипт не вызывает методы `set`, `update` или `add` Huckster и не меняет цены на маркетплейсе.
- Основная функция для ручного запуска после проверки credentials: `updateHucksterPrices()`.
- Read-only проверка без записи в таблицу: `checkHucksterConnection()`.
