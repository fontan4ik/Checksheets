// ============================================
// ВАЛИДАЦИОННЫЙ ТЕСТ ETM API
// ============================================

const https = require('https');

const ETM_LOGIN = '160119919fik';
const ETM_PASSWORD = 'Ibs30Rh2';
const ETM_BASE_URL = 'ipro.etm.ru';

// Тестовые артикулы с ожидаемыми остатками
const TEST_ARTICLES = [
  { article: '13527', expected: 272 },
  { article: '83829', expected: 5 },
  { article: '1029089', expected: 207 },
  { article: '1029096', expected: 278 },
  { article: 'lle-t80-8-230-40', expected: 2241 },
  { article: 'mrd10-16', expected: 2323 },
  { article: '23222', expected: 530 },
  { article: '024108(2)', expected: 40 }
];

let sessionId = '';

function httpsRequest(options) {
  return new Promise((resolve, reject) => {
    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          resolve({ statusCode: res.statusCode, data: JSON.parse(data) });
        } catch {
          resolve({ statusCode: res.statusCode, data: data });
        }
      });
    });
    req.on('error', reject);
    req.setTimeout(10000, () => {
      req.destroy();
      reject(new Error('Timeout'));
    });
    req.end();
  });
}

async function login() {
  const path = `/api/v1/user/login?log=${encodeURIComponent(ETM_LOGIN)}&pwd=${encodeURIComponent(ETM_PASSWORD)}`;
  const options = {
    hostname: ETM_BASE_URL,
    path: path,
    method: 'POST',
    headers: { 'Accept': 'application/json' }
  };

  const result = await httpsRequest(options);
  if (result.statusCode === 200 && result.data.data && result.data.data.session) {
    return result.data.data.session;
  }
  return null;
}

async function getArticleStock(article, sessionId) {
  const path = `/api/v1/goods/${encodeURIComponent(article)}/remains?type=etm&session-id=${sessionId}`;
  const options = {
    hostname: ETM_BASE_URL,
    path: path,
    method: 'GET',
    headers: { 'Accept': 'application/json' }
  };

  try {
    const result = await httpsRequest(options);

    if (result.statusCode === 200 && result.data.data && result.data.data.InfoStores) {
      // Ищем склад Стройкерамика (код 24121)
      const samaraStore = result.data.data.InfoStores.find(s =>
        s.StoreCode === 24121 || (s.StoreName && s.StoreName.includes('Стройкерамика'))
      );

      return {
        found: true,
        stock: samaraStore ? (samaraStore.StoreQuantRem || samaraStore.StockRem || 0) : 0,
        allStores: result.data.data.InfoStores
      };
    }

    return { found: false, stock: 0, allStores: [] };
  } catch (e) {
    return { found: false, stock: 0, error: e.message };
  }
}

async function main() {
  console.log('╔════════════════════════════════════════════════════════════════╗');
  console.log('║           ВАЛИДАЦИОННЫЙ ТЕСТ ETM API                            ║');
  console.log('╚════════════════════════════════════════════════════════════════╝\n');

  // Авторизация
  console.log('=== АВТОРИЗАЦИЯ ===');
  sessionId = await login();
  if (!sessionId) {
    console.log('❌ Авторизация не удалась');
    return;
  }
  console.log(`✅ Session ID: ${sessionId}\n`);

  // Тестируем каждый артикул
  console.log('=== ПРОВЕРКА АРТИКУЛОВ ===\n');

  let passed = 0;
  let failed = 0;

  for (const test of TEST_ARTICLES) {
    console.log(`Артикул: ${test.article}`);
    console.log(`Ожидается: ${test.expected} шт`);

    const result = await getArticleStock(test.article, sessionId);

    if (result.found) {
      console.log(`Получено: ${result.stock} шт`);

      // Проверяем совпадение
      if (result.stock === test.expected) {
        console.log('✅ СОВПАДЕНИЕ!');
        passed++;
      } else {
        console.log(`❌ НЕСОВПАДЕНИЕ! (разница: ${result.stock - test.expected})`);
        failed++;
      }

      // Показываем все склады если есть
      if (result.allStores && result.allStores.length > 0) {
        console.log('Все склады:');
        result.allStores.forEach(store => {
          if (store.StoreQuantRem > 0) {
            console.log(`   - ${store.StoreName}: ${store.StoreQuantRem} шт (код: ${store.StoreCode})`);
          }
        });
      }
    } else {
      console.log(`❌ НЕ НАЙДЕН`);
      failed++;
    }

    console.log('');

    // Небольшая пауза
    await new Promise(resolve => setTimeout(resolve, 100));
  }

  // Итоги
  console.log('╔════════════════════════════════════════════════════════════════╗');
  console.log('║                      ИТОГИ                                     ║');
  console.log('╚════════════════════════════════════════════════════════════════╝');
  console.log(`\nВсего тестов: ${TEST_ARTICLES.length}`);
  console.log(`✅ Прошло: ${passed}`);
  console.log(`❌ Не прошло: ${failed}`);
  console.log(`Успешность: ${((passed / TEST_ARTICLES.length) * 100).toFixed(1)}%\n`);

  if (passed === TEST_ARTICLES.length) {
    console.log('🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ! API РАБОТАЕТ ВЕРНО!');
  } else if (passed > 0) {
    console.log('⚠️  ЧАСТИЧНОЕ СОВПАДЕНИЕ. Проверьте артикулы с неудачами.');
  } else {
    console.log('❌ НИ ОДИН ТЕСТ НЕ ПРОЙДЕН. Возможные проблемы:');
    console.log('   1. Неверный склад (код 102 - Гаражная)');
    console.log('   2. Остатки изменились с момента теста');
    console.log('   3. Неверное поле в ответе API');
  }
}

main().catch(console.error);
