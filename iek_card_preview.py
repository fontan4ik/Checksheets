"""Local, read-only IEK product-card preview for marketplace preparation.

Run with ``.venv-etm-export/bin/python iek_card_preview.py``. The server binds
only to loopback and never publishes or writes marketplace cards.
"""
from __future__ import annotations

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import iek_stock_sync_local as iek
from iek_marketplace_mapper import build_preview

HOST = "127.0.0.1"
PORT = int(os.getenv("IEK_PREVIEW_PORT", "8765"))
DEFAULT_ARTICLES = [
    "KKME11-012-230-10",
    "KKME11-018-230-10",
    "KKME11-009-230-10",
    "KKME21-025-110-10",
    "KKME31-040-230-11",
]
PAGE = """<!doctype html>
<html lang=ru><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>IEK → карточки товаров</title>
<style>
:root{font:16px/1.5 system-ui,sans-serif;color:#17202b;background:#f3f6fa}*{box-sizing:border-box}body{margin:0}header{background:#102b46;color:white;padding:28px max(20px,calc((100vw - 1120px)/2))}h1{margin:0;font-size:25px}header p{margin:6px 0 0;color:#c7d6e5}.wrap{max-width:1120px;margin:24px auto;padding:0 18px}.bar{display:flex;gap:10px;flex-wrap:wrap}.bar textarea{flex:1;min-width:260px;min-height:86px;padding:12px;border:1px solid #ccd6e1;border-radius:9px;font:inherit}button{border:0;border-radius:8px;padding:11px 18px;background:#0879d1;color:#fff;font:inherit;font-weight:650;cursor:pointer}button:disabled{opacity:.5;cursor:wait}.notice{padding:12px 14px;background:#fff5d9;border:1px solid #f0d37b;border-radius:9px;margin:16px 0}.status{margin:14px 0;color:#4e6072}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:16px}.card{background:white;border:1px solid #e0e7ee;border-radius:12px;overflow:hidden;box-shadow:0 2px 9px #183a5510}.hero{height:230px;background:#edf2f7;display:flex;align-items:center;justify-content:center}.hero img{max-width:100%;max-height:100%;object-fit:contain}.body{padding:16px}.body h2{font-size:18px;margin:0 0 4px}.muted{color:#68798b;font-size:13px}.pill{display:inline-block;margin:8px 5px 8px 0;padding:3px 9px;border-radius:20px;background:#eaf3fb;color:#185783;font-size:12px}.photos{display:flex;gap:7px;overflow:auto;margin:12px 0}.photos img{width:62px;height:62px;object-fit:cover;border:1px solid #dce4ec;border-radius:6px}.features{border-collapse:collapse;width:100%;font-size:13px}.features td{padding:5px 2px;border-top:1px solid #edf0f3;vertical-align:top}.features td:last-child{text-align:right;font-weight:600}.desc{font-size:13px;white-space:pre-wrap;color:#415366}.footer{color:#617284;font-size:12px;margin:24px 0}
</style>
<header><h1>IEK · подготовка карточек WB / Ozon</h1><p>Проверка источника и предпросмотр — без публикации в маркетплейсы</p></header>
<main class=wrap><section class=bar><textarea id=articles>KKME11-012-230-10\nKKME11-018-230-10\nKKME11-009-230-10\nKKME21-025-110-10\nKKME31-040-230-11</textarea><button id=load>Загрузить данные IEK</button></section>
<div class=notice><b>Только чтение.</b> Этот локальный инструмент показывает данные IEK. Он не создаёт карточки, не меняет кабинет и не публикует сайт. Кратность берётся из IEK без автодобавления суффикса к артикулу.</div>
<div id=status class=status>Введите артикулы и нажмите «Загрузить данные IEK».</div><section id=cards class=grid></section><p class=footer>Ключ IEK читается из Keychain на серверной стороне и не передаётся браузеру.</p></main>
<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const button=document.querySelector('#load'),status=document.querySelector('#status'),cards=document.querySelector('#cards');
button.onclick=async()=>{const articles=document.querySelector('#articles').value.split(/[\\n,;]+/).map(x=>x.trim()).filter(Boolean);cards.innerHTML='';button.disabled=true;status.textContent='Запрашиваю IEK…';try{const r=await fetch('/api/products',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({articles})});const d=await r.json();if(!r.ok)throw Error(d.error||'Ошибка API');cards.innerHTML=d.products.map(p=>{if(p.error)return `<article class=card><div class=body><h2>${esc(p.article)}</h2><p>${esc(p.error)}</p></div></article>`;const photos=p.imageUrls||[];const etim=p.etim||{};const features=etim.features||[];return `<article class=card><div class=hero>${photos[0]?`<img src="${esc(photos[0])}" alt="${esc(p.name)}" loading=lazy>`:'Фото отсутствует'}</div><div class=body><h2>${esc(p.name||p.article)}</h2><div class=muted>Артикул: ${esc(p.article)} · IEK: ${esc(p.tm||'')}</div><span class=pill>${esc(p.categoryName||'Без категории')}</span><span class=pill>Кратность: ${esc(p.multiplicity??'не указана')}</span><div class=photos>${photos.map(u=>`<a href="${esc(u)}" target=_blank rel=noopener><img src="${esc(u)}" loading=lazy></a>`).join('')}</div><table class=features>${features.map(f=>`<tr><td>${esc(f.name)}</td><td>${esc(f.value)}${f.unit?' '+esc(f.unit):''}</td></tr>`).join('')}</table><p class=desc>${esc(p.description||'Описание не предоставлено')}</p></div></article>`}).join('');status.textContent=`Ответ IEK: ${d.products.length} из ${articles.length} артикулов.`}catch(e){status.textContent='Ошибка: '+e.message}finally{button.disabled=false}};
</script></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, content: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self' https:; img-src 'self' https: data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self';")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        if urlparse(self.path).path not in ("/", "/index.html"):
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        self._send(200, PAGE.encode(), "text/html; charset=utf-8")

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/products":
            self._send(404, b'{"error":"Not found"}', "application/json")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 20_000:
                raise ValueError("Слишком большой запрос")
            data = json.loads(self.rfile.read(length))
            articles = data.get("articles")
            if not isinstance(articles, list) or not 1 <= len(articles) <= 20:
                raise ValueError("Укажите от 1 до 20 артикулов")
            articles = [str(x).strip() for x in articles]
            if any(not x or len(x) > 100 for x in articles):
                raise ValueError("Некорректный артикул")
            session = iek.create_session()
            try:
                iek.login(session, iek.get_api_key())
                products = []
                for article in articles:
                    try:
                        product = iek.request_json(session, "GET", f"{iek.BASE_URL}/api/catalog/v1/client/products/{iek.quote(article, safe='')}", allow_not_found=True)
                        if product is None:
                            products.append({"article": article, "error": "Артикул не найден в IEK"})
                        elif iek.normalize_article(product.get("article")) != iek.normalize_article(article):
                            products.append({"article": article, "error": "API вернул несовпадающий артикул"})
                        else:
                            products.append({
                                **product,
                                "marketplacePreview": build_preview(product),
                            })
                    except Exception as exc:
                        products.append({"article": article, "error": f"Не удалось загрузить: {type(exc).__name__}"})
                result = json.dumps({"products": products}, ensure_ascii=False).encode()
            finally:
                session.close()
            self._send(200, result, "application/json; charset=utf-8")
        except Exception as exc:
            result = json.dumps({"error": str(exc)}, ensure_ascii=False).encode()
            self._send(400, result, "application/json; charset=utf-8")

    def log_message(self, format: str, *args: object) -> None:
        print("%s - %s" % (self.address_string(), format % args))


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    url = f"http://{HOST}:{PORT}"
    print(f"IEK read-only preview listening at {url}")
    print("Press Ctrl+C to stop; server binds to loopback only.")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping preview server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
