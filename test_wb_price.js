const https = require('https');

const TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg2MDUyMTMxLCJpZCI6IjAxOWMyZDI4LTI0MzMtNzY2MC1iZDU4LTRlNjVhYzMwM2E0YiIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.fZu3j3YZBrIIEAZ6KtuWjTZ7HfPS3sR8Z6vOdmfT5L8hpQmjvVq3zf9Io-2wXTifmda46JEKhCZafyUlTUfpdA';
const HOST = 'discounts-prices-api.wildberries.ru';
const PATH = '/api/v2/upload/task';

const body = JSON.stringify({
    data: [
        { nmID: 489278748, price: 4566 },
        { nmID: 669242720, price: 10818 },
        { nmID: 424697904, price: 5052 },
        { nmID: 489278711, price: 7745 }
    ]
});

const options = {
    hostname: HOST,
    path: PATH,
    method: 'POST',
    headers: {
        'Authorization': `Bearer ${TOKEN}`,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Content-Length': Buffer.byteLength(body)
    },
    timeout: 10000
};

console.log('📤 Sending request to WB API...');
console.log('📦 Payload:', body);

const req = https.request(options, (res) => {
    let responseData = '';
    console.log('📥 Status:', res.statusCode);
    
    res.on('data', (chunk) => {
        responseData += chunk;
    });

    res.on('end', () => {
        console.log('📥 Response:', responseData);
        const result = {
            statusCode: res.statusCode,
            headers: res.headers,
            body: responseData
        };
        try {
            result.json = JSON.parse(responseData);
        } catch (e) {}
        
        require('fs').writeFileSync('debug_output.json', JSON.stringify(result, null, 2));
        
        if (res.statusCode === 200 || res.statusCode === 201) {
            console.log('✅ Success!');
        } else {
            console.log('❌ Failed.');
        }
    });
});

req.on('error', (e) => {
    console.error('❌ Error:', e.message);
    require('fs').writeFileSync('debug_output.json', JSON.stringify({ error: e.message }, null, 2));
});

req.on('timeout', () => {
    console.error('❌ Timeout reached!');
    require('fs').writeFileSync('debug_output.json', JSON.stringify({ error: 'timeout' }, null, 2));
    req.destroy();
});

req.write(body);
req.end();
