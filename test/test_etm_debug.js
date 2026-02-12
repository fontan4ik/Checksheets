// ============================================
// ОТЛАДКА ETM API - ПОЛНЫЙ ОТВЕТ
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

async function debugArticle(article, sessionId) {
  const path = `/api/v1/goods/${encodeURIComponent(article)}/remains?type=etm&session-id=${sessionId}`;
  const options = {
    hostname: ETM_BASE_URL,
    path: path,
    method: 'GET',
    headers: { 'Accept': 'application/json' }
  };

  console.log(`\n========================================`);
  console.log(`АРТИКУЛ: ${article}`);
  console.log(`URL: https://${ETM_BASE_URL}${path}`);
  console.log(`========================================\n`);

  const result = await httpsRequest(options);

  console.log(`Код ответа: ${result.statusCode}`);
  console.log(`\nПОЛНЫЙ ОТВЕТ:`);
  console.log(JSON.stringify(result.data, null, 2));
}

async function main() {
  console.log('╔══════════════════════════════════════════════════════════╗');
  console.log('║           ОТЛАДКА ETM API                              ║');
  console.log('╚══════════════════════════════════════════════════════════╝');

  sessionId = await login();
  if (!sessionId) {
    console.log('❌ Авторизация не удалась');
    return;
  }
  console.log(`✅ Session ID: ${sessionId}`);

  // Проверим несколько артикулов
  await debugArticle('13527', sessionId);
  await debugArticle('9536092', sessionId);  // Тот, который раньше работал
}

main().catch(console.error);
