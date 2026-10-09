# VOLA-67 regression review checkpoint

## Fresh price evidence (owner-provided verification-inputs rev3)

The 2026-10-09 10:11:19 UTC `POST /v5/product/info/prices` read confirms both seller `price` and `marketing_seller_price` at 340 / 340 / 340 / 377 / 433 RUB for 9A / 12A / 18A / 25A / 40A, VAT 0.22. These are seller prices, not buyer-discount prices. Owner policy is seller price = IEK API RRC. The actor/source of the price change is unknown; do not attribute it. No marketplace write was made.

## Reviewer findings checked against checkout

VOLA-68's independent offline report documents nine reproduced failures. Current code inspection confirms unresolved defects in `worker/index.js` (false completion without product readback, empty required attribute values accepted, lost task receipt window, no durable atomic process claim) and `src/article-import.js` (30-attempt stop, no start guard, reload restores state without resuming, retry only shown for failed rows). The current source workspace is dirty and must be preserved; HEAD is `52e99ba76ae4c0ce93d04672791d9b809745e835`.

## Tests

`node --test test/*.test.mjs` passed 4/4 on this checkout. Independent review confirms these existing tests do not cover the nine regressions. No fix is claimed from that pass.

## Official Sites source-open attempt

Used supported `codex exec --ephemeral --json --sandbox workspace-write -C <registered Site checkout> -c approval_policy="never" -c sandbox_workspace_write.network_access=true`, requested fresh native source credential with `publish_on_push: null`, and started the bundled Site workflow in a fresh PTY. Native PTY reached the official hidden-input Ready prompt. Native `write_stdin` was then rejected with exact error: `write_stdin rejected: approval required by policy, but AskForApproval is set to Never`.

No credential was sent to the workflow, it did not open source, and no source changes/deploy/publish occurred from this attempt. Do not retry around this rejection. The issue remains blocked pending a supported authorized input path for the CLI PTY.

Visual UI remains unverified by explicit owner browser-security restriction. Certificates and product documents remain excluded from acceptance scope.