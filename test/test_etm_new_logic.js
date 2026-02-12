// ============================================
// ТЕСТ НОВОЙ ЛОГИКИ ETM API (прайс-лист)
// ============================================

const https = require('https');

const ETM_LOGIN = '160119919fik';
const ETM_PASSWORD = 'Ibs30Rh2';
const ETM_BASE_URL = 'ipro.etm.ru';

// Тестовые артикулы
const TEST_ARTICLES = [
  '13527',
  '83829',
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

async function loadPriceMap(sessionId) {
  console.log('\n=== ЗАГРУЗКА ПРАЙС-ЛИСТА ETM ===');

  const map = {};
  let page = 1;
  const pageSize = 1000;
  let totalLoaded = 0;

  while (true) {
    const path = `/api/v1/goodsprice?session-id=${sessionId}&page=${page}&rows=${pageSize}`;
    const options = {
      hostname: ETM_BASE_URL,
      path: path,
      method: 'GET',
      headers: { 'Accept': 'application/json' }
    };

    try {
      const result = await httpsRequest(options);

      if (result.statusCode !== 200) {
        console.log(`❌ Ошибка загрузки страницы ${page}: ${result.statusCode}`);
        break;
      }

      if (!result.data.data || !result.data.data.rows || result.data.data.rows.length === 0) {
        break;
      }

      result.data.data.rows.forEach(row => {
        const article = String(row.GdsExtArt || "").trim();
        const gdsCode = row.GdsCode;

        if (article && gdsCode) {
          map[article] = gdsCode;
        }
      });

      totalLoaded += result.data.data.rows.length;
      console.log(`Страница ${page}: ${result.data.data.rows.length} товаров (всего: ${totalLoaded})`);

      if (result.data.data.rows.length < pageSize) {
        break;
      }

      page++;

    } catch (e) {
      console.log(`❌ Ошибка: ${e.message}`);
      break;
    }
  }

  console.log(`\n✅ Загружено товаров: ${Object.keys(map).length}`);
  return map;
}

async function getStockByGdsCode(gdsCode, sessionId) {
  const path = `/api/v1/goods/${gdsCode}/remains?type=etm&session-id=${sessionId}`;
  const options = {
    hostname: ETM_BASE_URL,
    path: path,
    method: 'GET',
    headers: { 'Accept': 'application/json' }
  };

  try {
    const result = await httpsRequest(options);

    if (result.statusCode === 200 && result.data.data && result.data.data.InfoStores) {
      const store = result.data.data.InfoStores.find(s =>
        s.StoreCode === 24121 || (s.StoreName && s.StoreName.includes('Стройкерамика'))
      );

      return store ? (store.StoreQuantRem || 0) : 0;
    }

    return 0;
  } catch (e) {
    return 0;
  }
}

async function main() {
  console.log('╔══════════════════════════════════════════════════════════╗');
  console.log('║      ТЕСТ НОВОЙ ЛОГИКИ ETM API                           ║');
  console.log('╚══════════════════════════════════════════════════════════╝');

  sessionId = await login();
  if (!sessionId) {
    console.log('❌ Авторизация не удалась');
    return;
  }
  console.log(`✅ Session ID: ${sessionId}`);

  // Шаг 1: Загрузить прайс-лист
  const priceMap = await loadPriceMap(sessionId);

  if (Object.keys(priceMap).length === 0) {
    console.log('❌ Не удалось загрузить прайс-лист');
    return;
  }

  // Шаг 2: Проверить тестовые артикулы
  console.log('\n=== ПРОВЕРКА АРТИКУЛОВ ===\n');

  for (const article of TEST_ARTICLES) {
    console.log(`Артикул: ${article}`);

    const gdsCode = priceMap[article];

    if (!gdsCode) {
      console.log('   ❌ Не найден в прайсе\n');
      continue;
    }

    console.log(`   GdsCode: ${gdsCode}`);

    const stock = await getStockByGdsCode(gdsCode, sessionId);

    if (stock > 0) {
      console.log(`   ✅ Остаток: ${stock} шт\n`);
    } else {
      console.log(`   ⚠️  Остаток: 0 шт\n`);
    }

    await new Promise(resolve => setTimeout(resolve, 100));
  }

  // Показать несколько примеров из прайса
  console.log('\n=== ПРИМЕРЫ ИЗ ПРАЙС-ЛИСТА ===\n');
  const articles = Object.keys(priceMap).slice(0, 10);
  articles.forEach(article => {
    console.log(`${article} → GdsCode: ${priceMap[article]}`);
  });
}

main().catch(console.error);
