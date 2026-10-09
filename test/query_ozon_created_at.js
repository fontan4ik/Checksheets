const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const axios = require("axios");

const root = path.resolve(__dirname, "..");
const ids = fs.readdirSync("/tmp")
  .filter((name) => /^ozon_created_product_ids_\d+\.txt$/.test(name))
  .sort()
  .flatMap((name) => fs.readFileSync(path.join("/tmp", name), "utf8").split(/\s+/))
  .filter(Boolean);

if (!ids.length) throw new Error("No Ozon product IDs were provided");

const source = fs.readFileSync(path.join(root, "sync-etm-stocks.js"), "utf8");
const start = source.indexOf("const ozonHeaders = () => ({");
if (start < 0) throw new Error("Ozon header configuration was not found");
const close = source.indexOf("\n});", start);
if (close < 0) throw new Error("Ozon header configuration was incomplete");
const sandbox = {};
vm.runInNewContext(`${source.slice(start, close + 4)}; result = ozonHeaders()`, sandbox);
const headers = sandbox.result;

async function main() {
  const result = [];
  for (let offset = 0; offset < ids.length; offset += 1000) {
    const response = await axios.post(
      "https://api-seller.ozon.ru/v3/product/info/list",
      { product_id: ids.slice(offset, offset + 1000) },
      { headers, timeout: 60000 },
    );
    const items = response.data?.items || response.data?.result?.items;
    if (!Array.isArray(items)) throw new Error("Ozon response omitted product items");
    for (const item of items) {
      result.push({
        product_id: String(item.product_id ?? item.id ?? ""),
        offer_id: String(item.offer_id ?? ""),
        sku: String(item.sku ?? ""),
        created_at: item.created_at ?? null,
      });
    }
    console.log(`Read ${Math.min(offset + 1000, ids.length)}/${ids.length}`);
    if (offset + 1000 < ids.length) await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  fs.writeFileSync("/tmp/ozon_created_at_results.json", JSON.stringify(result));
  const dates = result.map((item) => item.created_at).filter(Boolean).sort();
  console.log(JSON.stringify({
    requested: ids.length,
    returned: result.length,
    withCreatedAt: dates.length,
    oldest: dates[0] ?? null,
    newest: dates.at(-1) ?? null,
  }));
}

main().catch((error) => {
  console.error(error.response?.status ? `Ozon API returned HTTP ${error.response.status}` : error.message);
  process.exitCode = 1;
});
