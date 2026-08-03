#!/usr/bin/env node
'use strict';

/**
 * Read-only Ozon Local Sales client.
 *
 * The endpoint is an internal Seller web-gateway route, so this script does
 * not copy cookies or API keys. It connects to the already authenticated
 * local Chrome instance over CDP and performs fetch() inside the Ozon page.
 *
 * Usage:
 *   node test/ozon-local-sales-api.js \
 *     --from 2026-07-04 --to 2026-08-02
 *
 * Requirements:
 *   - Chrome must be running with remote debugging on 127.0.0.1:9227.
 *   - An authenticated seller.ozon.ru page must be open in that profile.
 *
 * This version intentionally has no Google Sheets write path. It is a
 * read-only probe until the per-SKU mapping and write policy are approved.
 */

const DEFAULT_CDP_URL = process.env.OZON_CDP_URL || 'http://127.0.0.1:9227';
const COMPANY_ID = process.env.OZON_COMPANY_ID || '142355';
const ENDPOINT = '/api/logistic/v1/statistic';

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const value = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : true;
    args[key] = value;
  }
  return args;
}

function parseDate(value, flag) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) {
    throw new Error(`${flag} must be YYYY-MM-DD`);
  }
  const [year, month, day] = value.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    throw new Error(`${flag} is not a valid calendar date`);
  }
  return { year, month, day };
}

function usage() {
  console.error(
    'Usage: node test/ozon-local-sales-api.js --from YYYY-MM-DD --to YYYY-MM-DD [--cdp-url URL]'
  );
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`CDP discovery failed: HTTP ${response.status}`);
  return response.json();
}

class CdpClient {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.nextId = 1;
    this.pending = new Map();
    this.opened = new Promise((resolve, reject) => {
      this.ws.addEventListener('open', resolve, { once: true });
      this.ws.addEventListener('error', reject, { once: true });
    });
    this.ws.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (!message.id) return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message || 'CDP error'));
      else pending.resolve(message.result);
    });
  }

  async send(method, params = {}) {
    await this.opened;
    const id = this.nextId++;
    const result = new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
    this.ws.send(JSON.stringify({ id, method, params }));
    return result;
  }

  close() {
    this.ws.close();
  }
}

async function findOzonPage(cdpUrl) {
  const targets = await getJson(`${cdpUrl}/json/list`);
  const page = targets.find(
    (target) =>
      target.type === 'page' &&
      /^https:\/\/seller\.ozon\.ru\//.test(target.url || '') &&
      target.webSocketDebuggerUrl
  );
  if (!page) {
    throw new Error('No authenticated seller.ozon.ru page found in the local CDP browser');
  }
  return page;
}

async function fetchStatistic(page, period) {
  const cdp = new CdpClient(page.webSocketDebuggerUrl);
  try {
    const expression = `
      (async () => {
        const response = await fetch(${JSON.stringify(ENDPOINT)}, {
          method: 'POST',
          credentials: 'include',
          headers: {
            'content-type': 'application/json',
            'x-o3-company-id': ${JSON.stringify(COMPANY_ID)},
            'x-o3-app-name': 'seller-ui',
            'x-o3-language': 'ru'
          },
          body: JSON.stringify(${JSON.stringify({
            period,
            flags: { skuFlag: { count: 3, withTopOverpaymentSku: true } }
          })})
        });
        const text = await response.text();
        let body = null;
        try { body = JSON.parse(text); } catch (_) { body = { rawPrefix: text.slice(0, 300) }; }
        return { status: response.status, body };
      })()
    `;
    const result = await cdp.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.text || 'Browser evaluation failed');
    }
    return result.result.value;
  } finally {
    cdp.close();
  }
}

async function main() {
  const args = parseArgs(process.argv);
  if (!args.from || !args.to) {
    usage();
    process.exitCode = 2;
    return;
  }

  const from = parseDate(args.from, '--from');
  const to = parseDate(args.to, '--to');
  const period = { from, to };
  const cdpUrl = args['cdp-url'] || DEFAULT_CDP_URL;
  const page = await findOzonPage(cdpUrl);
  const response = await fetchStatistic(page, period);

  const output = {
    endpoint: ENDPOINT,
    page: page.url,
    period,
    http_status: response.status,
    local_data: response.body && response.body.localData,
    overpayment: response.body && response.body.overpayment,
    overpayment_reasons: response.body && response.body.overpaymentReasons,
    top_sku: response.body && response.body.overpaymentSku,
    calculation_days: response.body && response.body.calculationDays,
    grace: response.body && response.body.grace
  };
  console.log(JSON.stringify(output, null, 2));

  if (response.status !== 200 || !response.body || !response.body.overpayment) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(`ERROR: ${error.message}`);
  process.exitCode = 1;
});
