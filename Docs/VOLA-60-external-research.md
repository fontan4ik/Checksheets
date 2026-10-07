# VOLA-60 — Ozon TN VED candidate matching and marking flag

Дата: 2026-10-07. Marketplace API writes не выполнялись.

## Вывод по новому указанию владельца

Для пяти названных IEK контакторов из доступных Ozon-значений выбираю кандидат `8536490000` — полное описание в записи Ozon: «Прочие реле, на напряжение не более 1000 В» (в исходном issue указаны dictionary IDs 971400163/972997573; attribute ID 22232; category/type 17028654/99040).

Это наиболее подходящий сохранённый кандидат по известному назначению изделий: IEK KMIe — электромагнитные контакторы, выполняющие коммутацию силовых цепей/управление электродвигателями; класс 8536.49 охватывает прочие реле/аппараты соответствующего рода на напряжение не более 1000 В. Указанные в артикулах суффиксы 110/230 относятся к напряжению катушки управления, а не являются сами по себе свидетельством полного номинала силовой цепи; их не использовал как единственное доказательство. Запись словаря Ozon и эта техническая аналогия дают разумный candidate для продолжения карточки, но не обязательное юридическое классификационное решение.

Ограничение: из имеющихся локальных артефактов нельзя восстановить полный актуальный набор всех TN VED candidates и их полные описания для данной category/type. Поэтому утверждать, что `8536490000` уникально лучше каждого другого возможного dictionary-кандидата, нельзя. Сравнительная подборка ниже ограничена точно зафиксированными в задаче данными Ozon.

## SKU mapping

IEK product status report фиксирует точное получение всех пяти supplier records из IEK API и 14 ETIM характеристик для каждого. Но report не сохраняет сами 14 значений по SKU. Точный список:

| IEK SKU | Ozon TN VED candidate | Основание и предел |
|---|---|---|
| `KKME11-012-230-10` | `8536490000` | KMIe contactor; description candidate «прочие реле ≤1000 В» соответствует назначению класса. SKU-specific values для силового напряжения в артефакте не зафиксированы. |
| `KKME11-018-230-10` | `8536490000` | То же семейство и назначение; IEK API exact record есть, но individual ETIM values не записаны. |
| `KKME11-009-230-10` | `8536490000` | То же семейство и назначение; IEK API exact record есть, но individual ETIM values не записаны. |
| `KKME21-025-110-10` | `8536490000` | KMIe contactor; `110` в строке SKU не принят за product-rated voltage evidence. Exact ETIM values не записаны. |
| `KKME31-040-230-11` | `8536490000` | KMIe contactor; `230` в строке SKU не принят за product-rated voltage evidence. Exact ETIM values не записаны. |

Фактическая IEK API выдача подтверждена отчётом `Docs/VOLA-37-implementation-status.md`, раздел «Verified supplier data», строки таблицы 11–19; источник получения — IEK product API, documented loader `iek_stock_sync_local.get_api_key()` + client login + GET `/api/catalog/v1/client/products/{article}`. Этот status report документирует числа ETIM attributes, но не их содержимое. `test/test_iek_marketplace_mapper.py` содержит лишь synthetic fixture 12 A AC-3/400 V и Us 230 V AC для одной тестовой модели; это не exact-SKU evidence и в таблицу не переносилось.

## Boolean Ozon attribute 23536 — маркировка

Live schema finding, ранее зафиксированный в issue: attribute `23536` is Boolean, `dictionary_id=0`, meaning whether statutory product marking code is required. Это не barcode, не DataMatrix и не операция генерации marketplace barcode.

Для пяти SKU значение `true` или `false` пока не доказано доступными записями. IEK API summary/ETIM count и Ozon schema не устанавливают попадание товаров в применимый перечень обязательной маркировки. Флаг оставлен unresolved; не заполнять произвольным default. Marketplace barcode, уже имеющийся в IEK logistics, — отдельное поле.

## Проверенные ссылки и ограничения

- IEK public contactor category: https://www.iek.ru/products/catalog/produktsiya_kontaktor
- IEK public LIA listing: https://www.iek.ru/products/catalog/produktsiya_kontaktor/limitirovannyy_importnyy_assortiment_lia_kontaktor — текущий публичный листинг не содержит данные KMIe SKU.
- IEK API/Infobase overview: https://www.iek.ru/support/api/ — описаны API и выгрузки XML + связанные архивы документов; сами product XML/сертификаты не были публично доступны в текущей проверке.
- Ozon code candidate description/dictionary IDs/category/type — сохранены в issue description и локальных research notes; не получено отдельной свежей выгрузки полного словаря в этом run.

## Статус и безопасное продолжение

В VOLA-52 передан выбранный Ozon dictionary candidate `8536490000` и ограничения его доказательности; это передача выбранного подходящего доступного значения, а не присвоение выдуманного кода. Для окончательного техничного payload следует восстановить индивидуальные ETIM values из пяти IEK API records и сверить voltage/function; для `23536` по-прежнему требуется основание применимости обязательной маркировки. До подтверждения Boolean и успешной payload validation marketplace listing writes запрещены.

Публикация не выполнялась. VAT 0.22 и seller price/RRC не менялись.

## Повторный точный read и нормативная проверка (2026-10-07, 16:25 UTC)

Повторно прочитаны точные product records через штатный авторизованный IEK loader, а не по тестовому fixture: `iek_stock_sync_local.get_api_key()` → `create_session()` → `login()` → GET `https://bp.iek.ru/api/catalog/v1/client/products/{article}`. Во всех пяти ответах `article` в точности совпал с запросом. Получены поля `etim.class`, технические характеристики, `feacn`, `okpd2Code`, `isMarked` и `chestnyZnakProductGroup`:

| IEK SKU | ETIM class / name | AC-3 Ie @400 V | Switching power @400 V | Coil Us AC 50 Hz | Insulation Ui | IEK feacn | IEK OKPD2 | IEK marking fields |
|---|---|---:|---:|---:|---:|---|---|---|
| `KKME11-009-230-10` | `EC000066` — Магнитный пускатель или контактор переменного тока | 9 A | 4 kW | 230 V | 660 V | `8536490000` | `27.12.24.190` | `isMarked=true`; group `Радиоэлектронная продукция` |
| `KKME11-012-230-10` | `EC000066` — Магнитный пускатель или контактор переменного тока | 12 A | 5.5 kW | 230 V | 660 V | `8536490000` | `27.12.24.190` | `isMarked=true`; group `Радиоэлектронная продукция` |
| `KKME11-018-230-10` | `EC000066` — Магнитный пускатель или контактор переменного тока | 18 A | 7.5 kW | 230 V | 660 V | `8536490000` | `27.12.24.190` | `isMarked=true`; group `Радиоэлектронная продукция` |
| `KKME21-025-110-10` | `EC000066` — Магнитный пускатель или контактор переменного тока | 25 A | 11 kW | 110 V | 660 V | `8536490000` | `27.12.24.190` | `isMarked=true`; group `Радиоэлектронная продукция` |
| `KKME31-040-230-11` | `EC000066` — Магнитный пускатель или контактор переменного тока | 40 A | 18.5 kW | 230 V | 660 V | `8536490000` | `27.12.24.190` | `isMarked=true`; group `Радиоэлектронная продукция` |

IEK description for the family says these KMIe contactors start, stop, and reverse squirrel-cage asynchronous motors up to 660 V (AC-3) and switch lighting/heating/low-inductance loads (AC-1). That exact API record supplies its own `feacn=8536490000`; it is not merely the Ozon dictionary value. The Ozon attribute `22232` candidate remains the already documented dictionary entry `8536490000` (“Прочие реле, на напряжение не более 1000 В”, IDs recorded in issue description 971400163/972997573). Individual operating voltage is 660 V max, within the dictionary description's ≤1000 V threshold; the coil voltages are separately captured and are not substituted for the main circuit rating. This supports selecting the existing Ozon dictionary value for all five exact SKU. A fresh complete download of every Ozon dictionary page was not available in this execution environment (Ozon credentials are not exposed to this run), so this is not a claim that every alternative Ozon dictionary value was exhaustively compared.

### Official mandatory-marking scope

The current rule found is Russian Government Resolution 28.11.2025 No. 1954, “Rules for marking certain types of radio-electronic products”, effective for the relevant phases in 2026. Its annex expressly lists:

- TN VED `8536 49 000 0` — “реле на напряжение не более 1000 В”;
- OKPD2 `27.12.24` for that row;
- marking of products in scope from 1 May 2026, with transition provisions in the annex.

The same annex's entry is published at https://www.consultant.ru/document/cons_doc_LAW_520196/90c8fb9b9f132fd761cd66409a24c565d9b19e2a/ (table row explicitly pairs TN VED 8536 49 000 0 with OKPD2 27.12.24 and the name “реле на напряжение не более 1000 В”). IEK's exact records give the matching TN VED and OKPD2 subcode `27.12.24.190`, and the supplier also marks all five records `isMarked=true` with group `Радиоэлектронная продукция`. Therefore the evidence supports Ozon Boolean `23536 = true` for each of these SKUs. This is the mandatory marking requirement, not a request for Ozon to generate a marketplace barcode. Existing IEK barcode remains a separate logistics/barcode field.

The public source is an accessible legal-reference reproduction of the resolution and annex, not the official publication portal; exact primary legal document identity and cited annex row are explicit. Product-specific code/OKPD2/group fields independently match the scope. Before any actual product import, VOLA-52 should still validate the then-current Ozon schema and payload; no marketplace write occurred in this task.

### Disposition / handoff

Confirmed handoff values for VOLA-52: Ozon TN VED dictionary value `8536490000`; Ozon Boolean `23536=true`; applicable to all five SKU listed above. Verified IEK technical and compliance fields are in the table. Values are source-backed; the code is not guessed. No fresh Ozon full dictionary dump was obtained, but the selected entry already exists in the authorized category/type evidence in the issue. No other blocking ambiguity remains for the requested TN VED/marking values on these SKUs. Preserve VAT `0.22` and seller price/RRC unchanged. Marketplace publication is outside this research note and was not performed.
