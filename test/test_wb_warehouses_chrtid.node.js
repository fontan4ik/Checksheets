/**
 * ЛОКАЛЬНЫЙ ТЕСТ: WB Склады через chrtId (Node.js версия)
 *
 * Запуск: node test_wb_warehouses_chrtid.js
 *
 * Требует设置 API ключа в переменной окружения или в коде
 */

const https = require('https');

// ═══════════════════════════════════════════════════════════════════════════════
// КОНФИГУРАЦИЯ
// ═══════════════════════════════════════════════════════════════════════════════

// Вставьте ваш API ключ здесь
const API_KEY = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg2MDUyMTMxLCJpZCI6IjAxOWMyZDI4LTI0MzMtNzY2MC1iZDU4LTRlNjVhYzMwM2E0YiIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.fZu3j3YZBrIIEAZ6KtuWjTZ7HfPS3sR8Z6vOdmfT5L8hpQmjvVq3zf9Io-2wXTifmda46JEKhCZafyUlTUfpdA';

const wbHeaders = () => {
  return {
    'Authorization': `Bearer ${API_KEY}`
  };
};

// Rate limiting
let lastRequestTime = Date.now();
const RPS = 20; // requests per second

function rateLimitRPS(lastTime, rps) {
  const now = Date.now();
  const elapsed = now - lastTime;
  const minInterval = 1000 / rps;

  if (elapsed < minInterval) {
    const sleepTime = minInterval - elapsed;
    const ms = Math.floor(sleepTime);
    const start = Date.now();
    while (Date.now() - start < ms) {
      // sleep
    }
  }

  return Date.now();
}

// Retry fetch
function retryFetch(url, options, retries = 3) {
  for (let i = 0; i < retries; i++) {
    try {
      lastRequestTime = rateLimitRPS(lastRequestTime, RPS);

      return new Promise((resolve, reject) => {
        const req = https.request(url, options, (res) => {
          let data = '';

          res.on('data', (chunk) => {
            data += chunk;
          });

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

// ═══════════════════════════════════════════════════════════════════════════════
// ОСНОВНАЯ ЛОГИКА
// ═══════════════════════════════════════════════════════════════════════════════

async function testWBWarehousesByChrtId() {
  console.log('╔════════════════════════════════════════════════════════════════════════╗');
  console.log('║   ЛОКАЛЬНЫЙ ТЕСТ: FBS склады через chrtId (Node.js)                         ║');
  console.log('╚════════════════════════════════════════════════════════════════════════╝');

  // Проверка API ключа
  if (API_KEY === 'YOUR_WB_API_KEY_HERE') {
    console.log('❌ Укажите API ключ!');
    console.log('');
    console.log('Способы запуска:');
    console.log('  1. Переменная окружения:');
    console.log('     export WB_API_KEY="your_key_here"');
    console.log('     node test_wb_warehouses_chrtid.js');
    console.log('');
    console.log('  2. Или отредактируйте файл и вставьте ключ в константу API_KEY');
    return;
  }

  // ═══════════════════════════════════════════════════════════════════════════════
  // ШАГ 1: Получение списка складов
  // ═══════════════════════════════════════════════════════════════════════════════

  console.log('\n=== ШАГ 1: Список складов ===');

  const marketplaceUrl = 'https://marketplace-api.wildberries.ru';

  try {
    const warehousesRes = await retryFetch(
      `${marketplaceUrl}/api/v3/warehouses`,
      {
        method: 'GET',
        headers: wbHeaders()
      }
    );

    if (warehousesRes.getResponseCode() === 200) {
      const warehouses = JSON.parse(warehousesRes.getContentText());
      console.log(`✅ Складов: ${warehouses.length}`);

      warehouses.forEach((wh, i) => {
        const type = wh.isFbs ? 'FBS' : (wh.isDbs ? 'DBS' : '?');
        console.log(`   ${i + 1}. [${type}] "${wh.name}" (ID: ${wh.id})`);
      });

      // Находим целевые склады
      const feron = warehouses.find(wh => wh.name.includes('ФЕРОН') && wh.name.includes('МОСКВА'));
      const volt = warehouses.find(wh => wh.name.includes('Вольт'));

      if (!feron || !volt) {
        console.log('\n❌ Целевые склады не найдены!');
        return;
      }

      console.log(`\n🎯 Целевые склады:`);
      console.log(`   ФЕРОН МОСКВА: "${feron.name}" (ID: ${feron.id})`);
      console.log(`   ВольтМир: "${volt.name}" (ID: ${volt.id})`);

      // ═══════════════════════════════════════════════════════════════════════════════
      // ШАГ 2: Content API - получение карточек
      // ═══════════════════════════════════════════════════════════════════════════════

      console.log('\n=== ШАГ 2: Content API (первые 100 карточек) ===');

      const contentUrl = 'https://content-api.wildberries.ru';
      const payload = JSON.stringify({
        "settings": {
          "sort": { "ascending": true },
          "cursor": { "limit": 100 }
        },
        "filter": {
          "withPhoto": -1
        }
      });

      const contentRes = await retryFetch(
        `${contentUrl}/content/v2/get/cards/list`,
        {
          method: 'POST',
          headers: {
            ...wbHeaders(),
            'Content-Type': 'application/json'
          },
          payload: payload
        }
      );

      if (contentRes.getResponseCode() === 200) {
        const data = JSON.parse(contentRes.getContentText());

        if (data && data.cards && Array.isArray(data.cards)) {
          console.log(`✅ Получено карточек: ${data.cards.length}`);

          // Собираем chrtId
          const nmIdToChrtIds = {};
          const uniqueChrtIds = [];

          data.cards.forEach(card => {
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
          let examplesCount = 0;
          for (const nmId in nmIdToChrtIds) {
            if (examplesCount >= 3) break;
            const info = nmIdToChrtIds[nmId];
            console.log(`   Пример ${examplesCount + 1}: nmId=${nmId}, vendorCode=${info.vendorCode}, chrtId=[${info.chrtIds.slice(0, 2).join(", ")}...]`);
            examplesCount++;
          }

          // ═══════════════════════════════════════════════════════════════════════════════
          // ШАГ 3: Marketplace API - остатки
          // ═══════════════════════════════════════════════════════════════════════════════

          console.log('\n=== ШАГ 3: Marketplace API - остатки ===');

          const checkWarehouse = async (warehouse, name) => {
            console.log(`\n[${name}]`);

            const stocksPayload = JSON.stringify({
              chrtIds: uniqueChrtIds.slice(0, 100) // первые 100 для теста
            });

            const res = await retryFetch(
              `${marketplaceUrl}/api/v3/stocks/${warehouse.id}`,
              {
                method: 'POST',
                headers: {
                  ...wbHeaders(),
                  'Content-Type': 'application/json'
                },
                payload: stocksPayload
              }
            );

            if (res.getResponseCode() === 200) {
              const data = JSON.parse(res.getContentText());

              if (data.stocks && Array.isArray(data.stocks)) {
                const withStock = data.stocks.filter(s => s.amount > 0);
                console.log(`   ✅ Проверено chrtId: ${uniqueChrtIds.slice(0, 100).length}`);
                console.log(`   ✅ С остатками: ${withStock.length}`);

                if (withStock.length > 0) {
                  console.log(`   📦 Примеры:`);
                  withStock.slice(0, 5).forEach(stock => {
                    console.log(`      chrtId ${stock.chrtId}: ${stock.amount} шт`);
                  });
                }
              } else {
                console.log(`   ⚠️  Нет поля stocks в ответе`);
              }
            } else {
              console.log(`   ❌ Код: ${res.getResponseCode()}`);
            }
          };

          await checkWarehouse(feron, 'ФЕРОН МОСКВА');
          await checkWarehouse(volt, 'ВольтМир');

          // ═══════════════════════════════════════════════════════════════════════════════
          // ИТОГИ
          // ═══════════════════════════════════════════════════════════════════════════════

          console.log('\n=== ИТОГИ ===');
          console.log('✅ Тест успешно завершён!');
          console.log('');
          console.log('💡 Если видите примеры с остатками - логика работает!');
          console.log('💡 Можно обновлять WB Склады.gs для Apps Script');

        } else {
          console.log('⚠️  Неверный формат ответа Content API');
        }
      } else {
        console.log(`❌ Content API код: ${contentRes.getResponseCode()}`);
        console.log(`Response: ${contentRes.getContentText().substring(0, 500)}`);
      }
    } else {
      console.log(`❌ Ошибка получения складов: ${warehousesRes.getResponseCode()}`);
      console.log(`Response: ${warehousesRes.getContentText().substring(0, 500)}`);
    }
  } catch (e) {
    console.log(`❌ Исключение: ${e.message}`);
    console.log(e.stack);
  }

  console.log('\n════════════════════════════════════════════════════════════════════════');
}

// ═════════════════════════════════════════════════════════════════════════════
// ЗАПУСК
// ═══════════════════════════════════════════════════════════════════════════════

testWBWarehousesByChrtId().catch(err => {
  console.error('❌ Ошибка:', err.message);
  process.exit(1);
});
