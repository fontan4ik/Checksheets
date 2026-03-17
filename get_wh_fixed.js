const https = require('https');
const fs = require('fs');
const req = https.request({
    hostname: 'api-seller.ozon.ru',
    path: '/v1/warehouse/list',
    method: 'POST',
    headers: {
        'Client-Id': '142355',
        'Api-Key': 'fe539630-170b-4b48-b222-8ba092907a63',
        'Content-Type': 'application/json'
    }
}, res => {
    let data = '';
    res.on('data', chunk => data += chunk);
    res.on('end', () => {
        try {
            const body = JSON.parse(data);
            if (body.result) {
                const searchIds = [1020005000217829, 1020005005391400, 1020005004656250];
                const matches = body.result.filter(w => 
                    searchIds.includes(w.warehouse_id) || 
                    w.name.includes('ПОДОРОЖНИК') || 
                    w.name.includes('1C')
                ).map(w => `${w.name} : ${w.warehouse_id}`).join('\n');
                fs.writeFileSync('C:/AI/wh_check.txt', matches);
            }
        } catch (e) {}
    });
});
req.write(JSON.stringify({ limit: 200 }));
req.end();
