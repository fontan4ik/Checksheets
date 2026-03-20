// ============================================
// API КОНФИГУРАЦИЯ
// ============================================

const ozonHeaders = () => {
  const clientId = '142355';
  const apiKey = 'fe539630-170b-4b48-b222-8ba092907a63';

  return {
    'Content-Type': 'application/json',
    'Client-Id': clientId,
    'Api-Key': apiKey
  }
};

const wbHeaders = () => {
  return {
    Authorization: 'Bearer eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg2MDUyMTMxLCJpZCI6IjAxOWMyZDI4LTI0MzMtNzY2MC1iZDU4LTRlNjVhYzMwM2E0YiIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.fZu3j3YZBrIIEAZ6KtuWjTZ7HfPS3sR8Z6vOdmfT5L8hpQmjvVq3zf9Io-2wXTifmda46JEKhCZafyUlTUfpdA'
  };
};

// WB Analytics API - тот же токен, другой формат
const WB_ANALYTICS_BASE_URL = () => 'https://seller-analytics-api.wildberries.ru';

const wbAnalyticsHeaders = () => {
  return {
    'Authorization': wbHeaders()['Authorization'],
    'Content-Type': 'application/json'
  };
};

// Совместимость с диагностическим скриптом
function OZON_CLIENT_ID() {
  return ozonHeaders()['Client-Id'];
}

function OZON_API_KEY() {
  return ozonHeaders()['Api-Key'];
}

function WB_API_TOKEN() {
  return wbHeaders()['Authorization'].replace('Bearer ', '');
}

// ============================================
// ОСНОВНЫЕ ФУНКЦИИ
// ============================================

const mainSheet = () => SpreadsheetApp.getActiveSpreadsheet().getSheetByName("тест");
const RPS = () => 20; // Ограничение RPS по умолчанию (Ozon до 50 запросов в секунду)
const WB_RPS = () => 2; // RPS для Wildberries

// ============================================
// OZON API URL
// ============================================

const ozonProductsApiURL = () => 'https://api-seller.ozon.ru/v3/product/list';
const ozonProductsInfoApiURL = () => "https://api-seller.ozon.ru/v3/product/info/list";
const ozonPicturesApiURL = () => 'https://api-seller.ozon.ru/v2/product/pictures/info';
const ozonStocksApiURL = () => 'https://api-seller.ozon.ru/v4/product/info/stocks';
const ozonPricesApiURL = () => "https://api-seller.ozon.ru/v5/product/info/prices";
const ozonAnalyticsData = () => "https://api-seller.ozon.ru/v1/analytics/data";
const ozonFBSStocks = () => "https://api-seller.ozon.ru/v1/product/info/stocks-by-warehouse/fbs";
const ozonFBSWarehouseId = () => 1020005000217829;

// ============================================
// WB API URL
// ============================================

// Старые endpoints (оставлены для совместимости)
const wbStocksApiURL = () => "https://statistics-api.wildberries.ru/api/v1/supplier/stocks";
const wbOrdersApiURL = () => "https://statistics-api.wildberries.ru/api/v1/supplier/orders";
const wbPricesApiURL = () => "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter";

// Новые правильные endpoints (Analytics API)
const wbAnalyticsStocksURL = () => "https://seller-analytics-api.wildberries.ru/api/v2/stocks-report/products/products";
const wbSalesFunnelURL = () => "https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products/history";
const wbSalesFunnelProductsURL = () => "https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products";
const wbMarketplaceStocksURL = (warehouseId) => `https://marketplace-api.wildberries.ru/api/v3/stocks/${warehouseId}`;

// ============================================
// FERON API
// ============================================

const feronAPIUrl = () => 'https://clientapi.shop.feron.ru';
const feronAPIKey = () => 'ZjA5MDg3MTAtNjQ5ZS00ODU5LWJjNjktY2NkY2E1ZDdlNjUx';

// ============================================
// ETM API
// ============================================

const etmLogin = () => '160119919fik';
const etmPassword = () => 'Ibs30Rh2';

// ============================================
// RS API (Русский Свет)
// ============================================

const rsLogin = () => 'ntc-es1';
const rsPassword = () => '4XK69YO0';
const rsApiBaseUrl = () => 'https://holy-hall-9741.jilighyt4591667.workers.dev';
