/**
 * ТЕСТ СУММИРОВАНИЯ WB STOCKS
 */

const https = require('https');

const WB_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

const ARTICLE = '22068-1';

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
  console.log("║   СУММИРОВАНИЕ WB STOCKS                                              ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  console.log("\n=== statistics-api v1 ===");

  try {
    const result = await httpsGet('statistics-api.wildberries.ru', '/api/v1/supplier/stocks?dateFrom=2019-06-20', headers);
    console.log(`Status: ${result.status}, array length: ${result.data.length}`);

    // Суммируем по полному артикулу
    const fullMatches = result.data.filter(s => s.supplierArticle === ARTICLE);
    const fullTotal = fullMatches.reduce((sum, s) => sum + (s.quantity || 0), 0);

    console.log(`\n=== Полный артикул "${ARTICLE}" ===`);
    console.log(`Записей: ${fullMatches.length}`);
    console.log(`Общий quantity: ${fullTotal}`);
    if (fullMatches.length > 0 && fullMatches.length <= 5) {
      fullMatches.forEach(s => {
        console.log(`   ${s.warehouseName}: ${s.quantity} (barcode: ${s.barcode})`);
      });
    } else if (fullMatches.length > 5) {
      fullMatches.slice(0, 3).forEach(s => {
        console.log(`   ${s.warehouseName}: ${s.quantity}`);
      });
      console.log(`   ... и еще ${fullMatches.length - 3} записей`);
    }

    // Суммируем по базовому артикулу (без суффикса)
    const baseArticle = ARTICLE.split('-')[0];
    const baseMatches = result.data.filter(s => {
      const art = s.supplierArticle || '';
      return art.split('-')[0] === baseArticle;
    });
    const baseTotal = baseMatches.reduce((sum, s) => sum + (s.quantity || 0), 0);

    console.log(`\n=== Базовый артикул "${baseArticle}" ===`);
    console.log(`Записей: ${baseMatches.length}`);
    console.log(`Общий quantity: ${baseTotal} (ожидается 36 для O, 15)`);

    if (baseMatches.length > 0 && baseMatches.length <= 10) {
      baseMatches.forEach(s => {
        console.log(`   ${s.supplierArticle} @ ${s.warehouseName}: ${s.quantity}`);
      });
    } else if (baseMatches.length > 10) {
      baseMatches.slice(0, 5).forEach(s => {
        console.log(`   ${s.supplierArticle} @ ${s.warehouseName}: ${s.quantity}`);
      });
      console.log(`   ... и еще ${baseMatches.length - 5} записей`);
    }

    // Анализ по складам
    console.log(`\n=== АНАЛИЗ ПО СКЛАДАМ ===`);
    const warehouseMap = {};
    baseMatches.forEach(s => {
      const wh = s.warehouseName || 'Unknown';
      if (!warehouseMap[wh]) {
        warehouseMap[wh] = { count: 0, quantity: 0 };
      }
      warehouseMap[wh].count++;
      warehouseMap[wh].quantity += s.quantity;
    });

    Object.entries(warehouseMap)
      .sort((a, b) => b[1].quantity - a[1].quantity)
      .forEach(([wh, data]) => {
        console.log(`   ${wh}: ${data.quantity} (${data.count} записей)`);
      });

  } catch (e) {
    console.error(`❌ Ошибка: ${e.message}`);
  }
}

test();
