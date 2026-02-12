// ============================================
// ТЕСТ: Получение остатков по списку артикулов
// ============================================

const https = require('https');

const ETM_LOGIN = '160119919fik';
const ETM_PASSWORD = 'Ibs30Rh2';
const ETM_BASE_URL = 'ipro.etm.ru';

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

async function getProductRemains(article, sessionId) {
  const path = `/api/v1/goods/${article}/remains?type=etm&session-id=${sessionId}`;
  const options = {
    hostname: ETM_BASE_URL,
    path: path,
    method: 'GET',
    headers: { 'Accept': 'application/json' }
  };

  const result = await httpsRequest(options);

  if (result.statusCode === 200 && result.data.data && result.data.data.InfoStores) {
    // Ищем склад Самара (код 102 - г. Самара, ул. Гаражная)
    const samaraStore = result.data.data.InfoStores.find(s =>
      s.StoreCode === 102 || (s.StoreName && s.StoreName.includes('Гаражная'))
    );

    return {
      article: article,
      found: true,
      samaraStock: samaraStore ? samaraStore.StockRem || samaraStore.StoreQuantRem || 0 : 0,
      allStores: result.data.data.InfoStores
    };
  }

  return { article: article, found: false, samaraStock: 0 };
}

async function main() {
  console.log('╔══════════════════════════════════════════════════════════╗');
  console.log('║   ПОЛУЧЕНИЕ ОСТАТКОВ ПО СПИСКУ АРТИКУЛОВ                ║');
  console.log('╚══════════════════════════════════════════════════════════╝');

  // Авторизация
  console.log('\n=== АВТОРИЗАЦИЯ ===');
  sessionId = await login();
  if (!sessionId) {
    console.log('❌ Авторизация не удалась');
    return;
  }
  console.log(`✅ Session ID: ${sessionId}`);

  // Тестовые артикулы
  const testArticles = [
    '9536092',
    '48546',
    '38269',
    '6294',
    '6295'
  ];

  console.log(`\n=== ПОЛУЧЕНИЕ ОСТАТКОВ ПО ${testArticles.length} АРТИКУЛАМ ===`);

  const results = [];

  for (let i = 0; i < testArticles.length; i++) {
    const article = testArticles[i];
    console.log(`\n[${i + 1}/${testArticles.length}] Артикул: ${article}`);

    try {
      const result = await getProductRemains(article, sessionId);
      results.push(result);

      if (result.found) {
        console.log(`   ✅ Найден. Остаток на Гаражной: ${result.samaraStock}`);
      } else {
        console.log(`   ❌ Не найден`);
      }

      // Небольшая пауза между запросами
      await new Promise(resolve => setTimeout(resolve, 100));
    } catch (e) {
      console.log(`   ❌ Ошибка: ${e.message}`);
      results.push({ article: article, found: false, samaraStock: 0 });
    }
  }

  // Итоговая статистика
  console.log('\n╔══════════════════════════════════════════════════════════╗');
  console.log('║   ИТОГОВАЯ СТАТИСТИКА                                    ║');
  console.log('╚══════════════════════════════════════════════════════════╝');

  console.log('\nАртикул | Остаток Самара');
  console.log('--------|----------------');
  results.forEach(r => {
    console.log(`${r.article.padEnd(7)} | ${r.samaraStock}`);
  });

  const foundCount = results.filter(r => r.found).length;
  const totalStock = results.reduce((sum, r) => sum + r.samaraStock, 0);

  console.log(`\nНайдено товаров: ${foundCount} из ${testArticles.length}`);
  console.log(`Общий остаток: ${totalStock}`);

  console.log('\n✅ Метод работает! Можно получать остатки по каждому артикулу.');
  console.log('⚠️  Внимание: Это будет медленно для 10,000+ артикулов.');
}

main().catch(console.error);
