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

Документация указывает `set-cookie: ss-id=<SessionId>`, но фактический API принимает авторизованный запрос через обычный request-заголовок `Cookie: ss-id=<SessionId>`.

## Маппинг в таблицу

| Колонка | Поле Huckster | Смысл |
|---|---|---|
| BN (66) | `upload_price` | текущая выставленная/загруженная цена |
| BO (67) | `market_card_price` | рекомендуемая цена / РЦ для удержания |

Сопоставление товаров: сначала колонка V (`SKU Ozon`), затем колонка A (`offer_id`) как fallback. Обновляются только BN и BO листа `ТЕСТ`.

## Безопасность и запуск

- Логин и пароль не находятся в репозитории и не выводятся в лог.
- В начале `Huckster цены.js` есть пустые поля `HUCKSTER_USER_NAME`, `HUCKSTER_PASSWORD` и `HUCKSTER_SHOP_ID`; их можно заполнить вручную. Для логина/пароля при пустых inline-полях используются Script Properties с такими же ключами.
- Если `HUCKSTER_SHOP_ID` пустой и кабинетов Ozon несколько, скрипт остановится без записи и попросит задать идентификатор.
- Скрипт не вызывает методы `set`, `update` или `add` Huckster и не меняет цены на маркетплейсе.
- Единственная функция верхнего уровня для ручного запуска: `updateHucksterPrices()`.
