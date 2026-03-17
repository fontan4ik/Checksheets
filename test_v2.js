const https = require('https');

const TOKEN = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzg2MDUyMTMxLCJpZCI6IjAxOWMyZDI4LTI0MzMtNzY2MC1iZDU4LTRlNjVhYzMwM2E0YiIsImlpZCI6MTk3ODU3MDksIm9pZCI6MTc3NTU3LCJzIjo3OTM0LCJzaWQiOiI2OGI4Mjg0Ni0wZDk0LTRiNDEtODQ1NC1kYzM1MzM0ODJjOWEiLCJ0IjpmYWxzZSwidWlkIjoxOTc4NTcwOX0.fZu3j3YZBrIIEAZ6KtuWjTZ7HfPS3sR8Z6vOdmfT5L8hpQmjvVq3zf9Io-2wXTifmda46JEKhCZafyUlTUfpdA';

const body = JSON.stringify({
    data: [
        { nmID: 489278748, price: 4566 }
    ]
});

const options = {
    hostname: 'discounts-prices-api.wildberries.ru',
    path: '/api/v2/upload/task',
    method: 'POST',
    headers: {
        'Authorization': `Bearer ${TOKEN}`,
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
};

const req = https.request(options, (res) => {
    let data = '';
    console.log('STATUS:', res.statusCode);
    res.on('data', d => data += d);
    res.on('end', () => {
        console.log('BODY:', data);
        require('fs').writeFileSync('final_test.json', JSON.stringify({
            status: res.statusCode,
            body: data
        }, null, 2));
    });
});

req.on('error', e => {
    console.error('ERROR:', e.message);
    require('fs').writeFileSync('final_test.json', JSON.stringify({ error: e.message }, null, 2));
});

req.write(body);
req.end();
