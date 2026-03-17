const https = require('https');

// ============================================
// CONFIGURATION (from settings.gs)
// ============================================
const FERON_API_URL = 'https://clientapi.shop.feron.ru';
const FERON_API_KEY = 'MzZjNGMzNzMtYWNiMS00MzNhLTk2NTQtNjc4NjM0ZDIwYzYx';

// ============================================
// MOCKS
// ============================================
const Logger = {
    log: (...args) => console.log(...args)
};

const Utilities = {
    sleep: (ms) => new Promise(resolve => setTimeout(resolve, ms))
};

/**
 * Mock UrlFetchApp.fetch using Node.js https module
 */
const UrlFetchApp = {
    fetch: (url, options = {}) => {
        return new Promise((resolve, reject) => {
            const urlObj = new URL(url);
            const method = (options.method || 'GET').toUpperCase();
            
            const requestOptions = {
                hostname: urlObj.hostname,
                path: urlObj.pathname + urlObj.search,
                method: method,
                headers: {
                    ...options.headers,
                }
            };

            if (options.payload) {
                requestOptions.headers['Content-Length'] = Buffer.byteLength(options.payload);
            }

            const req = https.request(requestOptions, (res) => {
                let data = '';
                res.on('data', (chunk) => data += chunk);
                res.on('end', () => {
                    resolve({
                        getResponseCode: () => res.statusCode,
                        getContentText: () => data,
                        getAllHeaders: () => res.headers
                    });
                });
            });

            req.on('error', (e) => reject(e));
            
            if (options.payload) {
                req.write(options.payload);
            }
            req.end();
        });
    }
};

// ============================================
// RETRY LOGIC (from fetchapp.gs) - Modified to be async
// ============================================
async function retryFetch(url, options, maxRetries = 5) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const response = await UrlFetchApp.fetch(url, options);
      const responseCode = response.getResponseCode();

      if (responseCode >= 200 && responseCode < 500 && responseCode !== 429) {
        return response;
      }

      const responseText = response.getContentText();
      Logger.log(`⚠️ HTTP ${responseCode} для ${url}. Попытка ${attempt}/${maxRetries}`);
      if (responseCode === 429 || responseCode >= 500) {
        Logger.log(`   Ответ сервера: ${responseText.substring(0, 500)}`);
      }

      if (attempt === maxRetries) {
        Logger.log(`🚫 Достигнуто макс. число попыток (${maxRetries}) для: ${url}`);
        return response;
      }

    } catch (e) {
      Logger.log(`❌ Ошибка сети в retryFetch (попытка ${attempt}/${maxRetries}): ${e.toString()}`);
      
      if (attempt === maxRetries) {
        Logger.log(`🚫 Достигнуто макс. число попыток для: ${url}`);
        return null;
      }
    }

    if (attempt < maxRetries) {
      const waitTime = Math.pow(2, attempt) * 1500; 
      Logger.log(`   Пауза ${waitTime/1000}с...`);
      await Utilities.sleep(waitTime);
    }
  }
  return null;
}

// ============================================
// FERON API FUNCTIONS (from Feron API.gs) - Modified to be async
// ============================================

async function fetchFeronStocks(articles) {
  const chunkSize = 1000;
  const chunks = [];

  if (!articles || articles.length === 0) {
    chunks.push([]);
  } else if (articles.length > chunkSize) {
    for (let i = 0; i < articles.length; i += chunkSize) {
      chunks.push(articles.slice(i, i + chunkSize));
    }
    Logger.log(`Разбито ${articles.length} артикулов на ${chunks.length} чанков`);
  } else {
    chunks.push(articles);
  }

  const stockMap = {};

  for (let i = 0; i < chunks.length; i++) {
    const chunk = chunks[i];
    if (chunks.length > 1) {
      Logger.log(`Обработка чанка ${i + 1}/${chunks.length} (${chunk.length} артикулов)...`);
    }

    const chunkStocks = await fetchFeronStocksChunk(chunk);

    if (chunkStocks) {
      Object.assign(stockMap, chunkStocks);
    }

    if (i < chunks.length - 1) {
      await Utilities.sleep(500);
    }
  }

  Logger.log(`✅ Всего получено данных от Feron: ${Object.keys(stockMap).length} товаров`);
  return stockMap;
}

async function fetchFeronStocksChunk(articles) {
  const url = `${FERON_API_URL}/v1/stocks/list`;
  const payload = { filter: articles || [] };

  const options = {
    method: "post",
    headers: {
      "Content-Type": "application/json",
      "API-KEY": FERON_API_KEY
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  try {
    const response = await retryFetch(url, options);
    if (!response) return null;

    const responseCode = response.getResponseCode();
    if (responseCode !== 200) {
      Logger.log(`❌ Ошибка Feron API (${responseCode}): ${response.getContentText().substring(0, 500)}`);
      return null;
    }

    const data = JSON.parse(response.getContentText());
    if (!Array.isArray(data)) return null;

    const stockMap = {};
    data.forEach(item => {
      const code = item.code;
      if (!code || !item.stocks) return;

      stockMap[code] = { samara: 0, vnukovo: 0, novosibirsk: 0 };
      item.stocks.forEach(stock => {
        const warehouse = stock.warehouse;
        const quantity = stock.stock || 0;
        if (warehouse === "samara") stockMap[code].samara = quantity;
        else if (warehouse === "vnukovo") stockMap[code].vnukovo = quantity;
        else if (warehouse === "novosibirsk") stockMap[code].novosibirsk = quantity;
      });
    });
    return stockMap;
  } catch (e) {
    Logger.log(`❌ Ошибка: ${e.message}`);
    return null;
  }
}

async function fetchFeronPrices(articles) {
  const url = `${FERON_API_URL}/v1/prices/list`;
  const payload = { filter: articles || [] };
  const options = {
    method: "post",
    headers: {
      "Content-Type": "application/json",
      "API-KEY": FERON_API_KEY
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  try {
    const response = await retryFetch(url, options);
    if (!response) return null;

    const responseCode = response.getResponseCode();
    if (responseCode !== 200) return null;

    const data = JSON.parse(response.getContentText());
    if (!Array.isArray(data)) return null;

    const priceMap = {};
    data.forEach(item => {
      const code = item.code;
      if (!code || !item.prices) return;
      priceMap[code] = { rrc: null, mic: null };
      item.prices.forEach(p => {
        if (p.type === "rrc") priceMap[code].rrc = p.price;
        else if (p.type === "mic") priceMap[code].mic = p.price;
      });
    });
    return priceMap;
  } catch (e) {
    return null;
  }
}

// ============================================
// RUN TEST
// ============================================
async function runTest() {
  Logger.log("╔════════════════════════════════════════════════════════════════════════╗");
  Logger.log("║   ТЕСТ ПОДКЛЮЧЕНИЯ FERON API (локально)                                ║");
  Logger.log("╚════════════════════════════════════════════════════════════════════════╝");
  Logger.log("");

  Logger.log("1. Тестируем подключение (получение всех остатков)...");
  const stocks = await fetchFeronStocks([]);
  
  if (stocks) {
    const count = Object.keys(stocks).length;
    Logger.log(`✅ Успешно! Всего товаров: ${count}`);
    
    const firstCodes = Object.keys(stocks).slice(0, 3);
    firstCodes.forEach(code => {
      const s = stocks[code];
      Logger.log(`   Артикул ${code}: Самара=${s.samara}, Внуково=${s.vnukovo}, Новосибирск=${s.novosibirsk}`);
    });
  }

  Logger.log("\n2. Тестируем цены для конкретных артикулов (48546, 38269)...");
  const prices = await fetchFeronPrices(["48546", "38269"]);
  if (prices) {
    Object.keys(prices).forEach(code => {
      const p = prices[code];
      Logger.log(`   Артикул ${code}: RRC=${p.rrc || 'нет'}, MIC=${p.mic || 'нет'}`);
    });
  }

  Logger.log("\n✅ Тест завершен!");
}

runTest().catch(err => {
    console.error("CRITICAL ERROR:", err);
});
