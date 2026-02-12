// ============================================
// ТЕСТ: Использовать артикул как GdsCode напрямую
// ============================================

const https = require('https');

const ETM_LOGIN = '160119919fik';
const ETM_PASSWORD = 'Ibs30Rh2';
const ETM_BASE_URL = 'ipro.etm.ru';

// Артикулы для проверки
const TEST_ARTICLES = [
  '13527',
  '83829',
  '1029089',
  '1029096',
  '6139314',  // Известный GdsCode
  '9536092',  // Известный GdsCode
  'PSN21-016-3'
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
  const path = `/api/v1/goods/${encodeURIComponent(article)}/remains?type=etm&session-id=${sessionId}`;
  const options = {
    hostname: ETM_BASE_URL,
    path: path,
    method: 'GET',
    headers: { 'Accept': 'application/json' }
  };

  try {
    const result = await httpsRequest(options);

    if (result.statusCode === 200 && result.data.status && result.data.status.code === 200) {
      if (result.data.data && result.data.data.InfoStores) {
        const store = result.data.data.InfoStores.find(s =>
          s.StoreCode === 24121 || (s.StoreName && s.StoreName.includes('Стройкерамика'))
        );

        return {
          found: true,
          stock: store ? (store.StoreQuantRem || 0) : 0,
          gdsCode: result.data.data.gdscode || article
        };
      }
    }

    return { found: false, stock: 0 };
  } catch (e) {
    return { found: false, stock: 0 };
  }
}

async function main() {
  console.log('╔══════════════════════════════════════════════════════════╗');
  console.log('║   ТЕСТ: Артикул как GdsCode                             ║');
  console.log('╚══════════════════════════════════════════════════════════╝\n');

  sessionId = await login();
  if (!sessionId) {
    console.log('❌ Авторизация не удалась');
    return;
  }
  console.log(`✅ Session ID: ${sessionId}\n`);

  console.log('Проверка артикулов:\n');

  let foundCount = 0;
  let stockCount = 0;

  for (const article of TEST_ARTICLES) {
    process.stdout.write(`${article.padEnd(15)} ... `);

    const result = await checkArticle(article, sessionId);

    if (result.found) {
      foundCount++;
      if (result.stock > 0) {
        stockCount++;
        console.log(`✅ ${result.stock} шт (GdsCode: ${result.gdsCode})`);
      } else {
        console.log(`⚠️  найден, но остаток 0`);
      }
    } else {
      console.log('❌ не найден');
    }

    await new Promise(resolve => setTimeout(resolve, 50));
  }

  console.log(`\nИтоги:`);
  console.log(`  Найдено: ${foundCount}/${TEST_ARTICLES.length}`);
  console.log(`  С остатком: ${stockCount}/${TEST_ARTICLES.length}`);

  if (foundCount > 0) {
    console.log(`\n💡 Некоторые артикулы работают напрямую как GdsCode!`);
    console.log(`   Можно упростить код и не загружать прайс-лист.`);
  } else {
    console.log(`\n❌ Артикулы не работают как GdsCode.`);
    console.log(`   Нужно найти правильный метод для получения мапа.`);
  }
}

main().catch(console.error);
