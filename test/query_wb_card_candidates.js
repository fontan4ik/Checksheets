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
  const statePath = "/tmp/wb_candidate_scan_state.json";
  const saved = fs.existsSync(statePath) ? JSON.parse(fs.readFileSync(statePath, "utf8")) : {};
  const cardsByVendorCode = new Map((saved.matches || []).map((card) => [card.vendorCode, card]));
  const seenCursors = new Set(saved.seenCursors || []);
  let cursor = saved.cursor || null;
  let pages = saved.pages || 0;
  let totalCards = saved.totalCards || 0;

  while (true) {
    const settings = {
      sort: { ascending: true },
      cursor: cursor
        ? { updatedAt: cursor.updatedAt, nmID: cursor.nmID, limit: 100 }
        : { limit: 100 },
    };
    let response;
    for (let attempt = 1; ; attempt++) {
      try {
        response = await axios.post(
          "https://content-api.wildberries.ru/content/v2/get/cards/list",
          { settings, filter: { withPhoto: -1 } },
          { headers: { Authorization: sandbox.result, "Content-Type": "application/json" }, timeout: 60000 },
        );
        break;
      } catch (error) {
        const status = error.response?.status;
        const maxAttempts = status === 429 ? 3 : 5;
        if (![429, 500, 502, 503, 504].includes(status) || attempt >= maxAttempts) throw error;
        const retryAfter = Number(error.response?.headers?.["retry-after"]);
        const delay = status === 429
          ? (Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : 60000)
          : Math.min(30000, 1000 * 2 ** (attempt - 1));
        console.warn("WB Content API HTTP " + status + "; retry " + attempt + "/" + maxAttempts + " in " + delay + "ms");
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    }
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
    fs.writeFileSync(statePath, JSON.stringify({
      pages, totalCards, cursor, seenCursors: [...seenCursors], matches: [...cardsByVendorCode.values()],
    }));
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
