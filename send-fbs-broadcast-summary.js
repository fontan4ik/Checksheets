#!/usr/bin/env node
/** Sends one scheduled Telegram digest for completed FBS warehouse broadcasts. */

const { sendQueuedFbsBroadcastSummary } = require("./telegram_notifier");

sendQueuedFbsBroadcastSummary()
  .then((sent) => console.log(sent ? "FBS broadcast digest sent." : "No FBS broadcasts pending."))
  .catch((error) => {
    console.error(`FBS broadcast digest failed: ${error.stack || error.message || error}`);
    process.exitCode = 1;
  });
