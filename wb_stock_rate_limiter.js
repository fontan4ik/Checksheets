"use strict";

const fs = require("fs");
const path = require("path");

const DEFAULT_STATE_PATH = path.join(
  process.env.WB_STOCK_RATE_LIMIT_DIR || "/tmp/checksheets_locks",
  "wb_stock_rate_limiter.json",
);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function retryDelayMs(headers, fallbackMs) {
  const retryValue = Object.entries(headers || {}).find(
    ([key]) => key.toLowerCase() === "x-ratelimit-retry",
  )?.[1];
  const seconds = Number(retryValue);
  if (Number.isFinite(seconds) && seconds > 0) {
    // Small cushion avoids retrying on the boundary of WB's replenishment window.
    return Math.max(fallbackMs, seconds * 1000 + 250);
  }
  return fallbackMs;
}

function processIsAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === "EPERM";
  }
}

function createWbStockRateLimiter({
  requestsPerSecond = 5,
  statePath = DEFAULT_STATE_PATH,
  now = Date.now,
  wait = sleep,
  logger = () => {},
} = {}) {
  const rps = Number(requestsPerSecond);
  if (!Number.isFinite(rps) || rps <= 0) {
    throw new Error(`WB request rate must be positive; got ${requestsPerSecond}`);
  }
  const intervalMs = 1000 / Math.min(5, rps);
  const lockPath = `${statePath}.lock`;

  function readState() {
    try {
      const state = JSON.parse(fs.readFileSync(statePath, "utf8"));
      return {
        nextRequestAt: Number(state.nextRequestAt) || 0,
        blockedUntil: Number(state.blockedUntil) || 0,
      };
    } catch {
      return { nextRequestAt: 0, blockedUntil: 0 };
    }
  }

  function writeState(state) {
    const tempPath = `${statePath}.${process.pid}.${now()}.tmp`;
    fs.writeFileSync(tempPath, JSON.stringify(state), { mode: 0o600 });
    fs.renameSync(tempPath, statePath);
  }

  async function withStateLock(update) {
    fs.mkdirSync(path.dirname(statePath), { recursive: true });
    const startedWaitingAt = now();
    while (true) {
      try {
        fs.mkdirSync(lockPath);
        fs.writeFileSync(
          path.join(lockPath, "owner.json"),
          JSON.stringify({ pid: process.pid, createdAt: now() }),
          { mode: 0o600 },
        );
        break;
      } catch (error) {
        if (error.code !== "EEXIST") throw error;
        let owner = null;
        let lockAgeMs = 0;
        try {
          owner = JSON.parse(fs.readFileSync(path.join(lockPath, "owner.json"), "utf8"));
          lockAgeMs = Math.max(0, now() - Number(owner.createdAt || 0));
        } catch {
          try {
            lockAgeMs = Math.max(0, now() - fs.statSync(lockPath).mtimeMs);
          } catch {
            continue;
          }
        }
        if ((owner && !processIsAlive(Number(owner.pid))) || (!owner && lockAgeMs > 5000)) {
          try {
            fs.unlinkSync(path.join(lockPath, "owner.json"));
          } catch {}
          try {
            fs.rmdirSync(lockPath);
          } catch {}
          continue;
        }
        if (now() - startedWaitingAt > 120000) {
          throw new Error(`Timed out waiting for WB rate-limit lock: ${lockPath}`);
        }
        await wait(25);
      }
    }

    try {
      const state = readState();
      const result = update(state);
      writeState(state);
      return result;
    } finally {
      try {
        fs.unlinkSync(path.join(lockPath, "owner.json"));
      } catch {}
      try {
        fs.rmdirSync(lockPath);
      } catch {}
    }
  }

  return {
    async waitTurn() {
      const scheduledAt = await withStateLock((state) => {
        const requestAt = Math.max(now(), state.nextRequestAt, state.blockedUntil);
        state.nextRequestAt = requestAt + intervalMs;
        return requestAt;
      });
      const delayMs = Math.max(0, scheduledAt - now());
      if (delayMs > 0) await wait(delayMs);
      return delayMs;
    },

    async deferForRateLimit(headers, fallbackMs) {
      const delayMs = retryDelayMs(headers, fallbackMs);
      const blockedUntil = await withStateLock((state) => {
        state.blockedUntil = Math.max(state.blockedUntil, now() + delayMs);
        return state.blockedUntil;
      });
      logger(`WB shared cooldown: ${Math.max(0, blockedUntil - now())} ms`);
      return Math.max(0, blockedUntil - now());
    },

    async chargeResponse(status) {
      // WB charges a 409 stock update as ten requests. The request itself
      // already reserved one interval, so reserve the remaining nine here.
      if (Number(status) !== 409) return 0;
      return withStateLock((state) => {
        const penaltyMs = intervalMs * 9;
        state.nextRequestAt = Math.max(state.nextRequestAt, now()) + penaltyMs;
        return penaltyMs;
      });
    },
  };
}

module.exports = { createWbStockRateLimiter, retryDelayMs };
