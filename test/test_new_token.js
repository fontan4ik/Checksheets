// ТЕСТ НОВОГО ТОКЕНА SUPPLIERS-API
// Тестовый скрипт для проверки подключения

const https = require('https');

const newToken = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg2MDUyMTMxLCJpZCI6IjAxOWMyZDI4LTI0MzMtNzY2MC1iZDU4LTRlNjVhYzMwM2E0YiIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.fZu3j3YZBrIIEAZ6KtuWjTZ7HfPS3sR8Z6vOdmfT5L8hpQmjvVq3zf9Io-2wXTifmda46JEKhCZafyUlTUfpdA';

console.log("╔════════════════════════════════════════════════════════════════════════╗");
console.log("║   ТЕСТ НОВОГО ТОКЕНА WB API                                          ║");
console.log("╚════════════════════════════════════════════════════════════════════════╝");

// Декодируем JWT чтобы увидеть exp дату
try {
  const parts = newToken.split('.');
  const payload = JSON.parse(Buffer.from(parts[1], 'base64').toString());
  const expDate = new Date(payload.exp * 1000);
  const now = new Date();

  console.log("\n=== ИНФОРМАЦИЯ О ТОКЕНЕ ===");
  console.log(`UID: ${payload.uid}`);
  console.log(`Seller ID: ${payload.oid}`);
  console.log(`Expire: ${expDate.toISOString()}`);
  console.log(`Current: ${now.toISOString()}`);
  console.log(`Valid: ${expDate > now ? '✅' : '❌'}`);
} catch (e) {
  console.log(`❌ Ошибка декодирования: ${e.message}`);
}

// Тестируем API
const hosts = [
  'suppliers-api.wildberries.ru',
  'marketplace-api.wildberries.ru'
];

async function testHost(host) {
  return new Promise((resolve) => {
    const options = {
      hostname: host,
      path: '/api/v3/warehouses',
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${newToken}`,
        'Content-Type': 'application/json'
      }
    };

    console.log(`\n=== ТЕСТ ${host} ===`);
    console.log(`URL: https://${host}/api/v3/warehouses`);

    const req = https.request(options, (res) => {
      let data = '';

      res.on('data', (chunk) => {
        data += chunk;
      });

      res.on('end', () => {
        console.log(`Status: ${res.statusCode}`);

        if (res.statusCode === 200) {
          try {
            const json = JSON.parse(data);
            console.log(`✅ Успешно! Складов: ${json.length}`);

            json.forEach((wh, i) => {
              const type = wh.isFbs ? 'FBS' : (wh.isDbs ? 'DBS' : '?');
              console.log(`   ${(i + 1)}. [${type}] "${wh.name}" (ID: ${wh.id})`);
            });

            // Ищем целевые склады
            const targetZ = json.find(wh => wh.name.includes("ФЕРОН") && wh.name.includes("МОСКВА"));
            const targetAA = json.find(wh => wh.name.includes("ВольтМир") || wh.name.includes("ВОЛЬТМИР"));

            console.log("\n=== ЦЕЛЕВЫЕ СКЛАДЫ ===");
            if (targetZ) {
              console.log(`✅ Z (26): "${targetZ.name}" (ID: ${targetZ.id})`);
            } else {
              console.log(`❌ Z (26): Не найден`);
            }

            if (targetAA) {
              console.log(`✅ AA (27): "${targetAA.name}" (ID: ${targetAA.id})`);
            } else {
              console.log(`❌ AA (27): Не найден`);
            }

            resolve({ success: true, host, warehouses: json });
          } catch (e) {
            console.log(`❌ Ошибка JSON: ${e.message}`);
            console.log(`Response: ${data.substring(0, 500)}`);
            resolve({ success: false, host, error: e.message });
          }
        } else {
          console.log(`❌ Ошибка HTTP ${res.statusCode}`);
          console.log(`Response: ${data.substring(0, 500)}`);
          resolve({ success: false, host, error: `HTTP ${res.statusCode}` });
        }
      });
    });

    req.on('error', (e) => {
      console.log(`❌ Ошибка подключения: ${e.message}`);
      resolve({ success: false, host, error: e.message });
    });

    req.setTimeout(10000, () => {
      req.destroy();
      console.log(`❌ Таймаут (10 сек)`);
      resolve({ success: false, host, error: 'Timeout' });
    });

    req.end();
  });
}

async function main() {
  for (const host of hosts) {
    const result = await testHost(host);
    if (result.success) {
      console.log("\n" + "═".repeat(76));
      console.log(`✅ РАБОТАЮЩИЙ ХОСТ: ${result.host}`);
      console.log("Можно использовать в Apps Script!");
      break;
    }
  }
}

main().catch(console.error);
