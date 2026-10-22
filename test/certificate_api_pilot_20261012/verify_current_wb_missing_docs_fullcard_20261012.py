"""Verify the accepted full-card WB update without resending any writes."""
from __future__ import annotations

import json
import argparse
from collections import Counter
from datetime import datetime, timezone

from api_client import BASE, Client, now, save
from pilot_upload import norm

PLAN = BASE / 'wb_ozon_reconciliation_fullcard_plan_20261012.json'
EXEC = BASE / 'wb_ozon_reconciliation_fullcard_execution_20261012.json'
BEFORE = BASE / 'wb_target_full_before.json'
AFTER = BASE / 'wb_target_full_after.json'
OUT = 'wb_ozon_reconciliation_fullcard_verification_20261012.json'
ERRORS = 'wb_ozon_reconciliation_fullcard_errors_20261012.json'
COMPARE_FIELDS = ('nmID', 'imtID', 'nmUUID', 'subjectID', 'subjectName', 'vendorCode', 'brand', 'title',
                  'description', 'needKiz', 'kizMarked', 'photos', 'video', 'tags', 'dimensions', 'sizes')
DOC_CHAR_IDS = {15001135, 15001136, 15001137, 15001138}


def char_signature(card: dict) -> list[tuple]:
    rows = []
    for item in card.get('characteristics') or []:
        if int(item.get('id', -1)) in DOC_CHAR_IDS:
            continue
        rows.append((int(item.get('id', -1)), item.get('name'),
                     json.dumps(item.get('value'), ensure_ascii=False, sort_keys=True)))
    return sorted(rows)


def doc_signature(doc: dict) -> tuple:
    return (int(doc.get('type', 0)), norm(doc.get('number', '')),
            str(doc.get('startDate', ''))[:10], str(doc.get('endDate', ''))[:10],
            bool(doc.get('isEndless', False)))


def error_batches(client: Client) -> list[dict]:
    result = []
    cursor = {'limit': 100}
    for _ in range(100):
        body = client.call('wb', '/content/v2/cards/error/list', {'cursor': cursor, 'order': {'ascending': True}})
        if body.get('error'):
            raise RuntimeError('WB error-list returned an API error')
        data = body.get('data') or {}
        result.extend(data.get('items') or [])
        page = data.get('cursor') or {}
        if page.get('next') is not True:
            return result
        if not page.get('updatedAt') or not page.get('batchUUID'):
            raise RuntimeError('WB error-list cursor is incomplete')
        cursor = {'limit': 100, 'updatedAt': page['updatedAt'], 'batchUUID': page['batchUUID']}
    raise RuntimeError('WB error-list exceeded 100 pages')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', default=PLAN.name)
    parser.add_argument('--execution', default=EXEC.name)
    parser.add_argument('--before', default=BEFORE.name)
    parser.add_argument('--after', default=AFTER.name)
    parser.add_argument('--out', default=OUT)
    parser.add_argument('--errors', default=ERRORS)
    args = parser.parse_args()
    plan, execution, before, after = (json.loads((BASE / name).read_text())
                                       for name in (args.plan, args.execution, args.before, args.after))
    if (execution.get('state') != 'accepted_waiting_for_wb_sync'
            or not before.get('complete') or not after.get('complete')):
        raise RuntimeError('Accepted update and complete before/after WB readbacks are required')
    expected = {row['offer_id']: row for row in plan.get('updates') or []}
    old_cards = before.get('cards_by_offer') or {}
    new_cards = after.get('cards_by_offer') or {}
    if set(old_cards) != set(expected) or set(new_cards) != set(expected):
        raise RuntimeError('Full-card snapshots do not match the exact 354-card update set')

    results = []
    item_status_counts = Counter()
    overall_counts = Counter()
    for offer, row in expected.items():
        old, live = old_cards[offer], new_cards[offer]
        if (str(live.get('nmID')) != str(row['nmID']) or live.get('vendorCode') != offer
                or str(old.get('nmID')) != str(row['nmID'])):
            raise RuntimeError(f'Live WB card identity changed: {offer}')
        changed = [field for field in COMPARE_FIELDS if old.get(field) != live.get(field)]
        if char_signature(old) != char_signature(live):
            changed.append('characteristics_other_than_document_fields')
        if changed:
            raise RuntimeError(f'Unrelated WB card fields changed for {offer}: {changed}')
        old_docs = Counter(doc_signature(x) for x in ((old.get('documents') or {}).get('items') or []))
        actual_docs = ((live.get('documents') or {}).get('items') or [])
        new_docs = Counter(doc_signature(x) for x in actual_docs)
        if any(new_docs[key] < count for key, count in old_docs.items()):
            raise RuntimeError(f'Existing WB document rows were removed for {offer}')
        exact_rows = []
        for desired in row.get('additions') or []:
            sig = doc_signature(desired)
            matches = [x for x in actual_docs if doc_signature(x) == sig]
            if len(matches) != 1:
                raise RuntimeError(f'Expected exactly one WB readback row for {desired.get("number")} on {offer}')
            verdict = matches[0].get('verdict') or {}
            state = f'{verdict.get("status", "missing")}:{verdict.get("reason", "")}'
            item_status_counts[state] += 1
            exact_rows.append({'type': matches[0].get('type'), 'number': matches[0].get('number'),
                               'startDate': matches[0].get('startDate'), 'endDate': matches[0].get('endDate'),
                               'verdict': verdict})
        documents = live.get('documents') or {}
        if documents.get('excludeDocuments') is not False:
            raise RuntimeError(f'WB still excludes documents for {offer}')
        overall = documents.get('overallVerdict') or {}
        overall_counts[f'{overall.get("status", "missing")}:{overall.get("reason", "")}'] += 1
        results.append({'offer_id': offer, 'nmID': row['nmID'], 'documents_added': len(exact_rows),
                        'preexisting_documents_preserved': True, 'unrelated_fields_preserved': True,
                        'excludeDocuments': False, 'overallVerdict': overall, 'rows': exact_rows})

    client = Client()
    batches = error_batches(client)
    save(args.errors, {'checked_at': now(), 'batches': batches})
    sent_at = datetime.fromisoformat(execution['finished_at'].replace('Z', '+00:00'))
    offers = set(expected)
    related = []
    for batch in batches:
        try:
            updated = datetime.fromisoformat(str(batch.get('updatedAt', '')).replace('Z', '+00:00'))
        except ValueError:
            continue
        errors = batch.get('errors') or {}
        overlap = offers & (set(batch.get('vendorCodes') or []) | set(errors))
        if updated >= sent_at and overlap:
            related.append({'batchUUID': batch.get('batchUUID'), 'updatedAt': batch.get('updatedAt'),
                            'target_offers': sorted(overlap),
                            'errors': {offer: errors[offer] for offer in overlap if offer in errors}})

    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'execution_finished_at': execution['finished_at'],
              'wb_after_checked_at': after['checked_at'], 'cards_checked': len(results),
              'documents_expected': sum(len(x.get('additions') or []) for x in expected.values()),
              'documents_visible': sum(len(row['rows']) for row in results),
              'preexisting_documents_preserved': True, 'unrelated_fields_preserved': True,
              'all_excludeDocuments_false': True, 'item_verdict_counts': dict(item_status_counts),
              'overall_card_verdict_counts': dict(overall_counts), 'post_update_error_batches': related,
              'error_batches_checked': len(batches), 'cards': results}
    save(args.out, report)
    print(json.dumps({k: report[k] for k in ('cards_checked', 'documents_expected', 'documents_visible',
          'preexisting_documents_preserved', 'unrelated_fields_preserved', 'all_excludeDocuments_false',
          'item_verdict_counts', 'overall_card_verdict_counts', 'post_update_error_batches',
          'error_batches_checked')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
