# Ключи API извлеченные из 1С

**Дата извлечения:** 30 марта 2026  
**Источник:** `dtx_РегламентноеОбновлениеЦенИОстатковПоНоменклатуреПоставщиков (новый логин и пароль ЭТМ, новое апи ферона).epf`

---

## 🔑 API ФЕРОНА

### Активный API (Внуково) - используется с 23.10.2025

```1c
Функция КлючАпиFeronВнуково()
    Возврат "server ZjA5MDg3MTAtNjQ5ZS00ODU5LWJjNjktY2NkY2E1ZDdlNjUx";	
КонецФункции

Функция СерверFeronВнуково()
    Возврат "api.feron.ru";	
КонецФункции
```

**Параметры:**
- **URL:** `https://api.feron.ru`
- **Authorization:** `server ZjA5MDg3MTAtNjQ5ZS00ODU5LWJjNjktY2NkY2E1ZDdlNjUx`
- **Endpoints:**
  - `POST /offers/products/search` - поиск товаров
  - `POST /quantities/search` - получение остатков

### Старый API (закомментирован)

```1c
Функция СерверFeron()
    Возврат "clientapi.shop.feron.ru";	
КонецФункции

Функция КлючАпиFeron()
    //Возврат "ZjA5MDg3MTAtNjQ5ZS00ODU5LWJjNjktY2NkY2E1ZDdlNjUx";
    Возврат "OTdhM2U0ZDAtOTc3Ni00YTBjLThhNzQtNWExNGZiYzNjMjFm";
КонецФункции
```

**Параметры:**
- **URL:** `https://clientapi.shop.feron.ru`
- **API Key:** `OTdhM2U0ZDAtOTc3Ni00YTBjLThhNzQtNWExNGZiYzNjMjFm`
- **Статус:** Не используется (закомментирован в коде)

---

## 🏢 ID СКЛАДОВ ФЕРОНА

```1c
СкладВнуково = "de099cee-372a-11ef-96b6-a4bf0186f0c7";
СкладСамара = "67e4fb8a-6e27-11ef-96b6-a4bf0186f0c7";
```

**Дополнительно найдено при тестировании API:**
- **Новосибирск:** `ab50cafe-6e27-11ef-96b6-a4bf0186f0c7`

---

## 📊 СТРУКТУРА API ФЕРОНА

### Шаг 1: Поиск товара по артикулу

```http
POST https://api.feron.ru/offers/products/search
Authorization: server ZjA5MDg3MTAtNjQ5ZS00ODU5LWJjNjktY2NkY2E1ZDdlNjUx
Content-Type: application/json

{
  "size": 100
}
```

**Ответ:**
```json
{
  "items": [
    {
      "product_id": "000871e6-cfb0-11e9-812f-b0c554fff378",
      "vendor_code": "38029",
      "name": "Лампа светодиодная Feron.PRO LB-1011...",
      "brand": "FERON",
      "model": "LB-1011"
    }
  ],
  "search_token": "..."
}
```

### Шаг 2: Получение остатков по product_id

```http
POST https://api.feron.ru/quantities/search
Authorization: server ZjA5MDg3MTAtNjQ5ZS00ODU5LWJjNjktY2NkY2E1ZDdlNjUx
Content-Type: application/json

{
  "products_id": ["000871e6-cfb0-11e9-812f-b0c554fff378"]
}
```

**Ответ:**
```json
{
  "items": [
    {
      "product_id": "000871e6-cfb0-11e9-812f-b0c554fff378",
      "warehouse_name": "Самара",
      "warehouse_id": "67e4fb8a-6e27-11ef-96b6-a4bf0186f0c7",
      "value": {
        "text": "100",
        "quantity": 100,
        "limited": false
      }
    },
    {
      "product_id": "000871e6-cfb0-11e9-812f-b0c554fff378",
      "warehouse_name": "Новосибирск",
      "warehouse_id": "ab50cafe-6e27-11ef-96b6-a4bf0186f0c7",
      "value": {
        "text": "158",
        "quantity": 158,
        "limited": false
      }
    },
    {
      "product_id": "000871e6-cfb0-11e9-812f-b0c554fff378",
      "warehouse_name": "Внуково",
      "warehouse_id": "de099cee-372a-11ef-96b6-a4bf0186f0c7",
      "value": {
        "text": ">500",
        "quantity": 500,
        "limited": true
      }
    }
  ]
}
```

---

## ✅ ТЕСТИРОВАНИЕ API

**Дата теста:** 30 марта 2026  
**Артикул:** 38029 (LB-1011)

**Результаты:**
- ✅ Самара: 100 шт
- ✅ Новосибирск: 158 шт  
- ✅ Внуково: >500 шт (ограничено)

**Статус:** API работает корректно!

---

## 📝 ПРИМЕЧАНИЯ

1. **Метод авторизации:** Статический токен в заголовке `Authorization`
2. **Формат токена:** `server <base64_token>`
3. **Двухэтапный процесс:** Сначала поиск товара по `vendor_code`, затем получение остатков по `product_id`
4. **Rate limiting:** Рекомендуется пауза 2 секунды между запросами (2 запроса на товар)
5. **Минимальный размер выборки:** `size` должен быть >= 10

---

## 🔧 ИСПОЛЬЗОВАНИЕ В КОДЕ

### Python (feron_sync_local.py)

```python
FERON_API_KEY = "server ZjA5MDg3MTAtNjQ5ZS00ODU5LWJjNjktY2NkY2E1ZDdlNjUx"
FERON_API_URL = "https://api.feron.ru"

# ID складов
FERON_WAREHOUSE_VNUKOVO = "de099cee-372a-11ef-96b6-a4bf0186f0c7"
FERON_WAREHOUSE_SAMARA = "67e4fb8a-6e27-11ef-96b6-a4bf0186f0c7"
FERON_WAREHOUSE_NOVOSIBIRSK = "ab50cafe-6e27-11ef-96b6-a4bf0186f0c7"
```

### 1С (код из обработки)

```1c
Соединение = Новый HTTPСоединение(СерверВнуково, Порт, , , , , SSL);

ЗапросНоменклатураСайта = Новый HTTPЗапрос;
ЗапросНоменклатураСайта.Заголовки.Вставить("accept", "application/json");
ЗапросНоменклатураСайта.Заголовки.Вставить("Content-Type", "application/json");
ЗапросНоменклатураСайта.Заголовки.Вставить("Authorization", КлючАПИВнуково);
ЗапросНоменклатураСайта.АдресРесурса = "/offers/products/search";
```

---

## 📚 ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ

**Файлы проекта:**
- `feron_sync_local.py` - Python скрипт синхронизации
- `config_example.py` - конфигурация с ключами
- `Синхронизация остатков Feron.gs` - Google Apps Script
- `ИТОГ.txt` - полная документация проекта

**Извлечено с помощью:**
- `parse-1c-build` (Python пакет)
- `v8unpack` (утилита для файлов 1С)

---

*Документ создан автоматически при распаковке .epf файла*