# VOLA-63 Sites Read-Only Heartbeat — 2026-10-08

Scope: inspect the existing Sites project and attempt read-only Ozon reconciliation for the five approved offer IDs only. No deploy, no Ozon writes, no card create/import calls.

## Sites project

- Project: `appgprj_6ac...93d8`
- Site: `IEK · Контроль каталога`
- Status: active
- Latest/live version: 6
- Deployment: succeeded
- Live URL: `https://iek-catalog-ops.fandoigor.chatgpt.site`
- MCP server: not declared on the published Site
- D1 binding: `DB`
- D1 tables visible through read-only Sites tools: `operator_events`, `operator_records`, `supplier_refresh_control`

## Runtime bindings and secrets

- Runtime env revision: 1
- Secret key present: `IEK_API_KEY` (value redacted by Sites)
- Ozon Seller keys not present in Sites env metadata: `OZON_CLIENT_ID`, `OZON_API_KEY`
- No credential values were read, copied, or written to this artifact.

## Live D1 operator records

The live `operator_records` table contains all five VOLA-63 source articles with canonical `-1` listing articles:

- `KKME11-012-230-10` -> `KKME11-012-230-10-1`
- `KKME11-018-230-10` -> `KKME11-018-230-10-1`
- `KKME11-009-230-10` -> `KKME11-009-230-10-1`
- `KKME21-025-110-10` -> `KKME21-025-110-10-1`
- `KKME31-040-230-11` -> `KKME31-040-230-11-1`

Supplier payloads are present in D1 for the five records, but row values were intentionally not copied here beyond source/listing identity.

## Ozon read-only reconciliation

Status: not performed.

Reason: the authenticated Sites tool surface can read site metadata, environment metadata, saved versions, deployments, and D1 rows, but it does not expose a read-only Ozon Seller API caller. The published Site also has no MCP server, and its runtime env metadata does not include the required Ozon Seller secrets. Because protected Ozon credentials were unavailable to a read-only native tool, product info and exact schema required fields could not be reconciled without violating the no-secret/no-network/no-write constraints.

## Next exact step

Before the Ozon read-only reconciliation can run through Sites, configure the production runtime with redacted Site secrets for `OZON_CLIENT_ID` and `OZON_API_KEY`, then provide a read-only runtime surface for Ozon checks, such as an MCP tool or diagnostic endpoint that only calls read APIs for the fixed allowlist:

- `KKME11-012-230-10-1`
- `KKME11-018-230-10-1`
- `KKME11-009-230-10-1`
- `KKME21-025-110-10-1`
- `KKME31-040-230-11-1`

The reconciliation should call only read endpoints such as product info/list and category/type/attribute metadata. Creation/import/update endpoints must remain disabled.
