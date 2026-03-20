const https = require('https');
const fs = require('fs');

const clientId = '142355';
const apiKey = 'fe539630-170b-4b48-b222-8ba092907a63';

const req = https.request({
    hostname: 'api-seller.ozon.ru',
    path: '/v1/warehouse/list',
    method: 'POST',
    headers: {
        'Client-Id': clientId,
        'Api-Key': apiKey,
        'Content-Type': 'application/json'
    }
}, res => {
    let data = '';
    res.on('data', chunk => data += chunk);
    res.on('end', () => {
        fs.writeFileSync('C:\\AI\\ozon_list.json', data);
        console.log('FILE_WRITTEN');
    });
});
req.write(JSON.stringify({ limit: 200 }));
req.end();
