const fs = require('fs');
const data = JSON.parse(fs.readFileSync('wb_orders_old_api.json', 'utf8'));
const orders = data.filter(o => o.supplierArticle === '22068-1' && !o.isCancel);

console.log('Заказов:', orders.length);
const sum = orders.reduce((s, o) => s + o.priceWithDisc, 0);
console.log('Сумма priceWithDisc:', sum);
orders.forEach((o, i) => console.log(`Заказ ${i + 1}:`, o.priceWithDisc));
