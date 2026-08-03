#!/usr/bin/env node
'use strict';

/**
 * Read-only Ozon Local Sales client.
 *
 * The endpoint is an internal Seller web-gateway route. This script does not
 * copy cookies or API keys: it connects to the already authenticated local
 * Chrome instance over CDP and executes fetch() inside the Ozon page.
 *
 * Usage:
 *   node test/ozon-local-sales-api.js --from 2026-07-04 --to 2026-08-02
 *   node test/ozon-local-sales-api.js --from 2026-07-04 --to 2026-08-02 --items
 *
 * Requirements:
 *   - Chrome must be running with remote debugging on 127.0.0.1:9227.
 *   - An authenticated seller.ozon.ru page must be open in that profile.
 *
 * The script is read-only. Google Sheets writes are deliberately not enabled
 * until the per-SKU reconciliation policy is approved.
 */

const DEFAULT_CDP_URL = process.env.OZON_CDP_URL || 'http://127.0.0.1:9227';
const COMPANY_ID = process.env.OZON_COMPANY_ID || '142355';
const STATISTIC_ENDPOINT = '/api/logistic/v1/statistic';
const ITEMS_ENDPOINT = '/api/logistic/v1/items/table';
const ITEMS_PAGE_SIZE = 28; // frontend default (T.UN)

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
    'Usage: node test/ozon-local-sales-api.js --from YYYY-MM-DD --to YYYY-MM-DD [--items] [--cdp-url URL]'
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
    throw new Error('No seller.ozon.ru page found in the local CDP browser');
  }
  return page;
}

async function fetchInPage(cdp, endpoint, body) {
  const expression = `
    (async () => {
      const response = await fetch(${JSON.stringify(endpoint)}, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'content-type': 'application/json',
          'x-o3-company-id': ${JSON.stringify(COMPANY_ID)},
          'x-o3-app-name': 'seller-ui',
          'x-o3-language': 'ru'
        },
        body: JSON.stringify(${JSON.stringify(body)})
      });
      const text = await response.text();
      let parsed = null;
      try { parsed = JSON.parse(text); } catch (_) { parsed = { rawPrefix: text.slice(0, 300) }; }
      return { status: response.status, body: parsed };
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
}

function makePeriod(from, to) {
  return { from, to };
}

async function fetchAllItems(cdp, period) {
  const items = [];
  let offset = 0;
  let total = null;
  let firstPage = true;

  while (total === null || offset < total) {
    const response = await fetchInPage(cdp, ITEMS_ENDPOINT, {
      filter: { period, supplyPeriod: 'PERIOD_UNKNOWN' },
      limit: String(ITEMS_PAGE_SIZE),
      offset: String(offset)
    });
    if (response.status !== 200 || !response.body) {
      throw new Error(`Items endpoint HTTP ${response.status} at offset ${offset}`);
    }
    const pageItems = Array.isArray(response.body.items) ? response.body.items : [];
    total = Number(response.body.total || 0);
    items.push(...pageItems);
    if (!pageItems.length || items.length >= total) break;
    offset += pageItems.length;
    if (firstPage) firstPage = false;
  }

  return { items, total };
}

function sumItemOverpayments(items) {
  return Number(
    items
      .reduce((sum, item) => sum + Number(item?.metrics?.overpayment?.total || 0), 0)
      .toFixed(2)
  );
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
  const period = makePeriod(from, to);
  const cdpUrl = args['cdp-url'] || DEFAULT_CDP_URL;
  const page = await findOzonPage(cdpUrl);
  const cdp = new CdpClient(page.webSocketDebuggerUrl);

  try {
    const statistic = await fetchInPage(cdp, STATISTIC_ENDPOINT, {
      period,
      flags: { skuFlag: { count: 3, withTopOverpaymentSku: true } }
    });
    const output = {
      endpoint: STATISTIC_ENDPOINT,
      page: page.url,
      period,
      http_status: statistic.status,
      local_data: statistic.body && statistic.body.localData,
      overpayment: statistic.body && statistic.body.overpayment,
      overpayment_reasons: statistic.body && statistic.body.overpaymentReasons,
      top_sku: statistic.body && statistic.body.overpaymentSku,
      calculation_days: statistic.body && statistic.body.calculationDays,
      grace: statistic.body && statistic.body.grace
    };

    if (args.items) {
      const allItems = await fetchAllItems(cdp, period);
      output.items_endpoint = ITEMS_ENDPOINT;
      output.items_total = allItems.total;
      output.items_fetched = allItems.items.length;
      output.items_overpayment_sum = sumItemOverpayments(allItems.items);
      output.items_sum_matches_statistic =
        output.items_overpayment_sum === Number(output.overpayment?.total || NaN);
    }

    console.log(JSON.stringify(output, null, 2));
    if (
      statistic.status !== 200 ||
      !statistic.body ||
      !statistic.body.overpayment ||
      (args.items && !output.items_sum_matches_statistic)
    ) {
      process.exitCode = 1;
    }
  } finally {
    cdp.close();
  }
}

main().catch((error) => {
  console.error(`ERROR: ${error.message}`);
  process.exitCode = 1;
});
