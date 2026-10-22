#!/usr/bin/env python3
"""Read-only exact ETM manufacturer-article resolution for new onboarding rows.

The FTP manufacturer label may be prefixed (SE Dekraft), while the goods API
returns the actual manufacturer (Dekraft). No manufacturer aliases are inferred.
Input JSON is a list of {offer_id, model, brand, title}; output never writes Sheets.
"""
import argparse
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote


def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().replace('ё', 'е').split())


def title_tokens(value):
    # Family terms corroborate exact manufacturer/article; digits are not fuzzy matches.
    return {word for word in re.findall(r'[a-zа-я]+', normalize(value)) if len(word) >= 5}


def validate_product(row, product):
    if not isinstance(product, dict):
        return None, 'invalid_product'
    model, brand = normalize(row.get('model')), normalize(row.get('brand'))
    if not model or not brand:
        return None, 'identity_missing'
    if normalize(product.get('gdsArt')) != model:
        return None, 'manufacturer_article_mismatch'
    external = normalize(product.get('gdsExtArt'))
    if external and external != model:
        return None, 'external_article_mismatch'
    if normalize(product.get('gdsMnfName')) != brand:
        return None, 'manufacturer_mismatch'
    if normalize(product.get('gdsUnitName')) not in {'шт', 'шт.'}:
        return None, 'supplier_unit_review'
    code = str(product.get('gdsCode', ''))
    if not re.fullmatch(r'[1-9]\d*', code):
        return None, 'invalid_etm_code'
    supplier_title = str(product.get('gdsNameTitle') or product.get('gdsNameInMnf') or '').strip()
    if not supplier_title:
        return None, 'supplier_title_missing'
    if not row.get('title') or not (title_tokens(row['title']) & title_tokens(supplier_title)):
        return None, 'title_corroboration_missing'
    return code, None


def resolve_rows(rows, lookup, pause=lambda: None):
    cache, codes, pending, evidence, seen = {}, {}, [], {}, set()
    for row in rows:
        offer = str(row.get('offer_id') or '')
        if not offer or offer in seen:
            raise ValueError('Missing or duplicate onboarding offer')
        seen.add(offer)
        if row.get('code') or row.get('etm_code'):
            pending.append({'offer_id': offer, 'reason': 'existing_code_preserved'})
            continue
        model, brand = normalize(row.get('model')), normalize(row.get('brand'))
        if not model or not brand:
            pending.append({'offer_id': offer, 'reason': 'identity_missing'})
            continue
        key = (model, brand)
        if key not in cache:
            # Failures abort the caller, which must not checkpoint a fresh source.
            cache[key] = lookup(str(row['model']))
            pause()
        product = cache[key]
        code, reason = validate_product(row, product)
        if reason:
            pending.append({'offer_id': offer, 'reason': reason, 'unitReview': reason == 'supplier_unit_review'})
            continue
        codes[offer] = code
        evidence[offer] = {field: product.get(field) for field in ['gdsCode', 'gdsArt', 'gdsExtArt', 'gdsMnfName', 'gdsMnfCode', 'gdsNameTitle', 'gdsUnitName']}
    return {'codes': codes, 'pending': pending, 'evidence': evidence, 'unique_queries': len(cache)}


def make_lookup():
    from etm_sync_multi_store import create_etm_session, login_etm
    http = create_etm_session()
    session_id, _ = login_etm(http, {})
    if not session_id:
        raise RuntimeError('ETM authentication failed')

    def lookup(model):
        for attempt in range(3):
            try:
                response = http.get('https://ipro.etm.ru/api/v1/goods/' + quote(model, safe=''),
                                    params={'type': 'mnf', 'session-id': session_id}, timeout=(10, 25))
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise RuntimeError('ETM transient HTTP failure')
                if response.status_code == 404:
                    return {}
                if response.status_code != 200:
                    raise ValueError('ETM rejected exact goods request')
                payload = response.json()
                status = payload.get('status', {}).get('code')
                if str(status) in {'404', '400'}:
                    return {}
                if str(status) != '200':
                    raise ValueError('ETM invalid exact goods response')
                return payload.get('data')
            except ValueError:
                raise
            except Exception:
                if attempt == 2:
                    raise RuntimeError('ETM exact goods lookup failed') from None
                time.sleep(2 ** attempt)
        raise RuntimeError('ETM exact goods lookup exhausted')
    return lookup


def resolve_codes(rows):
    return resolve_rows(rows, make_lookup(), pause=lambda: time.sleep(1.05))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    rows = json.loads(Path(args.input).read_text())
    if not isinstance(rows, list):
        raise ValueError('Expected onboarding row list')
    result = resolve_codes(rows)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    temporary.replace(output)
    print(json.dumps({'resolved': len(result['codes']), 'pending': len(result['pending']), 'unique_queries': result['unique_queries']}))


if __name__ == '__main__':
    main()
