"""Transport regressions against a loopback server with an explicitly fake key."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from knowledge_agent.config import Settings
from knowledge_agent.model import LiveModel, ModelError


class ModelTransportTests(unittest.TestCase):
    def test_http_redirect_is_rejected_without_visiting_target(self):
        visited = []
        fake_key = "fake-key-for-loopback-test-only"

        class RedirectHandler(BaseHTTPRequestHandler):
            def handle_request(self):
                visited.append((self.path, self.headers.get("Authorization")))
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                if self.path == "/chat/completions":
                    self.send_response(302)
                    self.send_header("Location", "/leak")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                payload = json.dumps({"choices": [{"message": {
                    "role": "assistant", "content": "unexpected redirected response"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_POST = handle_request
            do_GET = handle_request

            def log_message(self, format, *arguments):
                pass

        server = HTTPServer(("127.0.0.1", 0), RedirectHandler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        try:
            settings = Settings(api_key=fake_key, base_url=f"http://127.0.0.1:{server.server_port}",
                                model="loopback-test-model", timeout=2)
            model = LiveModel(settings)
            with self.assertRaises(ModelError) as raised:
                model.complete([{"role": "user", "content": "offline transport test"}], [])
            self.assertEqual(raised.exception.kind, "redirect_rejected")
            self.assertEqual(raised.exception.status_code, 302)
            self.assertEqual(visited, [("/chat/completions", "Bearer " + fake_key)])
            self.assertNotIn(fake_key, str(raised.exception))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_settings_repr_omits_api_key_without_loading_environment(self):
        fake_key = "fake-secret-must-not-appear-in-repr"
        settings = Settings(api_key=fake_key)
        self.assertNotIn(fake_key, repr(settings))
        self.assertNotIn("api_key", repr(settings))


if __name__ == "__main__":
    unittest.main()
