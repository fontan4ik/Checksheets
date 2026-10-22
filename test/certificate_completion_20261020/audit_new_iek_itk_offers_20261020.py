"""Read-only crosswalk for new Ozon IEK/ITK offers to official maker product certificates."""
from __future__ import annotations
import concurrent.futures, json, re, time
from collections import defaultdict, Counter
from pathlib import Path
from urllib.parse import quote
import requests

HERE=Path(__file__).resolve().parent
SNAP=json.loads((HERE/'live_marketplaces_snapshot.json').read_text())
PREV=json.loads((HERE.parent/'certificate_completion_20261019'/'live_marketplaces_snapshot.json').read_text())
old={p['offer_id'] for p in PREV['ozon_products']['products']}
new=[p for p in SNAP['ozon_products']['products'] if p['offer_id'] not in old and (p.get('brand_values') or [''])[0].strip().casefold() in ('iek','itk')]
by_article=defaultdict(list)
for p in new: by_article[p['offer_id']].append(p)

session=requests.Session()
HEADERS={'User-Agent':'Mozilla/5.0 (compatible; certification-audit/1.0)'}
def nextdata(html):
 m=re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',html,re.S)
 if not m: raise ValueError('missing Next data')
 return json.loads(m.group(1)).get('props',{}).get('pageProps',{})
def get(url):
 r=requests.get(url,headers=HEADERS,timeout=30); r.raise_for_status(); return r.text

def lookup(article):
 probes=[article]
 # Seller pack variants are encoded as a terminal pack count; only strip known pack sizes.
 if re.search(r'-(?:1|2|3|5|10)$',article):
  base=re.sub(r'-(?:1|2|3|5|10)$','',article)
  if base!=article: probes.append(base)
 errors=[]
 for q in probes:
  try:
   page=nextdata(get('https://www.iek.ru/products/catalog/search?q='+quote(q,safe='')))
   results=(page.get('apiListing') or {}).get('products') or []
   exact=[x for x in results if str(x.get('article','')).casefold()==article.casefold()]
   if not exact and q!=article:
    exact=[x for x in results if str(x.get('article','')).casefold()==q.casefold()]
   if not exact: continue
   # When exact seller article appears as a search hit, preserve that product identity.
   item=exact[0]
   product_url='https://www.iek.ru/products/catalog'+item.get('url','')
   pp=nextdata(get(product_url))
   product=pp.get('apiProduct') or {}
   return {'offer_id':article,'product_article':item.get('article'),'product_url':product_url,
    'search_query':q,'search_item':item,'product':product}
  except Exception as e: errors.append(type(e).__name__)
 return {'offer_id':article,'error_types':errors or ['exact_official_product_not_found']}

# Query unique article ids to reduce requests. Four concurrent workers, all GET-only.
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 results=list(pool.map(lookup,by_article))

for row in results:
 if 'product' in row:
  prod=row['product']
  row['offer_ids']=[p['offer_id'] for p in by_article[row['offer_id']]]
  row['offer_product_ids']=[p['product_id'] for p in by_article[row['offer_id']]]
  row['offer_skus']=[p['sku'] for p in by_article[row['offer_id']]]
  row['offer_tnved_values']=[p['tnved_values'] for p in by_article[row['offer_id']]]
  row['official_name']=prod.get('name')
  row['official_brand']=prod.get('tm')
  row['official_product_flags']={k:prod.get(k) for k in ('isArchived','isOutOfAssortment','isOutOfProduction','firstSaleDate','feacn','countryOfProduction')}
  row['certificates']=prod.get('certificates') or []
  row['certificate_summary']=[{k:c.get(k) for k in ('type','number','dateStart','dateEnd','pubName','issuer','url')} for c in row['certificates']]
  # Do not persist the full HTML-derived product payload or assets.
  del row['product']

out=HERE/'new_iek_itk_official_crosswalk_20261020.json'
out.write_text(json.dumps({'checked_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'new_offer_count':len(new),'unique_article_count':len(by_article),'matched_products':sum('product_url' in x for x in results),'unmatched':sum('product_url' not in x for x in results),'results':results},ensure_ascii=False,indent=2))
print(json.dumps({'new_offers':len(new),'unique_articles':len(by_article),'matched_products':sum('product_url' in x for x in results),'unmatched':sum('product_url' not in x for x in results),'brands':dict(Counter((p.get('brand_values') or [''])[0] for p in new)),'out':str(out)},ensure_ascii=False))
