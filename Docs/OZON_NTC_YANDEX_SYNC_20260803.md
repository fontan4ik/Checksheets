# Ozon НТЦ → Yandex Market sync

Дата: 2026-08-03

## Что сделано

- Добавлен Apps Script-файл `Синхронизация остатков Ozon НТЦ в Яндекс.js`.
- Главная функция: `syncOzonNtcStocksToYandex()`.
- Источник: лист `UNIT YNX`, `A` = `art` / ShopSku Яндекс.
- Назначение остатка в таблице: `Y` = `НТЦ STOCK`.
- Ozon:
  - получает список складов через актуальный `POST /v2/warehouse/list`;
  - выбирает единственный склад по имени с точным совпадением `НТЦ СКЛАД`;
  - получает остатки через `POST /v2/product/info/stocks-by-warehouse/fbs`;
  - использует семантику проекта `present + reserved`.
- Yandex:
  - кампания `149209348` (`ВольтМир НТЦ`, FBS);
  - передача через `PUT /v2/campaigns/{campaignId}/offers/stocks`;
  - батчи до 2000 SKU.
- Добавлена одноразовая ручная функция `setupYandexMarketApiKey()`: ключ хранится только в Script Properties под именем `YANDEX_MARKET_API_KEY`, не в исходном коде.
- Добавлена read-only проверка `verifyYandexNtcConfiguration()`.
- Добавлен Script Lock, чтобы параллельные часовые запуски не пересекались.

## Проверка

- `node --check 'Синхронизация остатков Ozon НТЦ в Яндекс.js'` — успешно.
- Проверен live Ozon API: старые `v1` методы отвечают `obsolete method cannot be used`; актуальные `v2` методы работают.
- Live Ozon подтвердил склад `НТЦ СКЛАД`.
- Live Yandex подтвердил кампанию `ВольтМир НТЦ`, FBS, `AVAILABLE`.
- В `UNIT YNX` найдено 15 414 строк с `art`; 15 405 сопоставляются с Ozon SKU из `ТЕСТ!A:V`.
- Cloud Apps Script read-back: файл присутствует, SHA-256 локального и cloud-файла совпадает:
  `c945870bcbb97a43ec126d4b0b15cd5d7d9613bc7896ff4c23f7840ae7076cd5`.
- Токен в локальном и cloud-исходнике отсутствует.

## Что не выполнялось

- Часовой триггер не создавался.
- Реальная запись остатков в Яндекс не запускалась.
- API-ключ в Script Properties не устанавливался агентом.

## Ручной запуск Владимиром

1. В редакторе Apps Script один раз выполнить `setupYandexMarketApiKey()` и вставить ключ в диалог.
2. Выполнить `verifyYandexNtcConfiguration()` — read-only проверка доступа.
3. Создать часовой time-driven trigger на `syncOzonNtcStocksToYandex`.

Текущий фактический заголовок `UNIT YNX!I` — `Д`, а не «цены выставляемые». Скрипт цены не меняет и для передачи остатков не использует: официальный Yandex stock endpoint принимает SKU и количество.

## Откат

Локальная копия перед последним cloud-обновлением: `test/tmp/apps-script-local-backup-20260803_171458/`.
Для отката cloud-файла нужно заменить только добавленный Apps Script-файл на сохранённую согласованную версию; триггеры и Script Properties этим изменением не затрагиваются.
