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

    def test_serves_preview_html(self):
        response = self.request("/")
        self.assertEqual(response.status, 200)
        self.assertIn("IEK · подготовка карточек".encode(), response.read())

    def test_rejects_empty_article_list(self):
        with self.assertRaises(HTTPError) as exc:
            self.request("/api/products", {"articles": []})
        self.assertEqual(exc.exception.code, 400)

    def test_read_only_fetch_returns_product_data(self):
        product = {"article": "A-1", "name": "Test", "imageUrls": [], "etim": {"features": []}}

        class FakeSession:
            def close(self):
                pass

        with patch.object(app.iek, "create_session", return_value=FakeSession()), \
             patch.object(app.iek, "login"), \
             patch.object(app.iek, "get_api_key", return_value="hidden"), \
             patch.object(app.iek, "request_json", return_value=product):
            response = self.request("/api/products", {"articles": ["A-1"]})
        result = json.loads(response.read())
        self.assertEqual(result["products"][0]["article"], "A-1")


if __name__ == "__main__":
    unittest.main()
