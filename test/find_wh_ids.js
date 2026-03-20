const https = require('https');

const clientId = '142355';
const apiKey = 'fe539630-170b-4b48-b222-8ba092907a63';
const wbToken = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg2MDUyMTMxLCJpZCI6IjAxOWMyZDI4LTI0MzMtNzY2MC1iZDU4LTRlNjVhYzMwM2E0YiIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.fZu3j3YZBrIIEAZ6KtuWjTZ7HfPS3sR8Z6vOdmfT5L8hpQmjvVq3zf9Io-2wXTifmda46JEKhCZafyUlTUfpdA';

function request(options, body) {
    return new Promise((resolve) => {
        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => data += chunk);
            res.on('end', () => {
                try {
                    resolve(JSON.parse(data));
                } catch (e) {
                    resolve({ error: 'JSON parse error' });
                }
            });
        });
        req.on('error', (e) => resolve({ error: e.message }));
        if (body) req.write(JSON.stringify(body));
        req.end();
    });
}

async function main() {
    console.log('Fetching Ozon warehouses...');
    const ozonOptions = {
        hostname: 'api-seller.ozon.ru',
        path: '/v1/warehouse/list',
        method: 'POST',
        headers: {
            'Client-Id': clientId,
            'Api-Key': apiKey,
            'Content-Type': 'application/json'
        }
    };
    const ozon = await request(ozonOptions, { limit: 200 });
    
    if (ozon.result) {
        const samara = ozon.result.find(wh => 
            wh.name.includes('1C') || wh.name.includes('трансляция') || wh.name.includes('Самара')
        );
        if (samara) {
            console.log(`FOUND OZON SAMARA: ${samara.name} (ID: ${samara.warehouse_id})`);
        } else {
            console.log('OZON SAMARA NOT FOUND. List:');
            ozon.result.forEach(wh => console.log(`  - ${wh.name} (ID: ${wh.warehouse_id})`));
        }
    } else {
        console.log('Ozon error:', ozon);
    }

    console.log('\nFetching WB warehouses...');
    const wbOptions = {
        hostname: 'marketplace-api.wildberries.ru',
        path: '/api/v3/warehouses',
        method: 'GET',
        headers: {
            'Authorization': 'Bearer ' + wbToken
        }
    };
    const wb = await request(wbOptions);
    
    if (Array.isArray(wb)) {
        const volt = wb.find(wh => wh.name.includes('Вольт'));
        if (volt) {
            console.log(`FOUND WB VOLTMIR: ${volt.name} (ID: ${volt.id})`);
        } else {
            console.log('WB VOLTMIR NOT FOUND. List:');
            wb.forEach(wh => console.log(`  - ${wh.name} (ID: ${wh.id})`));
        }
    } else {
        console.log('WB error:', wb);
    }
}

main();
