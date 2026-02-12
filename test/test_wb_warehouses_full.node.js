/**
 * РАСШИРЕННЫЙ ТЕСТ: WB Склады через chrtId (с пагинацией)
 *
 * Загружает ВСЕ карточки через Content API с пагинацией
 * Ищет товары с остатками на FBS складах
 */

const https = require('https');

const API_KEY = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg2MDUyMTMxLCJpZCI6IjAxOWMyZDI4LTI0MzMtNzY2MC1iZDU4LTRlNjVhYzMwM2E0YiIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.fZu3j3YZBrIIEAZ6KtuWjTZ7HfPS3sR8Z6vOdmfT5L8hpQmjvVq3zf9Io-2wXTifmda46JEKhCZafyUlTUfpdA';

const wbHeaders = () => ({
  'Authorization': `Bearer ${API_KEY}`
});

let lastRequestTime = Date.now();
const RPS = 20;

function rateLimitRPS(lastTime, rps) {
  const now = Date.now();
  const elapsed = now - lastTime;
  const minInterval = 1000 / rps;

  if (elapsed < minInterval) {
    const sleepTime = minInterval - elapsed;
    const ms = Math.floor(sleepTime);
    const start = Date.now();
    while (Date.now() - start < ms) {}
  }

  return Date.now();
}

async function retryFetch(url, options, retries = 3) {
  for (let i = 0; i < retries; i++) {
    try {
      lastRequestTime = rateLimitRPS(lastRequestTime, RPS);

      return new Promise((resolve, reject) => {
        const req = https.request(url, options, (res) => {
          let data = '';
          res.on('data', (chunk) => { data += chunk; });
          res.on('end', () => {
            resolve({
              getResponseCode: () => res.statusCode,
              getContentText: () => data
            });
          });
        });
        req.on('error', reject);
        req.write(options.payload || '');
        req.end();
      });
    } catch (e) {
      if (i === retries - 1) throw e;
    }
  }
}

async function testFull() {
  console.log('╔════════════════════════════════════════════════════════════════════════╗');
  console.log('║   РАСШИРЕННЫЙ ТЕСТ: ВСЕ карточки с пагинацией                          ║');
  console.log('╚════════════════════════════════════════════════════════════════════════╝');

  const marketplaceUrl = 'https://marketplace-api.wildberries.ru';
  const contentUrl = 'https://content-api.wildberries.ru';

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 1: Список складов
  // ═════════════════════════════════════════════════════════════════════════════

  console.log('\n=== ШАГ 1: Список складов ===');

  const warehousesRes = await retryFetch(
    `${marketplaceUrl}/api/v3/warehouses`,
    { method: 'GET', headers: wbHeaders() }
  );

  if (warehousesRes.getResponseCode() !== 200) {
    console.log('❌ Ошибка получения складов');
    return;
  }

  const warehouses = JSON.parse(warehousesRes.getContentText());
  console.log(`✅ Складов: ${warehouses.length}`);

  const feron = warehouses.find(wh => wh.name.includes('ФЕРОН') && wh.name.includes('МОСКВА'));
  const volt = warehouses.find(wh => wh.name.includes('Вольт'));

  if (!feron || !volt) {
    console.log('❌ Целевые склады не найдены');
    return;
  }

  console.log(`\n🎯 Целевые склады:`);
  console.log(`   ФЕРОН МОСКВА: ID ${feron.id}`);
  console.log(`   ВольтМир: ID ${volt.id}`);

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 2: Content API - ВСЕ карточки с пагинацией
  // ═══════════════════════════════════════════════════════════════════════════════

  console.log('\n=== ШАГ 2: Content API - ВСЕ карточки ===');
  console.log('Загружаем все карточки с пагинацией...');

  let allCards = [];
  let cursorData = null;
  let totalCards = 0;
  let iteration = 0;
  const maxCards = 10000; // защита от бесконечного цикла
  const limit = 100; // WB API max limit is 100

  while (true) {
    iteration++;

    const payload = {
      "settings": {
        "sort": { "ascending": true },
        "cursor": { "limit": limit }
      },
      "filter": {
        "withPhoto": -1
      }
    };

    if (cursorData) {
      // Merge cursor data with limit - preserve limit from original cursor
      payload.settings.cursor = {
        ...cursorData,
        limit: limit
      };
    }

    const options = {
      method: 'POST',
      headers: {
        ...wbHeaders(),
        'Content-Type': 'application/json'
      },
      payload: JSON.stringify(payload)
    };

    try {
      if (iteration === 2) {
        console.log(`   📤 Request payload (2nd iteration): ${JSON.stringify(payload)}`);
      }
      const res = await retryFetch(`${contentUrl}/content/v2/get/cards/list`, options);
      const code = res.getResponseCode();

      if (code === 200) {
        const data = JSON.parse(res.getContentText());

        if (data && data.cards && Array.isArray(data.cards)) {
          const cardCount = data.cards.length;
          totalCards += cardCount;

          if (iteration === 1 || totalCards % 500 === 0 || totalCards % 100 === 0) {
            console.log(`   Загружено: ${cardCount} карточек (всего: ${totalCards})`);
          }

          allCards.push(...data.cards);

          // Пагинация
          if (data.cursor && data.cards.length > 0 && totalCards < maxCards) {
            cursorData = data.cursor;
          } else {
            console.log(`   ✅ Загружено ВСЕ карточек: ${totalCards}`);
            break;
          }
        } else {
          console.log('   ⚠️  Неверный формат ответа');
          break;
        }
      } else {
        console.log(`   ❌ Content API код: ${code}`);
        console.log(`   Response: ${res.getContentText().substring(0, 500)}`);
        break;
      }
    } catch (e) {
      console.log(`   ❌ Ошибка: ${e.message}`);
      break;
    }
  }

  console.log(`\n📊 Всего загружено карточек: ${allCards.length}`);

  if (allCards.length === 0) {
    console.log('❌ Нет карточек для анализа');
    return;
  }

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 3: Извлекаем chrtId
  // ═════════════════════════════════════════════════════════════════════════════

  console.log('\n=== ШАГ 3: Извлечение chrtId ===');

  const nmIdToChrtIds = {};
  const uniqueChrtIds = [];

  allCards.forEach(card => {
    const nmId = card.nmID || card.nmId;
    const vendorCode = card.vendorCode;

    if (nmId && card.sizes && card.sizes.length > 0) {
      nmIdToChrtIds[nmId] = {
        vendorCode: vendorCode,
        chrtIds: []
      };

      card.sizes.forEach(size => {
        if (size.chrtID) {
          nmIdToChrtIds[nmId].chrtIds.push(size.chrtID);
          uniqueChrtIds.push(size.chrtID);
        }
      });
    }
  });

  console.log(`✅ Уникальных nmId: ${Object.keys(nmIdToChrtIds).length}`);
  console.log(`✅ Уникальных chrtId: ${uniqueChrtIds.length}`);

  // Показываем примеры
  let count = 0;
  for (const nmId in nmIdToChrtIds) {
    if (count >= 5) break;
    const info = nmIdToChrtIds[nmId];
    console.log(`   nmId ${nmId}: "${info.vendorCode}", chrtId: ${info.chrtIds.length}`);
    count++;
  }

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 4: Marketplace API - остатки по складам
  // ═══════════════════════════════════════════════════════════════════════════════

  console.log('\n=== ШАГ 4: Marketplace API - остатки ===');

  const checkWarehouse = async (warehouse, name) => {
    console.log(`\n[${name}]`);

    const chunkSize = 999;
    let totalChecked = 0;
    const stockMap = {};

    for (let i = 0; i < uniqueChrtIds.length; i += chunkSize) {
      const chunk = uniqueChrtIds.slice(i, i + chunkSize);
      const chrtIdsNum = chunk.map(id => parseInt(id));

      const payload = JSON.stringify({ chrtIds: chrtIdsNum });

      const res = await retryFetch(
        `${marketplaceUrl}/api/v3/stocks/${warehouse.id}`,
        {
          method: 'POST',
          headers: {
            ...wbHeaders(),
            'Content-Type': 'application/json'
          },
          payload: payload
        }
      );

      if (res.getResponseCode() === 200) {
        const data = JSON.parse(res.getContentText());

        if (data.stocks && Array.isArray(data.stocks)) {
          data.stocks.forEach(stock => {
            if (stock.amount > 0) {
              stockMap[stock.chrtId] = stock.amount;
            }
          });
        }

        totalChecked += chunk.length;
      } else {
        console.log(`   ❌ Код: ${res.getResponseCode()}`);
        return;
      }
    }

    const withStock = Object.keys(stockMap).length;
    const totalStock = Object.values(stockMap).reduce((sum, qty) => sum + qty, 0);

    console.log(`   ✅ Проверено chrtId: ${totalChecked}`);
    console.log(`   ✅ С остатками: ${withStock} товаров, всего ${totalStock} шт`);

    // Показываем примеры
    let examples = 0;
    for (const chrtId in stockMap) {
      if (examples >= 5) break;
      const qty = stockMap[chrtId];

      // Находим nmId для этого chrtId
      for (const nmId in nmIdToChrtIds) {
        const info = nmIdToChrtIds[nmId];
        if (info.chrtIds.includes(parseInt(chrtId))) {
          console.log(`   📦 nmId ${nmId} (${info.vendorCode}): ${qty} шт (chrtId ${chrtId})`);
          examples++;
          break;
        }
      }
    }

    return stockMap;
  };

  const feronStocks = await checkWarehouse(feron, 'ФЕРОН МОСКВА');
  const voltStocks = await checkWarehouse(volt, 'ВольтМир');

  // ═══════════════════════════════════════════════════════════════════════════════
  // ИТОГИ
  // ═══════════════════════════════════════════════════════════════════════════════

  console.log('\n=== ИТОГИ ===');
  console.log(`📊 Статистика:`);
  console.log(`   Всего карточек: ${allCards.length}`);
  console.log(`   Уникальных nmId: ${Object.keys(nmIdToChrtIds).length}`);
  console.log(`   Уникальных chrtId: ${uniqueChrtIds.length}`);
  console.log(``);
  console.log(`   ФЕРОН МОСКВА: ${Object.keys(feronStocks).length} товаров с остатками`);
  console.log(`   ВольтМир: ${Object.keys(voltStocks).length} товаров с остатками`);

  const totalFeron = Object.values(feronStocks).reduce((sum, qty) => sum + qty, 0);
  const totalVolt = Object.values(voltStocks).reduce((sum, qty) => sum + qty, 0);

  console.log(`   Всего остатков ФЕРОН: ${totalFeron} шт`);
  console.log(`   Всего остатков ВольтМир: ${totalVolt} шт`);

  if (Object.keys(feronStocks).length > 0 || Object.keys(voltStocks).length > 0) {
    console.log(`\n✅ УСПЕХ! Найдены товары с остатками на FBS складах!`);
    console.log(`\n💡 Логика работает через chrtId!`);
    console.log(`💡 Можно обновлять WB Склады.gs!`);
  } else {
    console.log(`\n⚠️  Нет остатков на FBS складах`);
    console.log(`\nВозможно:`);
    console.log(`   1. Товары только на FBO складах WB`);
    console.log(`   2. Нет товаров на этих FBS складах`);
    console.log(`   3. NM ID в таблице не соответствуют этим складам`);
  }

  console.log('\n════════════════════════════════════════════════════════════════════════\n');
}

testFull().catch(err => {
  console.error('❌ Ошибка:', err.message);
  console.error(err.stack);
  process.exit(1);
});
