// ============================================
// ТЕСТ ETM API (Node.js)
// ============================================

const https = require('https');

// Новые учетные данные
const ETM_LOGIN = '160119919fik';
const ETM_PASSWORD = 'Ibs30Rh2';

// Базовый URL
const ETM_BASE_URL = 'ipro.etm.ru';

/**
 * Выполняем HTTPS запрос
 */
function httpsRequest(options) {
  return new Promise((resolve, reject) => {
    const req = https.request(options, (res) => {
      let data = '';

      res.on('data', (chunk) => {
        data += chunk;
      });

      res.on('end', () => {
        try {
          const jsonData = JSON.parse(data);
          resolve({ statusCode: res.statusCode, data: jsonData });
        } catch (e) {
          resolve({ statusCode: res.statusCode, data: data });
        }
      });
    });

    req.on('error', (e) => {
      reject(e);
    });

    req.end();
  });
}

/**
 * ТЕСТ 1: Авторизация
 */
async function testLogin() {
  console.log('\n=== ТЕСТ 1: АВТОРИЗАЦИЯ ===');

  const path = `/api/v1/user/login?log=${encodeURIComponent(ETM_LOGIN)}&pwd=${encodeURIComponent(ETM_PASSWORD)}`;

  const options = {
    hostname: ETM_BASE_URL,
    path: path,
    method: 'POST',
    headers: {
      'Accept': 'application/json',
      'Content-Type': 'application/json'
    }
  };

  console.log(`URL: https://${ETM_BASE_URL}${path}`);

  try {
    const result = await httpsRequest(options);

    console.log(`\nКод ответа: ${result.statusCode}`);
    console.log('Ответ:', JSON.stringify(result.data, null, 2));

    if (result.statusCode === 200 && result.data.data && result.data.data.session) {
      const sessionId = result.data.data.session;
      console.log(`\n✅ УСПЕХ! Session ID: ${sessionId}`);
      return sessionId;
    } else if (result.data.status && result.data.status.message) {
      console.log(`\n❌ ОШИБКА: ${result.data.status.message}`);
      return null;
    } else {
      console.log('\n❌ ОШИБКА: Неверный формат ответа');
      return null;
    }
  } catch (e) {
    console.log(`\n❌ ОШИБКА: ${e.message}`);
    return null;
  }
}

/**
 * ТЕСТ 2: Получить остатки по конкретному товару
 */
async function testProductRemains(sessionId) {
  console.log('\n=== ТЕСТ 2: ОСТАТКИ ПО ТОВАРУ ===');

  const productId = '9536092';
  const path = `/api/v1/goods/${productId}/remains?type=etm&session-id=${sessionId}`;

  const options = {
    hostname: ETM_BASE_URL,
    path: path,
    method: 'GET',
    headers: {
      'Accept': 'application/json'
    }
  };

  console.log(`URL: https://${ETM_BASE_URL}${path}`);

  try {
    const result = await httpsRequest(options);

    console.log(`\nКод ответа: ${result.statusCode}`);

    if (result.statusCode === 200) {
      console.log('\n✅ УСПЕХ!');
      console.log('Данные:', JSON.stringify(result.data, null, 2));

      // Проверяем наличие складов
      if (result.data.data && result.data.data.InfoStores) {
        console.log(`\n📦 Найдено складов: ${result.data.data.InfoStores.length}`);
        result.data.data.InfoStores.forEach(store => {
          console.log(`   - ${store.StoreName} (код: ${store.StoreCode})`);
        });

        // Ищем склад Самара
        const samara = result.data.data.InfoStores.find(s =>
          s.StoreName && s.StoreName.toLowerCase().includes('самара')
        );

        if (samara) {
          console.log(`\n✅ Найден склад Самара! Код: ${samara.StoreCode}`);
          return samara.StoreCode;
        } else {
          console.log('\n⚠️ Склад Самара не найден');
          return null;
        }
      }
    } else {
      console.log('Ответ:', JSON.stringify(result.data, null, 2));
    }

    return null;
  } catch (e) {
    console.log(`\n❌ ОШИБКА: ${e.message}`);
    return null;
  }
}

/**
 * ТЕСТ 3: Получить все остатки со склада
 */
async function testWarehouseStocks(sessionId, storeCode) {
  console.log('\n=== ТЕСТ 3: ВСЕ ОСТАТКИ СО СКЛАДА ===');

  const path = `/api/v1/goodsremains?store=${storeCode}&session-id=${sessionId}`;

  const options = {
    hostname: ETM_BASE_URL,
    path: path,
    method: 'GET',
    headers: {
      'Accept': 'application/json'
    }
  };

  console.log(`URL: https://${ETM_BASE_URL}${path}`);

  try {
    const result = await httpsRequest(options);

    console.log(`\nКод ответа: ${result.statusCode}`);

    if (result.statusCode === 200) {
      console.log('\n✅ УСПЕХ!');

      if (result.data.data && result.data.data.rows) {
        const rows = result.data.data.rows;
        console.log(`\n📦 Получено товаров: ${rows.length}`);

        // Показать первые 10 товаров
        console.log('\nПервые 10 товаров:');
        rows.slice(0, 10).forEach(row => {
          console.log(`   Артикул: ${row.Article}, Остаток: ${row.RemInfo}`);
        });

        return rows;
      } else {
        console.log('Ответ:', JSON.stringify(result.data, null, 2));
      }
    } else {
      console.log('Ответ:', JSON.stringify(result.data, null, 2));
    }

    return null;
  } catch (e) {
    console.log(`\n❌ ОШИБКА: ${e.message}`);
    return null;
  }
}

/**
 * ГЛАВНАЯ ФУНКЦИЯ
 */
async function main() {
  console.log('╔══════════════════════════════════════════════════════════╗');
  console.log('║         ТЕСТИРОВАНИЕ ETM API                             ║');
  console.log('╚══════════════════════════════════════════════════════════╝');
  console.log(`\nЛогин: ${ETM_LOGIN}`);
  console.log(`Пароль: ${ETM_PASSWORD}`);

  // Шаг 1: Авторизация
  const sessionId = await testLogin();
  if (!sessionId) {
    console.log('\n❌ НЕ УДАЛОСЬ АВТОРИЗОВАТЬСЯ. ПРЕРЫВАНИЕ.');
    return;
  }

  // Шаг 2: Получить остатки по товару и найти склад Самара
  const storeCode = await testProductRemains(sessionId);
  if (!storeCode) {
    console.log('\n⚠️ НЕ УДАЛОСЬ НАЙТИ СКЛАД САМАРА. ПРОБУЕМ ПРОДОЛЖИТЬ...');
  }

  // Шаг 3: Получить все остатки
  if (storeCode) {
    await testWarehouseStocks(sessionId, storeCode);
  }

  console.log('\n╔══════════════════════════════════════════════════════════╗');
  console.log('║         ТЕСТИРОВАНИЕ ЗАВЕРШЕНО                          ║');
  console.log('╚══════════════════════════════════════════════════════════╝');
}

// Запуск
main().catch(console.error);
