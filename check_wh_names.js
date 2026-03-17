const https = require('https');
const fs = require('fs');

const clientId = '142355';
const apiKey = 'fe539630-170b-4b48-b222-8ba092907a63';
const searchIds = [1020005000217829, 1020005005391400, 1020005004656250];

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
    let output = '';
    const ozonText = await request({
        hostname: 'api-seller.ozon.ru',
        path: '/v1/warehouse/list',
        method: 'POST',
        headers: {
            'Client-Id': clientId,
            'Api-Key': apiKey,
            'Content-Type': 'application/json'
        }
    }, { limit: 200 });
    
    try {
        const ozon = JSON.parse(ozonText);
        if (ozon.result) {
            ozon.result.forEach(wh => {
                const line = `WH: "${wh.name}" ID: ${wh.warehouse_id}\n`;
                output += line;
                if (searchIds.includes(wh.warehouse_id) || wh.name.includes('ПОДОРОЖНИК') || wh.name.includes('1C')) {
                    output += `MATCH: "${wh.name}" ID: ${wh.warehouse_id}\n`;
                }
            });
        }
    } catch (e) {
        output += `Error: ${e.message}\n`;
    }
    fs.writeFileSync('wh_results.txt', output);
    console.log('Results written to wh_results.txt');
}

main();
