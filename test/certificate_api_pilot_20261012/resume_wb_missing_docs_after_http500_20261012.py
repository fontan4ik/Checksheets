"""Continue WB updates only after proving which rows survived HTTP 500 responses."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from api_client import BASE, Client, now, save
from pilot_upload import norm

SOURCE_PLAN = BASE / 'wb_ozon_reconciliation_fullcard_plan_ozon_missing_retry_20261012.json'
FIRST_READBACK = BASE / 'wb_ozon_missing_chunk1_readback_20261012.json'
PLAN_NAME = 'wb_ozon_reconciliation_fullcard_plan_ozon_missing_residual_20261012.json'
RUN_NAME = 'wb_ozon_reconciliation_fullcard_execution_ozon_missing_residual_20261012.json'
COMPARE_FIELDS = ('nmID', 'imtID', 'nmUUID', 'subjectID', 'subjectName', 'vendorCode', 'brand', 'title',
                  'description', 'needKiz', 'kizMarked', 'photos', 'video', 'tags', 'dimensions', 'sizes')
DOC_CHAR_IDS = {15001135, 15001136, 15001137, 15001138}


def signature(item: dict) -> tuple:
    return (int(item.get('type', 0)), norm(item.get('number', '')),
            str(item.get('startDate', ''))[:10], str(item.get('endDate', ''))[:10],
            bool(item.get('isEndless', False)))


def char_signature(card: dict) -> list[tuple]:
    return sorted((int(x.get('id', -1)), x.get('name'),
                   json.dumps(x.get('value'), ensure_ascii=False, sort_keys=True))
                  for x in card.get('characteristics') or [] if int(x.get('id', -1)) not in DOC_CHAR_IDS)


def build_residual() -> dict:
    source = json.loads(SOURCE_PLAN.read_text())
    checked = json.loads(FIRST_READBACK.read_text())
    if (checked.get('cards_checked') != 50 or checked.get('documents_expected') != 50
            or checked.get('documents_visible') != 50 or checked.get('missing_rows')
            or checked.get('unrelated_field_changes') or checked.get('preexisting_rows_removed')):
        raise RuntimeError('The first failed chunk is not fully reconciled; inspect it before continuing')
    applied = {x['offer_id'] for x in checked.get('cards') or []}
    updates = [x for x in source.get('updates') or [] if x['offer_id'] not in applied]
    if len(updates) != 389:
        raise RuntimeError(f'Expected 389 unapplied cards after exact 50-card readback, found {len(updates)}')
    payloads = [x['payload'] for x in updates]
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(',', ':')).encode()
    result = {**source, 'created_at': now(), 'source_plan': SOURCE_PLAN.name,
              'source_plan_sha256': hashlib.sha256(SOURCE_PLAN.read_bytes()).hexdigest(),
              'first_failed_chunk_readback': FIRST_READBACK.name,
              'previously_applied_card_count': len(applied), 'updates': updates,
              'counts': {**source['counts'], 'source_candidates': len(updates),
                         'cards_to_update': len(updates),
                         'documents_to_add': sum(len(x.get('additions') or []) for x in updates),
                         'request_bytes': len(encoded),
                         'request_sha256': hashlib.sha256(encoded).hexdigest()}}
    save(PLAN_NAME, result)
    return result


def reconcile_chunk(client: Client, chunk: list[dict]) -> tuple[dict, list[dict]]:
    visible = []
    problems = []
    for row in chunk:
        offer = row['offer_id']
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            problems.append({'offer_id': offer, 'reason': 'missing_or_duplicate_card', 'card_count': len(cards)})
            continue
        live = cards[0]
        if str(live.get('nmID')) != str(row['nmID']) or live.get('vendorCode') != offer:
            problems.append({'offer_id': offer, 'reason': 'identity_changed'})
            continue
        before = row.get('before') or {}
        changed = [field for field in COMPARE_FIELDS if before.get(field) != live.get(field)]
        if char_signature(before) != char_signature(live):
            changed.append('non_document_characteristics')
        if changed:
            problems.append({'offer_id': offer, 'reason': 'unrelated_fields_changed', 'fields': changed})
        before_docs = Counter(signature(x) for x in ((before.get('documents') or {}).get('items') or []))
        documents = ((live.get('documents') or {}).get('items') or [])
        after_docs = Counter(signature(x) for x in documents)
        if any(after_docs[key] < count for key, count in before_docs.items()):
            problems.append({'offer_id': offer, 'reason': 'preexisting_document_removed'})
        exact_rows = []
        for desired in row.get('additions') or []:
            matches = [x for x in documents if signature(x) == signature(desired)]
            if len(matches) > 1:
                problems.append({'offer_id': offer, 'number': desired['number'], 'reason': 'duplicate_document_row'})
            elif len(matches) == 1:
                exact_rows.append(matches[0])
            else:
                same_number = [x for x in documents if norm(x.get('number', '')) == norm(desired['number'])]
                if same_number:
                    problems.append({'offer_id': offer, 'number': desired['number'],
                                     'reason': 'new_number_or_date_conflict'})
        if len(exact_rows) == len(row.get('additions') or []):
            visible.append({'offer_id': offer, 'nmID': live['nmID'], 'rows': exact_rows,
                            'overallVerdict': (live.get('documents') or {}).get('overallVerdict')})
        else:
            problems.append({'offer_id': offer, 'reason': 'one_or_more_rows_not_visible',
                             'visible_rows': len(exact_rows), 'expected_rows': len(row.get('additions') or [])})
    return {'cards_checked': len(chunk), 'documents_expected': sum(len(x.get('additions') or []) for x in chunk),
            'documents_visible': sum(len(x['rows']) for x in visible), 'cards': visible,
            'problems': problems, 'checked_at': now()}, problems


def execute(plan: dict, chunk_size: int) -> None:
    if (BASE / RUN_NAME).exists():
        raise RuntimeError('Residual WB retry already has a run marker; reconcile it before proceeding')
    if not 1 <= chunk_size <= 100:
        raise RuntimeError('Use a chunk size from 1 to 100 cards')
    run = {'started_at': now(), 'state': 'prepared', 'cards': len(plan['updates']),
           'documents': sum(len(x.get('additions') or []) for x in plan['updates']),
           'request_bytes': plan['counts']['request_bytes'], 'request_sha256': plan['counts']['request_sha256'],
           'previously_applied_card_count': plan['previously_applied_card_count'],
           'chunk_size': chunk_size, 'chunks': []}
    save(RUN_NAME, run)
    client = Client()
    updates = plan['updates']
    for start in range(0, len(updates), chunk_size):
        chunk = updates[start:start + chunk_size]
        payloads = [x['payload'] for x in chunk]
        body = json.dumps(payloads, ensure_ascii=False, separators=(',', ':')).encode()
        entry = {'index': len(run['chunks']) + 1, 'cards': len(chunk),
                 'documents': sum(len(x.get('additions') or []) for x in chunk),
                 'request_bytes': len(body), 'request_sha256': hashlib.sha256(body).hexdigest(),
                 'offers': [x['offer_id'] for x in chunk], 'phase': 'prepared', 'prepared_at': now()}
        run['chunks'].append(entry)
        save(RUN_NAME, run)
        try:
            response = client.call('wb', '/content/v2/cards/update', payloads, mutation=True)
        except Exception as exc:
            entry.update({'phase': 'uncertain_or_error', 'error_type': type(exc).__name__,
                          'error': str(exc)[:300], 'readback_started_at': now()})
            save(RUN_NAME, run)
            # Only an explicit HTTP 500 gets immediate readback and safe continuation.
            # Network-level uncertainty always stops without an automatic retry.
            if 'HTTP 500' not in str(exc):
                run.update({'state': 'network_uncertain_stop', 'finished_at': now()})
                save(RUN_NAME, run)
                raise RuntimeError('WB request outcome is uncertain; stopped without retry') from None
            readback, problems = reconcile_chunk(client, chunk)
            entry['readback'] = readback
            if problems:
                entry.update({'phase': 'http500_readback_incomplete', 'problems': problems})
                run.update({'state': 'http500_readback_incomplete_stop', 'finished_at': now()})
                save(RUN_NAME, run)
                raise RuntimeError('HTTP 500 chunk has missing/conflicted rows; stopped after fresh readback') from None
            entry.update({'phase': 'http500_but_rows_confirmed_live', 'reconciled_at': now()})
            save(RUN_NAME, run)
            continue
        entry.update({'phase': 'accepted' if response.get('error') is False else 'response_error',
                      'response': response, 'finished_at': now()})
        save(RUN_NAME, run)
        if response.get('error') is not False:
            readback, problems = reconcile_chunk(client, chunk)
            entry['readback'] = readback
            if problems:
                entry.update({'phase': 'response_error_readback_incomplete', 'problems': problems})
                run.update({'state': 'response_error_stop', 'finished_at': now()})
                save(RUN_NAME, run)
                raise RuntimeError('WB returned an error and fresh readback is incomplete')
            entry['phase'] = 'response_error_but_rows_confirmed_live'
            save(RUN_NAME, run)
    run.update({'state': 'all_chunks_accepted_or_confirmed_live', 'finished_at': now()})
    save(RUN_NAME, run)
    print(json.dumps({'state': run['state'], 'cards': run['cards'], 'documents': run['documents'],
                      'chunks': len(run['chunks']),
                      'chunks_confirmed_after_http500': sum(x['phase'] == 'http500_but_rows_confirmed_live' for x in run['chunks']),
                      'finished_at': run['finished_at']}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--chunk-size', type=int, default=50)
    args = parser.parse_args()
    plan = build_residual()
    print(json.dumps({'residual_cards': plan['counts']['cards_to_update'],
                      'residual_documents': plan['counts']['documents_to_add'],
                      'already_applied_cards': plan['previously_applied_card_count'],
                      'plan': PLAN_NAME}, ensure_ascii=False))
    if args.execute:
        execute(plan, args.chunk_size)


if __name__ == '__main__':
    main()
