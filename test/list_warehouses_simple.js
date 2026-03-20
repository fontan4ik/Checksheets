const https = require('https');
const fs = require('fs');

const clientId = '142355';
const apiKey = 'fe539630-170b-4b48-b222-8ba092907a63';
const wbToken = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg2MDUyMTMxLCJpZCI6IjAxOWMyZDI4LTI0MzMtNzY2MC1iZDU4LTRlNjVhYzMwM2E0YiIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.fZu3j3YZBrIIEAZ6KtuWjTZ7HfPS3sR8Z6vOdmfT5L8hpQmjvVq3zf9Io-2wXTifmda46JEKhCZafyUlTUfpdA';

function request(options, body) {
    return new Promise((resolve, reject) => {
        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => data += chunk);
            res.on('end', () => {
                try {
                    resolve(JSON.parse(data));
                } catch (e) {
                    resolve(data);
                }
            });
        });
        req.on('error', (e) => resolve({error: e.message}));
        if (body) req.write(JSON.stringify(body));
        req.end();
    });
}

async function main() {
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
    const ozon = await request(ozonOptions, {});

    const wbOptions = {
        hostname: 'marketplace-api.wildberries.ru',
        path: '/api/v3/warehouses',
        method: 'GET',
        headers: {
            'Authorization': 'Bearer ' + wbToken
        }
    };
    const wb = await request(wbOptions);

    const result = { ozon, wb };
    fs.writeFileSync('warehouse_ids.txt', JSON.stringify(result, null, 2));
    console.log('DONE');
}

main();
