/**
 * Используем старый проверенный WB API endpoint
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

async function fetchWBOrders() {
  console.log("=== WB Orders API (старый проверенный метод) ===");

  const path = `/api/v1/supplier/orders?dateFrom=2026-01-03`;

  const headers = {
    'Authorization': `Bearer ${WB_TOKEN}`
  };

  const result = await httpsGet('statistics-api.wildberries.ru', path, headers);
  console.log(`Status: ${result.status}`);

  const fs = require('fs');
  fs.writeFileSync('wb_orders_old_api.json', JSON.stringify(result.data, null, 2));
  console.log('✅ Сохранено: wb_orders_old_api.json');

  // Считаем сумму для артикула 22068-1
  if (Array.isArray(result.data)) {
    const articleOrders = result.data.filter(o => o.supplierArticle === '22068-1' && !o.isCancel);
    console.log(`\nЗаказов для 22068-1: ${articleOrders.length}`);

    let totalSum = 0;
    articleOrders.forEach(order => {
      totalSum += (order.priceWithDisc || 0);
    });

    console.log(`Сумма priceWithDisc: ${totalSum}`);
    console.log(`Сумма в рублях (priceWithDisc/100): ${totalSum / 100}`);
  }
}

fetchWBOrders();
