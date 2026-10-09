const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const axios = require("axios");

const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "sync-etm-stocks.js"), "utf8");
const start = source.indexOf("const wbToken =");
const end = source.indexOf("\n\nconst wbHeaders", start);
if (start < 0 || end < 0) throw new Error("WB token configuration was not found");
const sandbox = {};
vm.runInNewContext(`${source.slice(start, end)}; result = wbToken`, sandbox);

async function main() {
  const candidateRows = JSON.parse(fs.readFileSync("/tmp/etm_candidate_source_rows.json", "utf8"));
  const candidates = new Set(candidateRows.map((item) => item.article));
  const cardsByVendorCode = new Map();
  const seenCursors = new Set();
  let cursor = null;
  let pages = 0;
  let totalCards = 0;

  while (true) {
    const settings = { sort: { ascending: true }, cursor: cursor || { limit: 100 } };
    const response = await axios.post(
      "https://content-api.wildberries.ru/content/v2/get/cards/list",
      { settings, filter: { withPhoto: -1 } },
      { headers: { Authorization: sandbox.result, "Content-Type": "application/json" }, timeout: 60000 },
    );
    const data = response.data || {};
    const cards = Array.isArray(data.cards) ? data.cards : [];
    if (!cards.length) break;
    pages++;
    totalCards += cards.length;
    for (const card of cards) {
      const vendorCode = String(card.vendorCode || "").trim();
      if (!candidates.has(vendorCode)) continue;
      cardsByVendorCode.set(vendorCode, {
        vendorCode,
        nmId: String(card.nmID || card.nmId || ""),
        sizes: (card.sizes || []).map((size) => ({
          chrtId: String(size.chrtID || ""),
          skus: size.skus || [],
        })),
      });
    }
    if (!data.cursor) break;
    const next = data.cursor;
    const nextKey = `${next.updatedAt || ""}|${next.nmID || ""}`;
    if (seenCursors.has(nextKey)) throw new Error("WB Content API repeated a pagination cursor");
    seenCursors.add(nextKey);
    cursor = next;
    if (totalCards > 50000) throw new Error("WB Content API exceeded the 50000 card safety limit");
    if (pages % 25 === 0) console.log(`Read ${totalCards} WB cards, matched ${cardsByVendorCode.size}`);
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }

  const matches = [...cardsByVendorCode.values()];
  fs.writeFileSync("/tmp/wb_candidate_cards.json", JSON.stringify(matches));
  console.log(JSON.stringify({ pages, totalCards, candidateCount: candidates.size, matched: matches.length }));
}

main().catch((error) => {
  console.error(error.response?.status ? `WB Content API returned HTTP ${error.response.status}` : error.message);
  process.exitCode = 1;
});
