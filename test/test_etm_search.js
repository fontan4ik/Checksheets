// ============================================
// ПОИСК ВАРИАНТОВ АРТИКУЛА В ETM
// ============================================

const https = require('https');

const ETM_LOGIN = '160119919fik';
const ETM_PASSWORD = 'Ibs30Rh2';
const ETM_BASE_URL = 'ipro.etm.ru';

// Артикул 13527 - попробуем разные варианты
const VARIANTS = [
  '13527',           // Оригинал
  '013527',          // С ведущим нулём
  '0013527',         // С двумя ведущими нулями
  '00013527',        // С тремя ведущими нулями
  '272',             // Может это количество?
  '000013527',       // Еще нули
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

async function checkVariant(article, sessionId) {
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
      // Товар найден!
      if (result.data.data && result.data.data.InfoStores) {
        const stroikaStore = result.data.data.InfoStores.find(s =>
          s.StoreCode === 24121 || (s.StoreName && s.StoreName.includes('Стройкерамика'))
        );

        return {
          found: true,
          stock: stroikaStore ? stroikaStore.StoreQuantRem : 0,
          name: result.data.data.gdscode || article
        };
      }
    }

    return { found: false };
  } catch (e) {
    return { found: false, error: e.message };
  }
}

async function main() {
  console.log('╔══════════════════════════════════════════════════════════╗');
  console.log('║      ПОИСК ПРАВИЛЬНОГО КОДА АРТИКУЛА 13527               ║');
  console.log('╚══════════════════════════════════════════════════════════╝\n');

  sessionId = await login();
  if (!sessionId) {
    console.log('❌ Авторизация не удалась');
    return;
  }
  console.log(`✅ Session ID: ${sessionId}\n`);

  console.log('Проверяем варианты кодировки артикула...\n');

  for (const variant of VARIANTS) {
    process.stdout.write(`"${variant}" ... `);
    const result = await checkVariant(variant, sessionId);

    if (result.found) {
      console.log(`✅ НАЙДЕНО! Остаток на Стройкерамике: ${result.stock} шт`);
      console.log(`   Код товара: ${result.name}\n`);
    } else {
      console.log('❌ не найдено');
    }

    await new Promise(resolve => setTimeout(resolve, 50));
  }

  console.log('\n❗ Если ни один вариант не найден, значит:');
  console.log('   1. Артикул не существует в базе ETM');
  console.log('   2. Используется другая кодировка (не цифры)');
  console.log('   3. Это артикул из другой системы (Feron/Ozon/WB)');
}

main().catch(console.error);
