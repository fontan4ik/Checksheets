/**
 * ФИНАЛЬНЫЙ ТЕСТ L (12) - Сумма заказов Мес ОЗОН
 */

const https = require('https');

const OZON_CLIENT_ID = '273849';
const OZON_API_KEY = '4475806e-5701-4f70-9368-69962efae726';

function httpsPost(hostname, path, headers, body) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: hostname,
      path: path,
      method: 'POST',
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
    req.write(JSON.stringify(body));
    req.end();
  });
}

function formatDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

async function test() {
  console.log("╔════════════════════════════════════════════════════════════════════════╗");
  console.log("║   ТЕСТ L (12) - Сумма заказов Мес ОЗОН (2026)                             ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = {
    'Client-Id': OZON_CLIENT_ID,
    'Api-Key': OZON_API_KEY,
    'Content-Type': 'application/json'
  };

  const today = new Date(); // 2026-02-04
  const startOfMonth = new Date(today.getFullYear(), today.getMonth() - 1, 3); // 2026-01-03

  console.log("\n=== ТЕСТ 1: Получение ВСЕХ SKU с данными (с 3 января 2026) ===");
  const body1 = {
    date_from: formatDate(startOfMonth),
    date_to: formatDate(today),
    dimension: ["sku"],
    metrics: ["ordered_units", "revenue"],
    limit: 50,
    offset: 0,
    sort: [
      {
        key: "revenue",
        order: "DESC"
      }
    ]
  };

  console.log(`Период: ${formatDate(startOfMonth)} → ${formatDate(today)}`);

  const result1 = await httpsPost('api-seller.ozon.ru', '/v1/analytics/data', headers, body1);
  console.log(`Status: ${result1.status}`);
  const data1 = result1.data?.result?.data || [];
  console.log(`Записей: ${data1.length}`);

  if (data1.length > 0) {
    console.log("\nТОП-5 SKU по revenue:");
    data1.slice(0, 5).forEach((entry, i) => {
      const sku = entry.dimensions[0]?.id;
      const orderedUnits = entry.metrics[0];
      const revenue = entry.metrics[1];
      console.log(`  [${i+1}] SKU: ${sku}`);
      console.log(`       ordered_units: ${orderedUnits}, revenue: ${revenue} руб.`);
    });
  } else {
    console.log("❌ Нет данных за указанный период");
    console.log("\nВозможно:");
    console.log("- Товары не продавались в этот период");
    console.log("- Период слишком короткий");
  }

  console.log("\n=== ТЕСТ 2: Конкретный SKU 301854987 (22068-1) ===");
  const body2 = {
    date_from: formatDate(startOfMonth),
    date_to: formatDate(today),
    dimension: ["sku"],
    metrics: ["ordered_units", "revenue"],
    filters: [
      {
        key: "sku",
        op: "EQ",
        value: "301854987"
      }
    ],
    limit: 1,
    offset: 0
  };

  const result2 = await httpsPost('api-seller.ozon.ru', '/v1/analytics/data', headers, body2);
  const data2 = result2.data?.result?.data || [];

  if (data2.length > 0) {
    console.log("\n✅ ДАННЫЕ НАЙДЕНЫ:");
    console.log(`   ordered_units: ${data2[0].metrics[0]}`);
    console.log(`   revenue: ${data2[0].metrics[1]} руб.`);
    console.log("\n=> Эти данные должны записываться в:");
    console.log("   I (9)  Уход Мес ОЗОН: " + data2[0].metrics[0]);
    console.log("   L (12) Сумма заказов:  " + data2[0].metrics[1]);
  } else {
    console.log("\n❌ Нет данных для SKU 301854987");
    console.log("\nПопробуем расширенный период...");

    // Расширенный период - 90 дней
    const start90 = new Date(today);
    start90.setDate(today.getDate() - 90);

    const body3 = {
      date_from: formatDate(start90),
      date_to: formatDate(today),
      dimension: ["sku"],
      metrics: ["ordered_units", "revenue"],
      filters: [
        {
          key: "sku",
          op: "EQ",
          value: "301854987"
        }
      ],
      limit: 1,
      offset: 0
    };

    const result3 = await httpsPost('api-seller.ozon.ru', '/v1/analytics/data', headers, body3);
    const data3 = result3.data?.result?.data || [];

    if (data3.length > 0) {
      console.log(`\n✅ Данные за 90 дней:`);
      console.log(`   ordered_units: ${data3[0].metrics[0]}`);
      console.log(`   revenue: ${data3[0].metrics[1]} руб.`);
    } else {
      console.log("\n❌ Нет данных даже за 90 дней");
      console.log("\nВозможно:");
      console.log("- SKU 301854987 не существует");
      console.log("- Товар не продавался");
      console.log("- SKU изменился");
    }
  }

  console.log("\n=== ИТОГ ===");
  if (data1.length > 0) {
    console.log("✅ API Ozon работает, данные получены");
    console.log(`✅ Найдено ${data1.length} SKU с данными`);
  } else {
    console.log("⚠️  За период с 3 января нет данных");
  }
}

test();
