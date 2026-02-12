/**
 * ТЕСТ WB WAREHOUSE LIST
 */

const https = require('https');

const WB_TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg1ODgzMjc3LCJpZCI6IjAxOWMyMzE3LWEyZTMtNzQ2NC1iZTY3LTY3ZDNlMGY4YWNlMSIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.XsB0AXxVxUo13JxstFFAtQXxUqE-MjtP02FnX08uyhh3MGUxfFdm5hgVvcHRFOR-aiv1CeDegedqNJ1k5u8wPw';

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
  console.log("║   ТЕСТ WB WAREHOUSE LIST                                            ║");
  console.log("╚════════════════════════════════════════════════════════════════════════╝");

  const headers = { 'Authorization': `Bearer ${WB_TOKEN}` };

  // Попробуем разные warehouse_id
  const warehouseIds = [1449484, 798761, 1434120, 68154, 117501, 6969, 268282, 507, 124];

  for (const whId of warehouseIds) {
    console.log(`\n=== Warehouse ${whId} ===`);

    try {
      const result = await httpsPost('marketplace-api.wildberries.ru', `/api/v3/stocks/${whId}`, headers, {
        skus: ['22068-1', '23348-1', '22067-1']
      });

      if (result.data.stocks && result.data.stocks.length > 0) {
        console.log(`✅ FOUND ${result.data.stocks.length} items!`);
        result.data.stocks.forEach(s => {
          console.log(`   ${s.supplierArticle}: ${s.amount || s.quantity}`);
        });
      } else {
        process.stdout.write('.');
      }
    } catch (e) {
      console.error(`❌ ${e.message}`);
    }
  }

  console.log("\n\n✅ Завершено");
}

test();
