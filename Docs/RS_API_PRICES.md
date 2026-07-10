# RS API — Получение цен по артикулу

## Алгоритм

### 1. Получить карту соответствия Артикул → Код РС

Запрос: `GET /position/{warehouseId}/instock?page={N}&rows=1000`

Перебираем все страницы (лимит 1000 записей на страницу). На выходе — словарь:

```
{
  "4690612030968": "563726",
  "mb54-3": "100348",
  ...
}
```

### 2. Массово получить цены по кодам РС

Запрос: `POST /massprice`

Тело:
```json
{ "items": ["563726", "100348", "100458", ...] }
```

Лимит: **до 50 кодов** за один запрос.

Ответ (массив):
```json
[
  {
    "RSCode": "563726",
    "Price": {
      "Personal": 69.26,
      "Personal_w_VAT": 84.50,
      "Retail": 96.00,
      "Retail_w_VAT": 117.12,
      "Base": 106.56,
      "Base_w_VAT": 130.00,
      "MRC": 71.61,
      "MRC_w_VAT": 87.36,
      "AvailabilityMRC": "N"
    }
  },
  ...
]
```

### 3. Собрать результат

Для каждого исходного артикула → найти Код РС → найти Personal_w_VAT.

---

## Интересующие нас поля цен (когда НДС)

| Поле | Назначение | Пример |
|------|-----------|--------|
| **`Personal_w_VAT`** | **Цена клиента со скидкой, с НДС** ← **это зелёный ценник** | **84.50 ₽** |
| `Personal` | Цена клиента со скидкой, без НДС | 69.26 ₽ |
| `Retail_w_VAT` | Розничная цена с НДС | 117.12 ₽ |
| `MRC_w_VAT` | МРЦ с НДС | 87.36 ₽ |

Для выгрузки на Wildberries/Ozon обычно берём **`Personal_w_VAT`** — это наша закупочная цена с НДС.

Если работаем без НДС — берём **`Personal`**.

---

## Схема работы

```
Артикул (vendor_code)
    │
    ▼
┌─────────────────────────────┐
│ GET /position/{whId}/instock│  ← 1 раз за сессию (кешируем карту)
│ ?page=1..N&rows=1000        │
│                             │
│ Строим:                     │
│ vendor_code → RS_CODE       │
│ (напр. 4690612030968→563726)│
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ POST /massprice             │  ← батчами по 50 кодов
│ { "items": [RS_CODE, ...] } │
│                             │
│ Получаем:                   │
│ RS_CODE → Personal_w_VAT    │
│ (напр. 563726→84.50)        │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ Готово:                     │
│ Артикул → Цена с НДС        │
└─────────────────────────────┘
```

---

## Ограничения и особенности

| Параметр | Значение |
|----------|----------|
| Лимит `/massprice` | 50 кодов на запрос |
| Лимит `/position` | 1000 записей на страницу |
| Rate limit | 150 запросов / 30 сек на IP |
| Авторизация | Basic Auth (логин/пароль от rs24.ru) |
| Склады | 287 — Самара, 96 — Тольятти, 14030 — Москва и др. |
| Base URL | `https://cdis.russvet.ru/rs` |
| Прокси (для GAS) | `https://holy-hall-9741.jilighyt4591667.workers.dev` |

---

## Пример (Python, массовый)

```python
import requests, base64

# 1. Авторизация
auth = base64.b64encode(b"login:password").decode()
headers = {"Authorization": f"Basic {auth}"}

# 2. Собираем карту артикулов (1 раз)
code_map = {}
for page in range(1, 26):  # 25 страниц по 1000
    r = requests.get(
        f"https://cdis.russvet.ru/rs/position/287/instock?page={page}&rows=1000",
        headers=headers, timeout=60
    )
    for item in r.json().get("items", []):
        code_map[item["VENDOR_CODE"].strip()] = item["CODE"]

# 3. Получаем цены батчами по 50
prices = {}
rs_codes = [code_map[a] for a in articles if a in code_map]
for i in range(0, len(rs_codes), 50):
    batch = rs_codes[i:i+50]
    r = requests.post(
        "https://cdis.russvet.ru/rs/massprice",
        headers={**headers, "Content-Type": "application/json"},
        json={"items": batch}, timeout=30
    )
    for item in r.json():
        prices[item["RSCode"]] = item["Price"]["Personal_w_VAT"]

# 4. Результат: артикул → цена с НДС
for article in articles:
    rs_code = code_map.get(article)
    price = prices.get(rs_code)
    print(f"{article} → {price} ₽")
```
