'use strict';
// Read-only API identity lookup. Credentials remain inside the VM and request headers.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const config = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(root, 'Shared_Настройки.js'), 'utf8') + '\nthis.marketplaceHeaders = ozonHeaders();', config);
const remaining = JSON.parse(fs.readFileSync(path.join(__dirname, 'etm_codes_remaining_20261016.json'), 'utf8'));
async function api(endpoint, payload) {
  const response = await fetch('https://api-seller.ozon.ru' + endpoint, {
    method: 'POST', headers: config.marketplaceHeaders, body: JSON.stringify(payload), signal: AbortSignal.timeout(60000)
  });
  if (!response.ok) throw new Error('Ozon ' + endpoint + ' HTTP ' + response.status);
  return response.json();
}
async function main() {
  const offers = remaining.rows.map(row => row.offer_id);
  const byOffer = new Map();
  const info = await api('/v3/product/info/list', { offer_id: offers });
  for (const item of info.items || info.result?.items || []) byOffer.set(item.offer_id, item);
  const attrs = new Map();
  for (let start = 0; start < offers.length; start += 100) {
    const result = await api('/v4/product/info/attributes', { filter: { offer_id: offers.slice(start, start + 100), visibility: 'ALL' }, limit: 100 });
    for (const item of result.result || []) attrs.set(item.offer_id, item);
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  const rows = remaining.rows.map(source => {
    const info = byOffer.get(source.offer_id);
    const attributes = attrs.get(source.offer_id);
    const selected = {};
    for (const attribute of attributes?.attributes || []) {
      if ([85, 9048, 8229, 4389].includes(Number(attribute.id))) selected[attribute.id] = attribute.values;
    }
    return { ...source, marketplace: info ? {
      product_id: info.id, name: info.name, barcodes: info.barcodes || [],
      model_info: info.model_info || null, description_category_id: info.description_category_id,
      type_id: info.type_id, archived: info.is_archived, selected_attributes: selected,
      attribute_name: attributes?.name || null
    } : null };
  });
  const output = { at: new Date().toISOString(), source: 'Ozon Seller API v3 product info + v4 attributes',
    count: rows.length, ozon_matched: rows.filter(r => r.marketplace).length, attributes_matched: attrs.size, rows };
  fs.writeFileSync(path.join(__dirname, 'etm_remaining_marketplace_identity_20261016.json'), JSON.stringify(output, null, 2));
  console.log(JSON.stringify({ count: output.count, ozon_matched: output.ozon_matched, attributes_matched: output.attributes_matched,
    missing_brands: rows.filter(r => r.reason === 'missing_brand').map(r => ({ offer_id: r.offer_id, name: r.marketplace?.name, barcodes: r.marketplace?.barcodes, attributes: r.marketplace?.selected_attributes })) }, null, 2));
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
