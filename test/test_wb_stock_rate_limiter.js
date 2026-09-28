"use strict";

const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { test } = require("node:test");
const { createWbStockRateLimiter } = require("../wb_stock_rate_limiter");

test("shares request spacing across limiter instances", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "wb-rate-limit-"));
  const statePath = path.join(directory, "state.json");
  let currentTime = 1_000;
  const fakeWait = async (ms) => { currentTime += ms; };

  try {
    const first = createWbStockRateLimiter({
      requestsPerSecond: 0.5,
      statePath,
      now: () => currentTime,
      wait: fakeWait,
    });
    const second = createWbStockRateLimiter({
      requestsPerSecond: 0.5,
      statePath,
      now: () => currentTime,
      wait: fakeWait,
    });

    assert.strictEqual(await first.waitTurn(), 0);
    assert.strictEqual(await second.waitTurn(), 2_000);
    assert.strictEqual(currentTime, 3_000);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("propagates the server retry window to later requests", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "wb-rate-limit-"));
  const statePath = path.join(directory, "state.json");
  let currentTime = 1_000;
  const fakeWait = async (ms) => { currentTime += ms; };

  try {
    const first = createWbStockRateLimiter({
      requestsPerSecond: 1,
      statePath,
      now: () => currentTime,
      wait: fakeWait,
    });
    const second = createWbStockRateLimiter({
      requestsPerSecond: 1,
      statePath,
      now: () => currentTime,
      wait: fakeWait,
    });

    await first.waitTurn();
    assert.strictEqual(await first.deferForRateLimit({ "X-Ratelimit-Retry": "12" }, 3_000), 12_250);
    assert.strictEqual(await second.waitTurn(), 12_250);
    assert.strictEqual(currentTime, 13_250);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("reserves ten rate-limit units for a 409 response", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "wb-rate-limit-"));
  const statePath = path.join(directory, "state.json");
  let currentTime = 1_000;
  const fakeWait = async (ms) => { currentTime += ms; };

  try {
    const limiter = createWbStockRateLimiter({
      requestsPerSecond: 5,
      statePath,
      now: () => currentTime,
      wait: fakeWait,
    });

    await limiter.waitTurn();
    assert.strictEqual(await limiter.chargeResponse(409), 1_800);
    assert.strictEqual(await limiter.waitTurn(), 2_000);
    assert.strictEqual(currentTime, 3_000);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
