// ============================================
// ТЕСТ РАЗНЫХ ЭНДПОИНТОВ ETM API
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

async function testEndpoint(name, path, method = 'GET') {
  console.log(`\n=== ТЕСТ: ${name} ===`);
  console.log(`URL: https://${ETM_BASE_URL}${path}`);

  const options = {
    hostname: ETM_BASE_URL,
    path: path,
    method: method,
    headers: {
      'Accept': 'application/json',
      'Content-Type': 'application/json'
    }
  };

  try {
    const result = await httpsRequest(options);
    console.log(`Код: ${result.statusCode}`);

    if (result.statusCode === 200) {
      console.log('✅ УСПЕХ!');
      if (typeof result.data === 'object') {
        console.log(JSON.stringify(result.data, null, 2).substring(0, 500));
      }
      return result.data;
    } else {
      console.log('❌ ОШИБКА');
      console.log(typeof result.data === 'string' ? result.data.substring(0, 200) : JSON.stringify(result.data));
    }
  } catch (e) {
    console.log(`❌ EXCEPTION: ${e.message}`);
  }

  return null;
}

async function main() {
  console.log('╔══════════════════════════════════════════════════════════╗');
  console.log('║      ТЕСТИРОВАНИЕ ЭНДПОИНТОВ ETM API                    ║');
  console.log('╚══════════════════════════════════════════════════════════╝');

  // Шаг 1: Авторизация
  console.log('\n=== ШАГ 1: АВТОРИЗАЦИЯ ===');
  const loginPath = `/api/v1/user/login?log=${encodeURIComponent(ETM_LOGIN)}&pwd=${encodeURIComponent(ETM_PASSWORD)}`;
  const options = {
    hostname: ETM_BASE_URL,
    path: loginPath,
    method: 'POST',
    headers: { 'Accept': 'application/json' }
  };

  try {
    const result = await httpsRequest(options);
    if (result.statusCode === 200 && result.data.data && result.data.data.session) {
      sessionId = result.data.data.session;
      console.log(`✅ Session ID: ${sessionId}`);
    } else {
      console.log('❌ Авторизация не удалась');
      return;
    }
  } catch (e) {
    console.log(`❌ ${e.message}`);
    return;
  }

  // Шаг 2: Тестируем разные эндпоинты для получения остатков
  const storeCode = '102'; // Самара, ул. Гаражная

  const endpoints = [
    {
      name: 'Остатки склада (v1/goodsremains)',
      path: `/api/v1/goodsremains?store=${storeCode}&session-id=${sessionId}`
    },
    {
      name: 'Остатки склада (v2/goodsremains)',
      path: `/api/v2/goodsremains?store=${storeCode}&session-id=${sessionId}`
    },
    {
      name: 'Остатки все (v1/remains)',
      path: `/api/v1/remains?store=${storeCode}&session-id=${sessionId}`
    },
    {
      name: 'Остатки все (v1/stocks)',
      path: `/api/v1/stocks?store=${storeCode}&session-id=${sessionId}`
    },
    {
      name: 'Товары склада (v1/goods)',
      path: `/api/v1/goods?store=${storeCode}&session-id=${sessionId}`
    },
    {
      name: 'Складские остатки (v1/store/remains)',
      path: `/api/v1/store/${storeCode}/remains?session-id=${sessionId}`
    },
    {
      name: 'API Склад (v1/api/store/remains)',
      path: `/api/v1/api/store/remains?store=${storeCode}&session-id=${sessionId}`
    }
  ];

  for (const ep of endpoints) {
    await testEndpoint(ep.name, ep.path);
  }

  console.log('\n╔══════════════════════════════════════════════════════════╗');
  console.log('║      ТЕСТИРОВАНИЕ ЗАВЕРШЕНО                             ║');
  console.log('╚══════════════════════════════════════════════════════════╝');
}

main().catch(console.error);
