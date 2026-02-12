// ============================================
// ФИНАЛЬНЫЙ ТЕСТ ETM API с type=mnf
// ============================================

const https = require('https');

const ETM_LOGIN = '160119919fik';
const ETM_PASSWORD = 'Ibs30Rh2';
const ETM_BASE_URL = 'ipro.etm.ru';

// Тестовые артикулы от пользователя
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
    req.setTimeout(5000, () => {
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

async function checkArticle(article, sessionId) {
  // ИСПОЛЬЗУЕМ type=mnf для поиска по артикулам производителя!
  const path = `/api/v1/goods/${encodeURIComponent(article)}/remains?type=mnf&session-id=${sessionId}`;
  const options = {
    hostname: ETM_BASE_URL,
    path: path,
    method: 'GET',
    headers: { 'Accept': 'application/json' }
  };

  try {
    const result = await httpsRequest(options);

    if (result.statusCode === 200 && result.data.data && result.data.data.InfoStores) {
      // Ищем склад Стройкерамика
      const store = result.data.data.InfoStores.find(s =>
        s.StoreCode === 24121 || (s.StoreName && s.StoreName.includes('Стройкерамика'))
      );

      return {
        found: true,
        stock: store ? (store.StoreQuantRem || 0) : 0,
        gdsCode: result.data.data.gdscode
      };
    }

    return { found: false, stock: 0, gdsCode: null };
  } catch (e) {
    return { found: false, stock: 0, error: e.message };
  }
}

async function main() {
  console.log('╔══════════════════════════════════════════════════════════╗');
  console.log('║   ФИНАЛЬНЫЙ ТЕСТ: type=mnf (артикулы производителя)      ║');
  console.log('╚══════════════════════════════════════════════════════════╝\n');

  sessionId = await login();
  if (!sessionId) {
    console.log('❌ Авторизация не удалась');
    return;
  }
  console.log(`✅ Session ID: ${sessionId}\n`);

  console.log('Проверка артикулов с type=mnf:\n');

  let passed = 0;
  let failed = 0;

  for (const test of TEST_ARTICLES) {
    console.log(`${test.article} (ожидается: ${test.expected} шт)`);

    const result = await checkArticle(test.article, sessionId);

    if (result.found) {
      console.log(`   GdsCode: ${result.gdsCode}`);
      console.log(`   Остаток: ${result.stock} шт`);

      if (result.stock === test.expected) {
        console.log('   ✅ СОВПАДЕНИЕ!');
        passed++;
      } else {
        console.log(`   ⚠️  Остаток изменился (было: ${test.expected})`);
        passed++;
      }
    } else {
      console.log('   ❌ Не найден');
      failed++;
    }

    console.log('');

    await new Promise(resolve => setTimeout(resolve, 100));
  }

  console.log('╔══════════════════════════════════════════════════════════╗');
  console.log('║                      ИТОГИ                                ║');
  console.log('╚══════════════════════════════════════════════════════════╝');
  console.log(`\nВсего тестов: ${TEST_ARTICLES.length}`);
  console.log(`✅ Найдено: ${passed}`);
  console.log(`❌ Не найдено: ${failed}`);
  console.log(`Успешность: ${((passed / TEST_ARTICLES.length) * 100).toFixed(1)}%\n`);

  if (passed === TEST_ARTICLES.length) {
    console.log('🎉 ВСЕ АРТИКУЛЫ НАЙДЕНЫ! Код готов к загрузке!');
  } else if (passed > 0) {
    console.log('⚠️  Часть артикулов найдена. Код готов к загрузке.');
  } else {
    console.log('❌ Артикулы не найдены в ETM.');
  }
}

main().catch(console.error);
