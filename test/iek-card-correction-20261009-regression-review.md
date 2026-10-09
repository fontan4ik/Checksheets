# VOLA-67 source checkpoint

Reviewed using independent reviewer findings (VOLA-68) and latest owner verification-inputs rev3.

## Price facts

The owner-reported fresh `POST /v5/product/info/prices` response at 2026-10-09 10:11:19 UTC confirms seller `price` and `marketing_seller_price` at 340/340/340/377/433 RUB for 9A/12A/18A/25A/40A, VAT 0.22. These are not buyer-discount prices. The owner policy is seller price = RRC from IEK API. The actor/source of the current-price change is unknown; no attribution is made and no marketplace price write was attempted.

## Independent regressions checked in source

VOLA-68's offline report reproduces nine defects. Source inspection confirms several remain in the current uncommitted worktree:

- `worker/index.js:520-524`: `status === imported` plus product ID yields complete without product detail, images, prices, or attribute readback.
- `worker/index.js:549-557`: an existing product ID yields complete after only product-info lookup and required-schema presence check.
- `worker/index.js:427-432`: required attributes are considered satisfied by attribute ID alone, regardless of empty `values`.
- `worker/index.js:285-316`: brand has a fallback `IEK`, dimensions/weight are converted without persisted source units; only partial product payload fields are emitted.
- `worker/index.js:569-579`: provider create occurs before task ID persistence by the caller, so a DB failure can lose receipt and permit resubmission.
- `worker/index.js:674 onward`: processing path must be reworked to claim rows atomically before external effects; reviewer fixture showed duplicate concurrent provider submissions.
- `src/article-import.js:45-53,75-89`: 30-attempt driver exit can strand queued work; no double-click guard and retry only appears for failed rows; restoring previous run only renders state.

## Current source validation status

- `node --test test/*.test.mjs`: 4 tests passed in this run.
- Passing tests do not cover the independent regression cases; no fix is claimed.
- Source open/publish workflow must be run using official Sites connector. A previous attempt with `approval_policy=never` failed specifically on `write_stdin` requiring approval; that did not establish a broader CLI blocker. Retry path is explicitly authorized by owner: fresh PTY, workspace-write sandbox rooted at the registered Site checkout, network access enabled only for supported git workflow, approval_policy never, fresh credential in memory/stdin only, publish_on_push disabled.
- Live Site UI visual check remains intentionally unverified under owner security boundary. No attempt to bypass it.

## Remains

Do not edit prices/brand on provider without fresh source→expected→submitted preview. Preserve the existing product IDs; do not create SKUs, activate sales, or alter stock/documents/certificates. Implement and test same-ID readback/validation, durable import claim and task receipt handling, unit-aware packaging conversion and truthful UI resume. Then use authorized Sites source open, reconcile without discarding shared changes, build/test, and publish this existing Site through the official mechanism. Capture version/deployment IDs and provider readback; ask for human acceptance only against the current revision.