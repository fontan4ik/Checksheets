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

async function simulateUpdate() {
  console.log("1. Fetching warehouses list via v2...");
  const whResp = await axios.post(
    "https://api-seller.ozon.ru/v2/warehouse/list",
    { limit: 200 },
    { headers: ozonHeaders() }
  );
  const warehouses = whResp.data.warehouses || [];
  console.log(`Fetched ${warehouses.length} warehouses`);

  const targetWarehouses = [];
  TARGET_WAREHOUSES.forEach(tw => {
    const wh = warehouses.find(w => w.name === tw.name || (w.name && w.name.toLowerCase().includes(tw.name.toLowerCase())));
    if (wh) {
      targetWarehouses.push({
        ...tw,
        warehouseId: wh.warehouse_id,
        warehouseName: wh.name
      });
    }
  });

  const targetWhMap = {};
  targetWarehouses.forEach(tw => {
    targetWhMap[String(tw.warehouseId)] = tw;
    console.log(`  Mapped ${tw.letter} (${tw.column}): "${tw.warehouseName}" (ID: ${tw.warehouseId})`);
  });

  // Simulated SKUs including Arlight item 1145227174
  const testSkus = [1145227174, 1145227331, 1145227420, 246104569];
  const numRows = 4;
  const skuToIndices = new Map();
  testSkus.forEach((sku, idx) => {
    skuToIndices.set(sku, [idx]);
  });

  const columnsData = {};
  targetWarehouses.forEach(tw => {
    columnsData[tw.column] = new Array(numRows).fill(0);
  });

  console.log("\n2. Fetching stocks via v2...");
  const payload = { sku: testSkus, limit: 1000 };
  const resp = await axios.post(
    "https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs",
    payload,
    { headers: ozonHeaders() }
  );

  const products = resp.data.products || [];
  console.log(`Got ${products.length} product records from API`);

  products.forEach(item => {
    const tw = targetWhMap[String(item.warehouse_id)];
    if (tw) {
      const sku = Number(item.sku);
      const present = Number(item.present) || 0;
      const reserved = Number(item.reserved) || 0;
      const total = present + reserved;
      const indices = skuToIndices.get(sku);
      if (indices) {
        for (let k = 0; k < indices.length; k++) {
          columnsData[tw.column][indices[k]] = total;
        }
      }
    }
  });

  console.log("\n3. Resulting columns data:");
  targetWarehouses.forEach(tw => {
    console.log(`Col ${tw.letter} (${tw.column}) "${tw.warehouseName}":`, columnsData[tw.column]);
  });

  // Specifically check Arlight SKU 1145227174 on ЭТМ САМАРА
  const etmCol = targetWarehouses.find(tw => tw.name === "ЭТМ САМАРА").column;
  console.log(`\nArlight SKU 1145227174 stock on ЭТМ САМАРА (Col ${etmCol}):`, columnsData[etmCol][0]);
  if (columnsData[etmCol][0] === 127) {
    console.log("SUCCESS! Exactly matches Ozon inventory (127 pcs)!");
  } else {
    console.log("Note: value is", columnsData[etmCol][0]);
  }
}

simulateUpdate().catch(console.error);
