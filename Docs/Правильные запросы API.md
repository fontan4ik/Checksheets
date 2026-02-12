Данные, которые ты видишь в разделе
Поставки и заказы → Управление остатками (FBS) / marketplace-stocks-management, отдаются через блок методов Stocks FBS:

список твоих FBS‑складов: GET /api/v3/warehouses

остатки по товарам на конкретном FBS‑складе: POST /api/v3/stocks/{warehouseId}

изменение остатков: PUT /api/v3/stocks/{warehouseId}.

Ниже — как это вытащить.

1. Базовый URL и заголовки
Все запросы по остаткам FBS делаются на Marketplace API:

text
https://marketplace-api.wildberries.ru
Обязательный заголовок:

text
Authorization: <твой API-ключ>
Content-Type: application/json
2. Получить список твоих FBS‑складов
Это те же склады, которые ты видишь в интерфейсе управления остатками (названия типа «ФЕРОН МОСКВА», «ВольтМир» и т.п.).

text
GET https://marketplace-api.wildberries.ru/api/v3/warehouses
Authorization: <API-ключ>
Пример ответа (сокращённо):

json
[
  {
    "id": 12345,
    "name": "ФЕРОН МОСКВА",
    "officeId": 678,          // связанный склад WB
    "isFbs": true,
    "isDd": false
  },
  {
    "id": 23456,
    "name": "ВольтМир",
    "officeId": 679,
    "isFbs": true
  }
]
ID из этого ответа (id) — это warehouseId, который дальше подставляется в запросы по остаткам.

3. Получить остатки FBS по конкретному складу
Метод, который в документации и на форумах прямо рекомендуется как «получить остатки товаров на складе продавца»:

text
POST https://marketplace-api.wildberries.ru/api/v3/stocks/{warehouseId}
Authorization: <API-ключ>
Content-Type: application/json
Тело запроса — список баркодов (или SKU), по которым нужны остатки:

json
{
  "skus": [
    "4660123456789",
    "4660987654321"
  ]
}
Пример ответа:

json
[
  {
    "sku": "4660123456789",
    "amount": 15
  },
  {
    "sku": "4660987654321",
    "amount": 0
  }
]
То, что в таблице «Управление остатками» показывается как «Остаток» для конкретного товара и склада, — это поле amount в этом ответе.

Важно: этот метод не отдаёт «все товары сразу», нужно передавать список баркодов/sku пачками (например, по 100–500 штук). Так работает официальное API.

4. Обновить остатки FBS (как ручное редактирование в ЛК)
Когда в интерфейсе ты меняешь цифру в колонке «Остаток» и жмёшь «Сохранить», под капотом дергается PUT /api/v3/stocks/{warehouseId}.

text
PUT https://marketplace-api.wildberries.ru/api/v3/stocks/{warehouseId}
Authorization: <API-ключ>
Content-Type: application/json
Тело:

json
{
  "stocks": [
    {
      "sku": "4660123456789",
      "amount": 20
    },
    {
      "sku": "4660987654321",
      "amount": 5
    }
  ]
}
Так ты программно выставляешь те же числа, которые обычно вбиваешь в marketplace-stocks-management.

