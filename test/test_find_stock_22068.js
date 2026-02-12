/**
 * ТЕСТ ВСЕХ СКЛАДОВ ДЛЯ ТОВАРА 22068-1
 */

const https = require('https');

const WB_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

function httpsGet(hostname, path, headers) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: hostname,
      path: path,
      method: 'GET',
      headers: headers
    };
    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          const jsonData = JSON.parse(data);
          resolve({ status: res.statusCode, data: jsonData });
        } catch (e) {
          resolve({ status: res.statusCode, data: data });
        }
      });
    });
    req.on('error', reject);
    req.end();
  });
}

function httpsPost(hostname, path, headers, body) {
  return new Promise((resolve, reject) => {
    const postData = JSON.stringify(body);
    const options = {
      hostname: hostname,
      path: path,
      method: 'POST',
      headers: {
        ...headers,
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(postData)
      }
    };
    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          const jsonData = JSON.parse(data);
          resolve({ status: res.statusCode, data: jsonData });
        } catch (e) {
          resolve({ status: res.statusCode, data: data });
        }
      });
    });
    req.on('error', reject);
    req.write(postData);
    req.end();
  });
}

async function test() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ПОИСК ТОВАРА 22068-1 ПО ВСЕМ СКЛАДАМ WB                             ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  // Сначала получим список всех складов
  console.log("\n=== ПОЛУЧЕНИЕ СПИСКА СКЛАДОВ ===");

  let warehouses = [];
  try {
    const result = await httpsGet('marketplace-api.wildberries.ru', '/api/v3/warehouses', headers);

    if (Array.isArray(result.data)) {
      warehouses = result.data;
      console.log(`Всего складов: ${warehouses.length}`);
    }
  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
    return;
  }

  // Теперь проверим каждый склад
  console.log("\n=== ПОИСК ТОВАРА ПО СКЛАДАМ ===");

  const article = '22068-1';
  let foundAny = false;

  for (const wh of warehouses) {
    try {
      const result = await httpsPost('marketplace-api.wildberries.ru', `/api/v3/stocks/${wh.id}`, headers, {
        skus: [article]
      });

      if (result.data.stocks && result.data.stocks.length > 0) {
        foundAny = true;
        const stock = result.data.stocks[0];
        console.log(`\n✅ ${wh.name} (id=${wh.id})`);
        console.log(`   Amount: ${stock.amount || stock.quantity}`);
        console.log(`   Type: ${wh.cargoType} (${wh.cargoType === 1 ? 'ФБС' : wh.cargoType === 2 ? 'DBS' : 'КГТ'})`);
      }
    } catch (e) {
      // Игнорируем ошибки
    }
  }

  if (!foundAny) {
    console.log("\n❌ Товар не найден ни на одном складе!");
  }

  console.log("\n✅ Завершено");
}

test();
