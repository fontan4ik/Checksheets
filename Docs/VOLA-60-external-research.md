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
