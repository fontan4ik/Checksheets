#!/usr/bin/env node
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const context = vm.createContext({ alerts: [] });
vm.runInContext(fs.readFileSync(path.join(root, 'Shared_Настройки.js'), 'utf8'), context);
vm.runInContext(fs.readFileSync(path.join(root, 'Shared_Telegram.js'), 'utf8'), context);

const headers = ['', 'SKU Ozon\n', 'ЦЕНА ОЗОН', 'Артикул WB', 'Артикул WB'];
const sheet = {
  getName: () => 'ТЕСТ',
  getLastColumn: () => headers.length,
  getRange: () => ({ getValues: () => [headers] }),
};
context.sheet = sheet;
assert.strictEqual(vm.runInContext('columnByHeader_(sheet, "sku ozon")', context), 2);
assert.throws(() => vm.runInContext('columnByHeader_(sheet, "Артикул WB")', context), /найден 2 раз/);
assert.throws(() => vm.runInContext('columnByHeader_(sheet, "неизвестная колонка")', context), /найден 0 раз/);

vm.runInContext('sendTelegramAlertGAS = (...args) => alerts.push(args)', context);
assert.throws(() => vm.runInContext(`
  runWithTelegramAlertGAS_('outer', () =>
    runWithTelegramAlertGAS_('inner', () => { throw new Error('boom'); }))
`, context), /boom/);
assert.strictEqual(context.alerts.length, 1);
assert.strictEqual(context.alerts[0][0], 'inner');
assert.strictEqual(vm.runInContext('escapeTelegramHtmlGAS_("<x&>")', context), '&lt;x&amp;&gt;');
console.log('PASS header resolution and Telegram alert wrapper');
