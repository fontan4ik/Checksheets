# Huckster Repraiser → Checksheets: цены

## Источник

Официальная документация Huckster:
<https://wiki.huckster.ru/prochie-instrukcii/rukovodstvo-polzovatelya-po-rabote-s-api-repraisera-huckster>

API base URL: `https://wbs.e-teleport.ru`.

## Используемые методы

### Read-only выгрузка в лист «ТЕСТ»

1. `POST /md5` — получает MD5-хэш пароля.
2. `POST /auth/credentials` — получает краткоживущую `SessionId`.
3. `POST /markets/integrations/accounts/list` — определяет кабинеты и `shop_id`.
4. `POST /markets/integrations/repricer/items/list` — получает товары стратегии «Удержание РРЦ».

### Запись цен из листа «ARL TR»

1. `POST /markets/integrations/repricer/items/set` — записывает `min_price`.
2. `POST /catalog_updatePrice` — записывает базовую розничную (`retail_price`) цену.
3. `POST /markets/price_types/list` — получает `price_type_id` дополнительного типа «РЦ Озон».
4. `POST /markets/items/prices/update` — записывает цену дополнительного типа «РЦ Озон».

Документация Huckster указывает заголовок `set-cookie: ss-id=<SessionId>`. В текущей рабочей интеграции авторизованный запрос отправляется через обычный request-заголовок `Cookie: ss-id=<SessionId>`.

## Маппинг в таблицу

### Лист «ТЕСТ» (read-only выгрузка)

| Колонка | Поле Huckster | Смысл |
|---|---|---|
| BN (66) | `upload_price` | текущая выставленная/загруженная цена |
| BO (67) | `market_card_price` | цена по карте / РЦ для удержания |
| колонка с заголовком `Цена на витрине с картой Х` | `market_card_price` | текущая цена на витрине с картой |
| колонка с заголовком `Мин цена продажи Х` | `min_price` | минимальная цена продажи |

### Лист «ARL TR» (запись в Huckster)

| Колонка | Поле/метод Huckster | Смысл |
|---|---|---|
| U (21), `МИНИМАЛЬНАЯ ХАКСТЕР` | `min_price` → `repricer/items/set` | минимальная цена продажи |
| W (23), `ВЫСТАВЛЯЕМАЯ ХАКСТЕР` | `retail_price` → `catalog_updatePrice` | базовая выставляемая/розничная цена |
| X (24), `РЦ ХАКСТЕР` | `retail_price` + тип `РЦ Озон` → `markets/items/prices/update` | дополнительная цена РЦ |

Сопоставление товаров для записи выполняется по артикулу из колонки A (`offer_id`) с полем `sku` или `uid` из ответа Huckster. Пустые значения U/W/X не отправляются; значения `0` считаются явным числом. Для `catalog_updatePrice` скрипт предварительно получает текущую закупочную цену через `catalog_get`, чтобы не затирать её.

## Безопасность и запуск

- Логин и пароль не находятся в репозитории и не выводятся в лог.
- В начале `Huckster цены.js` поля `HUCKSTER_USER_NAME`, `HUCKSTER_PASSWORD` и `HUCKSTER_SHOP_ID` пустые. Все три значения задаются в Script Properties Apps Script с такими же ключами; секреты не записываются в исходный файл.
- Если `HUCKSTER_SHOP_ID` пустой и кабинетов Ozon несколько, скрипт остановится без записи и попросит задать идентификатор.
- `updateHucksterPrices()` выполняет только read-only выгрузку в «ТЕСТ».
- `syncHucksterPricesFromArlTr()` выполняет запись в Huckster только при ручном запуске и обрабатывает товары пачками до 100.
- Перед первым live-запуском необходимо проверить сформированные payload и получить отдельное подтверждение на запись цен в Huckster.
- Единственная функция для read-only запуска: `updateHucksterPrices()`; функция записи: `syncHucksterPricesFromArlTr()`.
