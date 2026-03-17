const fs = require('fs');
try {
    const data = fs.readFileSync('output.txt');
    console.log('File size:', data.length);
    console.log('Content (Hex):', data.toString('hex'));
    console.log('Content (UTF-8):', data.toString('utf8'));
} catch (e) {
    console.log('Error:', e.message);
}
