/** Fixed service layout: three independent model-keyed tables, headers on row 6. */
function ntcOperatorLayout_(sheet) {
  const h = sheet.getRange(6, 1, 1, 8).getDisplayValues()[0];
  if (h[0] === 'МОДЕЛЬ' && h[1] === 'КОЛИЧЕСТВО, ШТ' && h[2] === 'ПОСТАВКА, ШТ' && h[3] === 'СПИСАНИЕ, ШТ') return 'legacy';
  if (h[0] === 'МОДЕЛЬ' && h[1] === 'КОЛИЧЕСТВО, ШТ' && h[3] === 'МОДЕЛЬ' && h[4] === 'ПОСТАВКА, ШТ' && h[6] === 'МОДЕЛЬ' && h[7] === 'СПИСАНИЕ, ШТ') return 'three';
  if (h[0] === 'МОДЕЛЬ' && h[1] === 'КОЛИЧЕСТВО, ШТ' && h[3] === 'МОДЕЛЬ' && h[4] === 'ПОСТАВКА, ШТ' && h[6] === '' && h[7] === '') return 'partial';
  if (h.every(function(v) { return v === ''; })) return 'empty';
  throw new Error('Склад НТЦ: изменены заголовки таблиц в строке 6');
}
function ntcReadOperatorMovements_(sheet) {
  const layout = ntcOperatorLayout_(sheet), result = {supplies: [], writeoffs: [], extras: []};
  const count = Math.max(0, sheet.getLastRow() - 6);
  if (!count || layout === 'empty') return result;
  if (layout === 'partial') throw new Error('Завершите настройку третьей таблицы перед складской операцией');
  const rows = sheet.getRange(7, 1, count, 8).getValues();
  const tables = layout === 'legacy' ? [{model: 1, quantity: 3, type: 'supply'}, {model: 1, quantity: 4, type: 'writeoff'}] : [{model: 4, quantity: 5, type: 'supply'}, {model: 7, quantity: 8, type: 'writeoff'}];
  tables.forEach(function(table) {
    const seen = {};
    rows.forEach(function(r, i) {
      const rawModel = r[table.model - 1], model = String(rawModel == null ? '' : rawModel).trim(), qty = r[table.quantity - 1], row = i + 7;
      if (model && seen[model]) throw new Error('Модель ' + model + ' повторяется в таблице ' + (table.type === 'supply' ? 'поставки' : 'списания'));
      if (model) seen[model] = true;
      if (qty === '' || qty == null) return;
      if (!model) throw new Error('Не указана модель для количества, строка ' + row);
      if (typeof qty === 'boolean' || !Number.isSafeInteger(Number(qty)) || Number(qty) <= 0) throw new Error('Введите положительное целое количество физических штук, строка ' + row);
      const movement = {model: model, quantity: Number(qty), type: table.type};
      (table.type === 'supply' ? result.supplies : result.writeoffs).push(movement);
      result.extras.push({row: row, col: table.quantity, modelCol: table.model, model: rawModel, quantity: qty});
    });
  });
  return result;
}
/** Capture the entire input table before formatting, including unknown drafts. */
function ntcOperatorDrafts_(sheet, layout, models, type) {
  const count = Math.max(0, sheet.getLastRow() - 6), table = type === 'supply' ? [4, 5] : [7, 8];
  const rows = count ? sheet.getRange(7, 1, count, 8).getValues() : [];
  if (layout === 'three' || layout === 'partial') {
    const drafts = rows.map(function(r) { return [r[table[0] - 1], r[table[1] - 1]]; });
    while (drafts.length && drafts[drafts.length - 1].every(function(v) { return v === ''; })) drafts.pop();
    const present = {}; drafts.forEach(function(r) { if (r[0] !== '') present[String(r[0]).trim()] = true; });
    models.forEach(function(model) { if (!present[model]) drafts.push([model, '']); });
    return drafts;
  }
  const drafts = rows.filter(function(r) { return r[0] !== '' || r[type === 'supply' ? 2 : 3] !== ''; }).map(function(r) { return [r[0], layout === 'legacy' ? r[type === 'supply' ? 2 : 3] : '']; });
  const present = {}; drafts.forEach(function(r) { if (r[0] !== '') present[String(r[0]).trim()] = true; });
  models.forEach(function(model) { if (!present[model]) drafts.push([model, '']); });
  return drafts;
}
