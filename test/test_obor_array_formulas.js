#!/usr/bin/env node
'use strict';

const assert = require('assert');

function parseNumber(value) {
  const normalized = String(value ?? '')
    .replace(/[\u00a0 ]/g, '')
    .replace(',', '.')
    .trim();
  if (!normalized || normalized.startsWith('#')) return 0;
  const number = Number(normalized);
  return Number.isFinite(number) ? number : 0;
}

function weightedValue(baseArticle, sourceArticle, value) {
  const base = String(baseArticle).trim();
  const source = String(sourceArticle).trim();
  if (source === base) return parseNumber(value);
  const prefix = base + '-';
  if (!source.startsWith(prefix)) return 0;
  const suffix = source.slice(prefix.length);
  const multiplier = Number(suffix.replace(',', '.'));
  return Number.isFinite(multiplier) ? parseNumber(value) * multiplier : 0;
}

function aggregate(baseArticle, rows, valueFields) {
  return rows.reduce((sum, row) => {
    const sourceValue = valueFields.reduce((part, field) => part + parseNumber(row[field]), 0);
    return sum + weightedValue(baseArticle, row.article, sourceValue);
  }, 0);
}

const rows = [
  { article: '55222', fbo: '2', fbs: '3', ozonSalesFbo: '4', ozonSalesFbs: '1' },
  { article: '55222-10', fbo: '7', fbs: '0', ozonSalesFbo: '2', ozonSalesFbs: '1' },
  { article: '55222-5', fbo: '1', fbs: '2', ozonSalesFbo: '3', ozonSalesFbs: '0' },
  { article: '55222-foo', fbo: '99', fbs: '99', ozonSalesFbo: '99', ozonSalesFbs: '99' },
  { article: '99999-10', fbo: '100', fbs: '100', ozonSalesFbo: '100', ozonSalesFbs: '100' },
];

assert.strictEqual(aggregate('55222', rows, ['fbo']), 2 + 7 * 10 + 1 * 5);
assert.strictEqual(aggregate('55222', rows, ['fbs']), 3 + 0 * 10 + 2 * 5);
assert.strictEqual(
  aggregate('55222', rows, ['ozonSalesFbo', 'ozonSalesFbs']),
  5 + 3 * 10 + 3 * 5
);
assert.strictEqual(aggregate('99999', rows, ['fbo']), 100 * 10);
assert.strictEqual(aggregate('missing', rows, ['fbo']), 0);

console.log('OK: вариантные артикулы агрегируются с множителем после последнего дефиса');
console.log('OK: точное совпадение учитывается с множителем 1');
console.log('OK: чужие и нечисловые суффиксы не попадают в агрегат');
