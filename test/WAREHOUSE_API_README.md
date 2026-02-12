# WB Склады - Тестовые данные и план разработки

## 📁 Файлы

| Файл | Описание |
|------|----------|
| [mock_wb_stocks_api.json](mock_wb_stocks_api.json) | Statistics API - остатки по всем складам WB |
| [mock_wb_warehouses_api.json](mock_wb_warehouses_api.json) | Supplier API - список складов продавца |
| [mock_wb_stocks_supplier_api.json](mock_wb_stocks_supplier_api.json) | Supplier API - остатки на конкретном складе |

---

## 🎯 План разработки

### Фаза 1: Склады WB по warehouseName (Z, AA, AI, AJ)

**Файл:** `WB Склады.gs`

**Логика:**
1. GET `/api/v1/supplier/stocks` - получить ВСЕ остатки
2. Фильтровать по `warehouseName` (частичное совпадение)
3. Агрегировать по `supplierArticle`

**Фильтры:**
```javascript
const warehouseFilters = {
  Z:  { column: 26, name: "ФЕРОН МОСКВА", filter: (n) => n.includes("Подольск 3") },
  AA: { column: 27, name: "ВОЛЬТМИР", filter: (n) => n.includes("Индустриальная") },
  AI: { column: 35, name: "Ферон Самара", filter: (n) => n.includes("г.Самара") },
  AJ: { column: 36, name: "Ферон Внуково", filter: (n) => n.includes("Внуково") }
};
```

### Фаза 2: FBS склады (AB, AC)

**Файл:** `WB Склады FBS.gs`

**Логика:**
1. GET `/api/v3/warehouses` - получить список складов
2. Найти нужные склады по названию
3. GET `/api/v3/stocks/{warehouseId}` - получить остатки
4. Записать в соответствующие колонки

**Склады:**
```javascript
const supplierWarehouses = {
  AB: { column: 28, name: "ФЕРОН ФБС", search: "ФЕРОН ФБС" },
  AC: { column: 29, name: "ЭТМ САМАРА", search: "ЭТМ САМАРА" }
};
```

---

## 📊 Пример агрегации для 22068-1

### Исходные данные (statistics-api):

| warehouseId | warehouseName | supplierArticle | quantity |
|-------------|---------------|-----------------|----------|
| 1449484 | Коледино | 22068-1 | 10 |
| 123496 | Москва (Подольск 3) | 22068-1 | 20 |
| 84321 | ул. Индустриальная... | 22068-1 | 5 |
| 84390 | Самарская область... | 22068-1 | 8 |
| 3027 | г. Москва, Внуково... | 22068-1 | 12 |

### Результат в таблице:

| Колонка | Буква | Склад | Значение | Логика |
|---------|-------|-------|----------|--------|
| O | 15 | Все FBO | 55 | Сумма всех warehouseId |
| Z | 26 | ФЕРОН МОСКВА | 20 | filter: "Подольск 3" |
| AA | 27 | ВОЛЬТМИР | 5 | filter: "Индустриальная" |
| AI | 35 | Ферон Самара | 8 | filter: "г.Самара" |
| AJ | 36 | Ферон Внуково | 12 | filter: "Внуково" |

---

## 🧪 Тестовые скрипты

### test_warehouse_filter.js
```bash
cd test
node test_warehouse_filter.js
```

Проверяет:
1. Фильтрацию по warehouseName
2. Агрегацию quantity
3. Правильность записываемых значений

---

## 📝 Чек-лист реализации

- [ ] Создать `WB Склады.gs` для Z, AA, AI, AJ
- [ ] Создать `WB Склады FBS.gs` для AB, AC
- [ ] Добавить функции в `Главные функции.gs` → `WbMain()`
- [ ] Протестировать локально с mock данными
- [ ] Загрузить в Apps Script
- [ ] Проверить на реальном API
- [ ] Добавить диагностику для 22068-1

---

## 🔗 Связанные файлы

- [СТРУКТУРА ТАБЛИЦЫ.md](../СТРУКТУРА%20ТАБЛИЦЫ.md) - полная структура колонок
- [Правильные запросы API.md](../Правильные%20запросы%20API.md) - документация API
- [settings.gs](../settings.gs) - API ключи
