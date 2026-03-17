const https = require('https');
const fs = require('fs');

const clientId = '142355';
const apiKey = 'fe539630-170b-4b48-b222-8ba092907a63';

function request(options, body) {
    return new Promise((resolve) => {
        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => data += chunk);
            res.on('end', () => resolve(data));
        });
        req.on('error', (e) => resolve('Error: ' + e.message));
        if (body) req.write(JSON.stringify(body));
        req.end();
    });
}

async function main() {
    const ozon = await request({
        hostname: 'api-seller.ozon.ru',
        path: '/v1/warehouse/list',
        method: 'POST',
        headers: {
            'Client-Id': clientId,
            'Api-Key': apiKey,
            'Content-Type': 'application/json'
        }
    }, { limit: 200 });
    fs.writeFileSync('ozon_list.txt', ozon);
    console.log('DONE');
}
main();
