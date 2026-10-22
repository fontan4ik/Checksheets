"use strict";

const fs = require("fs");
const path = require("path");

// Only regular writer read paths use this gate. The onboarding publisher must
// be able to submit its prepared records before it creates their checkpoints.
function gatePublication(stocks, marketplace, options = {}) {
  if (marketplace === undefined) return stocks;
  if (!["ozon", "wb", "all"].includes(marketplace)) throw new Error(`Invalid onboarding gate marketplace: ${marketplace}`);
  const file = options.stateFile || process.env.CHECKSHEETS_ONBOARDING_STATE_FILE ||
    path.join(__dirname, "logs", "stream-onboarding-state.json");
  let state;
  try { state = JSON.parse(fs.readFileSync(file, "utf8")); }
  catch (error) {
    if (error.code === "ENOENT") return stocks; // Before first onboarding installation.
    throw new Error(`Invalid onboarding publication state: ${error.message}`);
  }
  if (!state || state.version !== 1 || !state.offers || typeof state.offers !== "object" || Array.isArray(state.offers) ||
      (state.enforcePublicationGate !== undefined && typeof state.enforcePublicationGate !== "boolean")) {
    throw new Error("Invalid onboarding publication state; regular stock writes blocked");
  }
  if (!state.enforcePublicationGate) return stocks;
  for (const entry of Object.values(state.offers)) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry) ||
        (entry.baseline !== undefined && typeof entry.baseline !== "boolean") ||
        ["unitReview", "rsQuarantined"].some((key) => entry[key] !== undefined && typeof entry[key] !== "boolean")) {
      throw new Error("Invalid onboarding offer state; regular stock writes blocked");
    }
  }
  const hasCheckpoint = (entry, destination) => typeof entry[`${destination}Fingerprint`] === "string" &&
    entry[`${destination}Fingerprint`].trim().length > 0;
  const allowed = stocks.filter((row) => {
    const id = String(row.offer_id ?? "").trim();
    if (!Object.prototype.hasOwnProperty.call(state.offers, id)) return false;
    const entry = state.offers[id];
    if (entry.baseline === true) return true;
    if (entry.unitReview || entry.rsQuarantined) return false;
    if (marketplace !== "all") return hasCheckpoint(entry, marketplace);
    const chrt = String(row.chrt_id ?? row.chrlid ?? "").trim();
    return hasCheckpoint(entry, "ozon") && (!chrt || hasCheckpoint(entry, "wb"));
  });
  for (const key of Object.keys(stocks)) {
    if (!/^(0|[1-9]\d*)$/.test(key)) allowed[key] = stocks[key];
  }
  const blocked = stocks.length - allowed.length;
  (options.logger || console.log)(`Onboarding publication gate (${marketplace}): allowed=${allowed.length}, blocked=${blocked}`);
  return allowed;
}

module.exports = { gatePublication };
