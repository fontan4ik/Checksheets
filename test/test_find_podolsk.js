/**
 * ТЕСТ: Поиск склада "Подольск" и всех складов Москва
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

async function test() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ПОИСК СКЛАДОВ: САМАРА И ПОДОЛЬСК                                   ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  console.log("\n=== ШАГ 1: Получение всех остатков ===");

  try {
    const result = await httpsGet(
      'statistics-api.wildberries.ru',
      '/api/v1/supplier/stocks?dateFrom=2019-06-20',
      headers
    );

    console.log(`Status: ${result.status}`);

    if (!Array.isArray(result.data)) {
      console.log("❌ Ответ не является массивом");
      return;
    }

    const allStocks = result.data;
    console.log(`Всего записей: ${allStocks.length}`);

    // Собираем уникальные warehouseName
    const uniqueWarehouses = {};
    allStocks.forEach(item => {
      const whName = item.warehouseName || "НЕ УКАЗАНО";
      if (!uniqueWarehouses[whName]) {
        uniqueWarehouses[whName] = {
          warehouseId: item.warehouseId,
          count: 0,
          totalQty: 0
        };
      }
      uniqueWarehouses[whName].count++;
      uniqueWarehouses[whName].totalQty += (item.quantity || 0);
    });

    console.log(`\nУникальных складов: ${Object.keys(uniqueWarehouses).length}`);

    console.log("\n=== ШАГ 2: Поиск САМАРА ===");

    const samaraWarehouses = Object.keys(uniqueWarehouses).filter(name =>
      name.toLowerCase().includes("самара") ||
      name.toLowerCase().includes("samara")
    );

    console.log(`Найдено складов с "Самара": ${samaraWarehouses.length}`);

    samaraWarehouses.forEach(name => {
      const data = uniqueWarehouses[name];
      console.log(`   ✓ "${name}"`);
      console.log(`     Записей: ${data.count}`);
      console.log(`     Quantity: ${data.totalQty}`);
    });

    console.log("\n=== ШАГ 3: Поиск ПОДОЛЬСК ===");

    const podolskWarehouses = Object.keys(uniqueWarehouses).filter(name =>
      name.toLowerCase().includes("подольск") ||
      name.toLowerCase().includes("подмос") ||
      name.toLowerCase().includes("коледино") || // Коледино в Подмосковье
      name.toLowerCase().includes("podolsk") ||
      name.toLowerCase().includes("moskov")
    );

    console.log(`Найдено складов с "Подольск/Подмосковье/Коледино": ${podolskWarehouses.length}`);

    podolskWarehouses.forEach(name => {
      const data = uniqueWarehouses[name];
      console.log(`   ✓ "${name}"`);
      console.log(`     Записей: ${data.count}`);
      console.log(`     Quantity: ${data.totalQty}`);
    });

    console.log("\n=== ШАГ 4: Все 93 склада ===");

    const allNames = Object.keys(uniqueWarehouses).sort();
    allNames.forEach((name, i) => {
      const data = uniqueWarehouses[name];
      console.log(`${(i + 1).toString().padStart(2)}. "${name}" (${data.count} записей, qty: ${data.totalQty})`);
    });

  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }
}

test();
