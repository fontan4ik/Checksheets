# Имена файлов Apps Script

Формат: `List_<лист>__<колонки>__<назначение>.js`; для процессов нескольких листов — `Flow_`, для общих функций — `Shared_`, для диагностики — `Diagnostic_`. Имена функций триггеров не менялись.

| Было | Стало |
| --- | --- |
| `1C остатки.js` | `List_1С_остатки__Таблица__Импорт.js` |
| `Alright API.js` | `List_ARL_TR__F__Транзисторы.js` |
| `DIAGNOSTICS.js` | `Diagnostic_Система.js` |
| `Huckster цены.js` | `Flow_ТЕСТ_ARL_TR__Цены_Huckster.js` |
| `O квартал.js` | `List_UNIT_API_квартал__РасчетныеПоля__Ozon.js` |
| `O.js` | `List_UNIT_API__РасчетныеПоля__Ozon.js` |
| `Ozon Buyout.js` | `List_UNIT_API__УПД__Ozon.js` |
| `Ozon FBS склады.js` | `List_ТЕСТ__AB_AH__Склады_Ozon_FBS.js` |
| `Ozon Получить товары.js` | `List_ТЕСТ__A_U__ProductId_Ozon.js` |
| `Ozon Продажи НТЦ.js` | `List_ТЕСТ__BM__Продажи_НТЦ.js` |
| `Ozon возвраты и отмены.js` | `List_ТЕСТ__BH_BI__Отмены_Возвраты_Ozon.js` |
| `Ozon заказы.js` | `List_ТЕСТ__I_J_L_AO__Заказы_Ozon.js` |
| `Ozon индекс.js` | `List_ТЕСТ__BK__Индекс_Ozon.js` |
| `Ozon обновить товары V2.js` | `List_ТЕСТ__C_E_V_X_Y__Товары_Ozon.js` |
| `Ozon остатки FBO.js` | `List_ТЕСТ__F_G__Остатки_Ozon.js` |
| `Ozon отзывы.js` | `List_ТЕСТ__BL__Отзывы_Ozon.js` |
| `Ozon платное хранение.js` | `List_ТЕСТ__BJ__Хранение_Ozon.js` |
| `Ozon продажи FBO FBS.js` | `List_ТЕСТ__AQ_AT__Продажи_Ozon.js` |
| `Ozon реклама V3.js` | `List_ТЕСТ__BA_BC__Реклама_Ozon_Performance.js` |
| `Ozon реклама.js` | `List_ТЕСТ__AU__Реклама_Ozon.js` |
| `Ozon склад Москва.js` | `List_ТЕСТ__H__Склад_Москва_Ozon.js` |
| `Ozon цена по карте.js` | `List_ТЕСТ__BG__Цена_по_карте_Ozon.js` |
| `Ozon цена.js` | `List_ТЕСТ__K_BR__Цена_Ozon.js` |
| `TelegramNotifier.js` | `Shared_Telegram.js` |
| `WB Unit.js` | `List_UNIT_WB__Финансы_API__WB.js` |
| `WB Аналитика.js` | `List_ТЕСТ__R_S__Аналитика_WB.js` |
| `WB Артикулы.js` | `List_ТЕСТ__T__Артикулы_WB.js` |
| `WB Тех данные.js` | `List_ТЕХ_данные_wb__Таблица__WB.js` |
| `WB склады.js` | `List_ТЕСТ__Z_AA__Склады_WB.js` |
| `fetchapp.js` | `Shared_HTTP.js` |
| `settings.js` | `Shared_Настройки.js` |
| `Без названия 3.js` | `Diagnostic_API_токен.js` |
| `Без названия.js` | `Diagnostic_Продажи.js` |
| `ВБ заказы.js` | `List_ТЕСТ__N_AP__Заказы_WB.js` |
| `ВБ остатки.js` | `List_ТЕСТ__O__Остатки_WB_FBO.js` |
| `ВБ продажи FBO FBS.js` | `List_ТЕСТ__AV_AY__Продажи_WB.js` |
| `ВБ.js` | `List_ТЕСТ__P_Q__Остатки_WB_FBS.js` |
| `Главные функции.js` | `Flow_Триггеры__Основные.js` |
| `Годовые продажи.js` | `List_ТЕСТ__BD_BE__Годовые_продажи.js` |
| `Диагностика RS.js` | `Diagnostic_RS_API.js` |
| `НТЦ списания.js` | `Flow_НТЦ_списания__FBS_резерв.js` |
| `ОБОР формулы.js` | `List_ОБОР__РасчетныеПоля__Сводка.js` |
| `Обнуление.js` | `Flow_StreamSupps__Обнуление_Ozon.js` |
| `Синхронизация остатков Ozon НТЦ в Яндекс.js` | `Flow_UNIT_YNX__Остатки_НТЦ_Яндекс.js` |
| `Синхронизация остатков поставщиков в Яндекс.js` | `Flow_UNIT_YNX__Остатки_поставщиков_Яндекс.js` |
| `Цены ВБ.js` | `List_ТЕСТ__M__Цена_WB.js` |

Заголовки `ТЕСТ!A` пустой, `Артикул WB` (T и AN) и заголовки продаж AQ:AT/AV:AY повторяются. Для них числовые адреса сохранены до отдельной правки шапки листа.

Триггер `updateOzonFBOSales` теперь оставлен как совместимый вход без тяжёлого обхода. AQ:AT обновляет локальный `ozon_fbo_fbs_sales_local.js`. Аналогично `updateOzonReviewCountBL` не дублирует действующий локальный `ozon_reviews_local.js`.
