# Feron API Documentation

## Overview

**Base URL:** `https://clientapi.shop.feron.ru`

**API Version:** 1.0.0

**Description:** REST API компании Feron предназначен для получения списка товаров, описания, свойств и остатков товаров в базе Feron, посредством HTTPS-запросов.

---

## Authentication

All API requests require an API key in the header:

```
API-KEY: your-api-key-here
```

---

## Available Endpoints

### 1. Products (Товары)

#### 1.1 Get Products List

**Endpoint:** `POST /v1/products/list`

**Description:** Получает данные списка товаров, с опциональным фильтром по артикулам

**Request Body:**
```json
{
  "filter": ["48546", "38269"]
}
```

**Request Schema:** `ProductsListRequest`
- `filter` (array, optional): Array of product codes (articules)

**Response (200):** Array of `Product` objects

**Example Response:**
```json
[
  {
    "code": "38269",
    "brand": "FERON",
    "model": "AL164",
    "name": "LB-474 (25W) 230V GX70 4000K, для натяжных потолков",
    "printName": "Лампа cветодиодная, (25W) 230V GX70 4000K, LB-474",
    "description": "Светильники трековые на шинопровод GX53, однофазный (ИВО) FERON AL164, 15W, 230V, цвет белый, корпус алюминий, вращение →350°/↓90°, 92*92*55 мм",
    "packing_ratio": 1,
    "packing_unit": "шт",
    "properties": [
      {
        "name": "Мощность, Вт",
        "value": "15"
      },
      {
        "name": "Тип лампы",
        "value": "GX53"
      },
      {
        "name": "Напряжение, Вольт",
        "value": "230"
      },
      {
        "name": "Материал корпуса",
        "value": "алюминий"
      }
    ],
    "images": [
      "https://shop.feron.ru/upload/iblock/6da/8flk2etl4useyou64y6v5n8silb9w2r0.jpg",
      "https://shop.feron.ru/upload/iblock/470/470a8c82a254a8d51c27d2893ecf26b8.jpg",
      "https://shop.feron.ru/upload/iblock/8ad/rlry8bhgxqt708d40qcddm6xcijiaukt.jpg"
    ],
    "files": [
      {
        "type": "certificate",
        "link": "https://feron.ru/postup/certificate/01381 Лампы светодиодные тм Feron, серия LB. Сертификат по 004 и 020_1.pdf"
      },
      {
        "type": "declaration",
        "link": "https://feron.ru/postup/certificate/87137 Лампы светодиодные тм Feron серия LB Декларация по 037_1.jpg"
      },
      {
        "type": "manual",
        "link": "https://feron.ru/instructions/инструкция филаментные лампы.docx"
      }
    ]
  }
]
```

---

#### 1.2 Get Product by Code

**Endpoint:** `GET /v1/products/{code}`

**Description:** Получает данные существующего товара по его артикулу

**Path Parameters:**
- `code` (string, required): Артикул товара
  - Example: `38269`

**Response (200):** `Product` object

**Error Responses:**
- `400`: Bad Request
- `401`: Unauthorized
- `404`: Not found
- `500`: Internal server error

**Example Usage:**
```bash
curl -X GET "https://clientapi.shop.feron.ru/api/v1/products/38269" \
  -H "API-KEY: your-api-key-here"
```

---

### 2. Stocks (Остатки)

#### 2.1 Get Stocks List

**Endpoint:** `POST /v1/stocks/list`

**Description:** Получает остатки списка товаров, с опциональным фильтром по артикулам

**Request Body:**
```json
{
  "filter": ["48546", "38269"]
}
```

**Request Schema:** `StocksListRequest`
- `filter` (array, optional): Array of product codes

**Response (200):** Array of `StockList` objects

**Example Response:**
```json
[
  {
    "code": "38269",
    "stocks": [
      {
        "warehouseId": "fc154c92-924a-4e6f-8a3d-02442c9893b6",
        "warehouse": "moscow",
        "stock": 2500,
        "overLimit": true
      },
      {
        "warehouseId": "another-uuid",
        "warehouse": "novosibirsk",
        "stock": 1200,
        "overLimit": false
      }
    ]
  }
]
```

**Stock Object Fields:**
- `warehouseId` (string): Unique warehouse identifier (UUID)
- `warehouse` (string): Warehouse name (e.g., "moscow", "novosibirsk")
- `stock` (number): Available quantity
- `overLimit` (boolean): If true, actual stock is greater than the `stock` value

---

#### 2.2 Get Stock by Code

**Endpoint:** `GET /v1/stocks/{code}`

**Description:** Получает остатки существующего товара по его артикулу

**Path Parameters:**
- `code` (string, required): Артикул товара
  - Example: `38269`

**Response (200):** `StockList` object

**Example Usage:**
```bash
curl -X GET "https://clientapi.shop.feron.ru/api/v1/stocks/38269" \
  -H "API-KEY: your-api-key-here"
```

---

### 3. Prices (Цены)

#### 3.1 Get Prices List

**Endpoint:** `POST /v1/prices/list`

**Description:** Получает цены списка товаров, с опциональным фильтром по артикулам

**Request Body:**
```json
{
  "filter": ["48546", "38269"]
}
```

**Request Schema:** `PricesListRequest`
- `filter` (array, optional): Array of product codes

**Response (200):** Array of `PriceList` objects

**Example Response:**
```json
[
  {
    "code": "38269",
    "prices": [
      {
        "type": "rrc",
        "price": 1250.42
      },
      {
        "type": "mic",
        "price": 665.4
      }
    ]
  }
]
```

**Price Object Fields:**
- `type` (string): Price type (e.g., "rrc" - recommended retail price, "mic" - minimum price)
- `price` (number): Price value

---

#### 3.2 Get Price by Code

**Endpoint:** `GET /v1/prices/{code}`

**Description:** Получает цены существующего товара по его артикулу

**Path Parameters:**
- `code` (string, required): Артикул товара
  - Example: `38269`

**Response (200):** `PriceList` object

**Example Usage:**
```bash
curl -X GET "https://clientapi.shop.feron.ru/api/v1/prices/38269" \
  -H "API-KEY: your-api-key-here"
```

---

### 4. Reports (Исходящие отчеты)

#### 4.1 Submit Sales Report

**Endpoint:** `POST /v1/reports/sellout`

**Description:** Предназначен для пересылки в компанию Ферон отчетных данных по продажам за указанные периоды

**Request Body:**
```json
{
  "salesData": [
    {
      "regionCode": 77,
      "regionString": "Москва",
      "federalDistrict": "ЦФО",
      "year": 2023,
      "month": 2,
      "productCode": "abc_12345",
      "feronProductCode": "48546",
      "productName": "FERON AL164 светильник трековый под лампу GX53, белый",
      "feronProductName": "AL164 светильник трековый под лампу GX53, белый",
      "revenue": 123456.78,
      "value": 43456.78,
      "quantity": 255
    }
  ]
}
```

**SalesData Object Fields:**
- `regionCode` (number, optional): Region code (e.g., 77 for Moscow)
- `regionString` (string, required): Region name
- `federalDistrict` (string, optional): Federal district (e.g., "ЦФО")
- `year` (number, required): Reporting period year
- `month` (number, required): Reporting period month
- `productCode` (string, required): Product article/code
- `feronProductCode` (string, required): Feron product article
- `productName` (string, required): Product name
- `feronProductName` (string, required): Feron product name
- `revenue` (number, required): Revenue
- `value` (number, optional): Revenue at purchase prices
- `quantity` (number, required): Quantity sold

**Response (200):** `ReportResult` object (empty object)

**Example Usage:**
```bash
curl -X POST "https://clientapi.shop.feron.ru/api/v1/reports/sellout" \
  -H "API-KEY: your-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "salesData": [
      {
        "regionCode": 77,
        "regionString": "Москва",
        "federalDistrict": "ЦФО",
        "year": 2023,
        "month": 2,
        "productCode": "abc_12345",
        "feronProductCode": "48546",
        "productName": "FERON AL164 светильник трековый под лампу GX53, белый",
        "feronProductName": "AL164 светильник трековый под лампу GX53, белый",
        "revenue": 123456.78,
        "value": 43456.78,
        "quantity": 255
      }
    ]
  }'
```

---

## Data Schemas

### Product Object

| Field | Type | Required | Description | Example |
|-------|------|----------|-------------|---------|
| `code` | string | Yes | Артикул товара | "38269" |
| `brand` | string | Yes | Бренд товара | "FERON" |
| `model` | string | Yes | Модель товара | "AL164" |
| `name` | string | Yes | Наименование товара | "LB-474 (25W) 230V GX70 4000K" |
| `printName` | string | Yes | Наименование для документов | "Лампа cветодиодная" |
| `description` | string | Yes | Краткое описание | "Светильники трековые..." |
| `packing_ratio` | number | Yes | Кратность минимальной упаковки | 1 |
| `packing_unit` | string | Yes | Единица измерения | "шт" |
| `properties` | array | Yes | Свойства товара | [{name, value}] |
| `images` | array | Yes | Ссылки на изображения | ["url1", "url2"] |
| `files` | array | Yes | Ссылки на файлы | [{type, link}] |

### ProductProperty Object

| Field | Type | Required | Description | Example |
|-------|------|----------|-------------|---------|
| `name` | string | Yes | Наименование свойства | "Мощность, Вт" |
| `value` | string | Yes | Значение свойства | "15" |

### ProductFile Object

| Field | Type | Required | Description | Example |
|-------|------|----------|-------------|---------|
| `type` | string | Yes | Тип файла | "certificate" |
| `link` | string | Yes | Ссылка на файл | "https://feron.ru/..." |

**Available File Types:**
- `certificate` - Сертификат
- `manual` - Инструкция
- `description` - Описание
- `declaration` - Декларация

### Stock Object

| Field | Type | Required | Description | Example |
|-------|------|----------|-------------|---------|
| `warehouseId` | string | Yes | Идентификатор склада (UUID) | "fc154c92-..." |
| `warehouse` | string | Yes | Наименование склада | "moscow" |
| `stock` | number | Yes | Количество остатков | 2520 |
| `overLimit` | boolean | Yes | Остаток больше указанного | true |

### Price Object

| Field | Type | Required | Description | Example |
|-------|------|----------|-------------|---------|
| `type` | string | Yes | Вид цены | "rrc" |
| `price` | number | Yes | Цена | 1250.42 |

**Known Price Types:**
- `rrc` - Recommended Retail Price (Рекомендуемая розничная цена)
- `mic` - Minimum Price (Минимальная цена)

---

## Error Responses

All error responses follow a consistent format:

### 400 Bad Request

```json
{
  "statusCode": 400,
  "message": ["Bad Request error message"],
  "error": "Bad Request"
}
```

### 401 Unauthorized

```json
{
  "statusCode": 401,
  "message": "Unauthorized"
}
```

### 404 Not Found

```json
{
  "statusCode": 404,
  "message": "Not found error message",
  "error": "Not found"
}
```

### 500 Internal Server Error

```json
{
  "statusCode": 500,
  "message": "Internal server error"
}
```

---

## Usage Examples

### Example 1: Get All Products

```javascript
const response = await fetch('https://clientapi.shop.feron.ru/api/v1/products/list', {
  method: 'POST',
  headers: {
    'API-KEY': 'your-api-key-here',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({})
});

const products = await response.json();
console.log(products);
```

### Example 2: Get Specific Products by Codes

```javascript
const response = await fetch('https://clientapi.shop.feron.ru/api/v1/products/list', {
  method: 'POST',
  headers: {
    'API-KEY': 'your-api-key-here',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    filter: ['38269', '48546']
  })
});

const products = await response.json();
```

### Example 3: Get Stock for Single Product

```javascript
const productCode = '38269';
const response = await fetch(`https://clientapi.shop.feron.ru/api/v1/stocks/${productCode}`, {
  method: 'GET',
  headers: {
    'API-KEY': 'your-api-key-here'
  }
});

const stockData = await response.json();
console.log(`Stock for ${stockData.code}:`, stockData.stocks);
```

### Example 4: Get Prices for Multiple Products

```javascript
const response = await fetch('https://clientapi.shop.feron.ru/api/v1/prices/list', {
  method: 'POST',
  headers: {
    'API-KEY': 'your-api-key-here',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    filter: ['38269', '48546', '12345']
  })
});

const prices = await response.json();
prices.forEach(item => {
  console.log(`Product ${item.code}:`);
  item.prices.forEach(price => {
    console.log(`  ${price.type}: ${price.price}`);
  });
});
```

---

## Integration with Google Apps Script

Based on the project structure, here's how you could integrate Feron API:

```javascript
// In a new file: Feron.gs

const FERON_API_URL = 'https://clientapi.shop.feron.ru/api';
const FERON_API_KEY = 'your-api-key-here'; // Set in settings.gs

function getFeronProducts(productCodes) {
  const payload = productCodes ? { filter: productCodes } : {};

  const response = UrlFetchApp.fetch(FERON_API_URL + '/v1/products/list', {
    method: 'post',
    headers: {
      'API-KEY': FERON_API_KEY,
      'Content-Type': 'application/json'
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });

  const responseCode = response.getResponseCode();
  const responseBody = response.getContentText();

  if (responseCode !== 200) {
    console.error('Error:', responseCode, responseBody);
    return null;
  }

  return JSON.parse(responseBody);
}

function getFeronStocks(productCodes) {
  const payload = productCodes ? { filter: productCodes } : {};

  const response = UrlFetchApp.fetch(FERON_API_URL + '/v1/stocks/list', {
    method: 'post',
    headers: {
      'API-KEY': FERON_API_KEY,
      'Content-Type': 'application/json'
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });

  return JSON.parse(response.getContentText());
}

function getFeronPrices(productCodes) {
  const payload = productCodes ? { filter: productCodes } : {};

  const response = UrlFetchApp.fetch(FERON_API_URL + '/v1/prices/list', {
    method: 'post',
    headers: {
      'API-KEY': FERON_API_KEY,
      'Content-Type': 'application/json'
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });

  return JSON.parse(response.getContentText());
}

// Example: Sync Feron data to Google Sheet
function syncFeronDataToSheet() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('тест');
  const lastRow = sheet.getLastRow();

  // Get all product codes from column A (starting from row 2)
  const productCodes = sheet.getRange(2, 1, lastRow - 1, 1)
    .getValues()
    .flat()
    .filter(code => code !== '');

  // Fetch data from Feron API
  const products = getFeronProducts(productCodes);
  const stocks = getFeronStocks(productCodes);
  const prices = getFeronPrices(productCodes);

  // Process and write to sheet
  // ... implement mapping logic
}
```

---

## Notes

1. **API Key**: You must obtain an API key from Feron to use this API
2. **Rate Limiting**: Check with Feron for any rate limits
3. **overLimit Flag**: When `overLimit: true` in stock data, it means actual stock is greater than the reported number
4. **Product Properties**: Each product may have different properties; the `properties` array is dynamic
5. **File Types**: Products may have various file types (certificates, manuals, descriptions, declarations)

---

## Support

For API key and technical support, contact Feron directly.

---

**Generated:** 2026-02-10
**API Version:** 1.0.0
**OpenAPI Specification:** See `feron_swagger.json` for complete schema
