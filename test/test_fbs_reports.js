const { sendFbsWarehouseReport } = require("../telegram_notifier");

async function test() {
  console.log("Testing Ozon warehouse report...");
  const res1 = await sendFbsWarehouseReport({
    marketplace: "Ozon",
    warehouseName: "ЭТМ САМАРА",
    totalSku: 7358,
    activeSku: 3429,
    marketplaceStockSku: 3429,
    marketplaceTotalPieces: 48210,
    durationSec: 725, // 12 мин 5 сек
  });
  console.log("Ozon report sent:", res1);

  await new Promise((r) => setTimeout(r, 600));

  console.log("Testing WB warehouse report...");
  const res2 = await sendFbsWarehouseReport({
    marketplace: "ВБ",
    warehouseName: "ВольтМир",
    totalSku: 7358,
    activeSku: 2579,
    marketplaceStockSku: 2572,
    marketplaceTotalPieces: 39150,
    durationSec: 725, // 12 мин 5 сек
  });
  console.log("WB report sent:", res2);
}

test().catch(console.error);
