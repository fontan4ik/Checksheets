"use strict";

const assert = require("assert");
const { formatFbsBroadcastDigest } = require("../telegram_notifier");

const digest = formatFbsBroadcastDigest([{
  completedAt: "2026-09-22T08:00:00.000Z",
  marketplace: "Ozon",
  warehouseName: "ЭТМ САМАРА",
  totalSku: 100,
  activeSku: 100,
  sourcePositiveSku: 100,
  acceptedSku: 90,
  skippedSku: 3,
  errorSku: 7,
  mismatchSku: 2,
  verificationStatus: "mismatch",
}]);

assert.match(digest, /В источнике с остатком: <b>100<\/b>/);
assert.match(digest, /Подтверждено отправкой: <b>90<\/b>/);
assert.match(digest, /Пропущено .*<b>3<\/b>/);
assert.match(digest, /Ошибки отправки: <b>7<\/b>/);
assert.match(digest, /есть расхождения.*2 SKU/);
assert.doesNotMatch(digest, /Транслировалось:/);
console.log("telegram report metrics: OK");
