"use strict";

// Match acknowledgements to the requested offer and warehouse. A duplicate or
// unrelated acknowledgement must never compensate for a missing product.
function reconcileOzonStockResults(batch, data, warehouseId) {
  const byOfferId = new Map();
  for (const item of Array.isArray(data?.result) ? data.result : []) {
    if (!item?.offer_id) continue;
    if (item.warehouse_id != null && String(item.warehouse_id) !== String(warehouseId)) continue;
    const key = String(item.offer_id);
    if (!byOfferId.has(key)) byOfferId.set(key, item);
    else byOfferId.set(key, { offer_id: key, updated: false, errors: [{ code: "AMBIGUOUS_RESULT", message: "Duplicate Ozon acknowledgement" }] });
  }
  return batch.map((requested) => byOfferId.get(String(requested.offer_id)) || {
    offer_id: String(requested.offer_id),
    updated: false,
    errors: [{ code: "MISSING_RESULT", message: "Ozon did not acknowledge the requested product/warehouse" }],
  });
}

const WAREHOUSE_RESTRICTIONS = new Set(["OVER_MAX_OVH_NON_KGT", "OVER_MAX_OVH_KGT", "NON_KGT_ON_KGT_WAREHOUSE"]);

function isOzonWarehouseRestriction(item) {
  return Array.isArray(item?.errors) && item.errors.length > 0 &&
    item.errors.every((error) => WAREHOUSE_RESTRICTIONS.has(error.code));
}

function ozonRestrictionDetails(offerIds) {
  const ids = [...(offerIds || [])];
  if (!ids.length) return null;
  return `ограничение габаритов/типа склада Ozon: ${ids.length} SKU (${ids.slice(0, 8).join(", ")}${ids.length > 8 ? ", …" : ""}); проверьте габариты карточек и совместимость склада КГТ`;
}

module.exports = { reconcileOzonStockResults, isOzonWarehouseRestriction, ozonRestrictionDetails };
