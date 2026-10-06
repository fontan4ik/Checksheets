import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import iek_card_preview as app


class PreviewServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(self.base + path, data=data, headers={"Content-Type": "application/json"})
        return urlopen(req)

    def test_serves_preview_html_with_marketplace_readiness(self):
        response = self.request("/")
        self.assertEqual(response.status, 200)
        page = response.read().decode()
        self.assertIn("IEK · подготовка карточек", page)
        self.assertIn("Проверка WB / Ozon", page)
        self.assertIn("sourceMultiplicity", page)

    def test_rejects_empty_article_list(self):
        with self.assertRaises(HTTPError) as exc:
            self.request("/api/products", {"articles": []})
        self.assertEqual(exc.exception.code, 400)

    def test_read_only_fetch_returns_mapped_product_and_multiplicity(self):
        product = {
            "article": "A-1",
            "name": "Test",
            "imageUrls": [],
            "etim": {"features": []},
            "multiplicity": 1,
        }

        class FakeSession:
            def close(self):
                pass

        with patch.object(app.iek, "create_session", return_value=FakeSession()), \
             patch.object(app.iek, "login"), \
             patch.object(app.iek, "get_api_key", return_value="hidden"), \
             patch.object(app.iek, "request_json", return_value=product):
            response = self.request("/api/products", {"articles": ["A-1"]})
        result = json.loads(response.read())
        item = result["products"][0]
        self.assertEqual(item["article"], "A-1")
        self.assertEqual(item["sourceMultiplicity"], 1)
        self.assertEqual(item["marketplacePreview"]["article"], "A-1")
        self.assertFalse(item["marketplacePreview"]["publishable"])


if __name__ == "__main__":
    unittest.main()
