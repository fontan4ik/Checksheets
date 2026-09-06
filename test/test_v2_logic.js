const axios = require("axios");

const OZON_CLIENT_ID = "142355";
const OZON_API_KEY = "fe539630-170b-4b48-b222-8ba092907a63";

const ozonHeaders = () => ({
  "Content-Type": "application/json",
  "Client-Id": OZON_CLIENT_ID,
  "Api-Key": OZON_API_KEY
});

const TARGET_WAREHOUSES = [
  { name: "ФЕРОН ФБС", column: 28, letter: "AB" },
  { name: "ЭТМ САМАРА", column: 29, letter: "AC" },
  { name: "РЕЗЕРВ", column: 30, letter: "AD" },
  { name: "НТЦ СКЛАД", column: 31, letter: "AE" },
  { name: "ПОДОРОЖНИК ФБС", column: 32, letter: "AF" },
  { name: "Арлайт Москва", column: 33, letter: "AG" },
  { name: "GAUSS MSK", column: 34, letter: "AH" }
];

async function testV2Logic() {
  console.log("1. Fetching warehouses via v2...");
  const whResp = await axios.post("https://api-seller.ozon.ru/v2/warehouse/list", {}, { headers: ozonHeaders() });
  const warehouses = whResp.data.warehouses || whResp.data.result || [];
  console.log(`Found ${warehouses.length} warehouses`);

  const foundTargets = [];
  TARGET_WAREHOUSES.forEach(tw => {
    const wh = warehouses.find(w => w.name === tw.name || (w.name && w.name.toLowerCase().includes(tw.name.toLowerCase())));
    if (wh) {
      foundTargets.push({
        ...tw,
        warehouseId: wh.warehouse_id,
        warehouseName: wh.name
      });
      console.log(`  Mapped ${tw.letter} (${tw.column}): "${tw.name}" -> ID ${wh.warehouse_id}`);
    }
  });

  const whMap = {};
  foundTargets.forEach(tw => {
    whMap[String(tw.warehouseId)] = tw;
  });

  // Test with some known Arlight and non-Arlight SKUs
  const testSkus = [1145227174, 1145227331, 1145227420, 246104569];
  console.log(`\n2. Fetching stocks for test SKUs: ${testSkus.join(", ")}`);
  
  const stocksResp = await axios.post(
    "https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs",
    { sku: testSkus, limit: 100 },
    { headers: ozonHeaders() }
  );

  const products = stocksResp.data.products || stocksResp.data.result || [];
  console.log(`Returned ${products.length} stock entries`);

  const stocksByCol = {};
  foundTargets.forEach(tw => {
    stocksByCol[tw.column] = {};
  });

  products.forEach(item => {
    const tw = whMap[String(item.warehouse_id)];
    if (tw) {
      const sku = item.sku;
      const total = (Number(item.present) || 0) + (Number(item.reserved) || 0);
      stocksByCol[tw.column][sku] = total;
      if (total > 0) {
        console.log(`  [${tw.letter} ${tw.name}] SKU ${sku} (${item.offer_id}): present=${item.present}, reserved=${item.reserved} -> total=${total}`);
      }
    }
  });

  console.log("\nSuccess!");
}

testV2Logic().catch(console.error);
