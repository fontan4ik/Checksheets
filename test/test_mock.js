// ТЕСТ MOCK ДАННЫХ ДЛЯ WB СКЛАДОВ

const mockWarehouses = {
  warehouses: [
    { id: 1449484, name: "ФБС ФЕРОН МОСКВА", officeId: 10110, isFbs: true },
    { id: 798761, name: "ВольтМир", officeId: 128, isFbs: true }
  ]
};

const mockStocks1449484 = {
  stocks: [
    { sku: "22068-1", amount: 10 },
    { sku: "23348-1", amount: 25 },
    { sku: "25841-5", amount: 15 }
  ]
};

const mockStocks798761 = {
  stocks: [
    { sku: "22068-1", amount: 5 },
    { sku: "23348-1", amount: 12 },
    { sku: "39171-1", amount: 30 }
  ]
};

console.log("Mock данные загружены:");
console.log("Складов:", mockWarehouses.warehouses.length);
console.log("Стоков 1449484:", mockStocks1449484.stocks.length);
console.log("Стоков 798761:", mockStocks798761.stocks.length);
