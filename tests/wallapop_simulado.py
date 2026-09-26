"""Servidor LOCAL que imita el formulario «Subir producto» de Wallapop.

Solo para pruebas: sirve `tests/fixtures/wallapop_simulado` en 127.0.0.1 y
guarda lo que «se publica». No se conecta a Wallapop ni a internet.
"""

from __future__ import annotations

import copy
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "fixtures" / "wallapop_simulado"


class SimulatedWallapop:
    def __init__(self) -> None:
        self.published: list[dict] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silencio
                pass

            def _send(self, code: int, body: bytes, kind: str = "text/html; charset=utf-8"):
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path == "/app/catalog/upload":
                    self._send(200, (ROOT / "app/catalog/upload.html").read_bytes())
                elif path.startswith("/item/"):
                    slug = path.rsplit("/", 1)[-1]
                    self._send(
                        200,
                        f"<!doctype html><meta charset=utf-8><title>{slug}</title>"
                        f"<h1>Producto subido</h1><p>Tu producto ya está a la venta.</p>"
                        f"<a href='/item/{slug}'>Ver anuncio</a>".encode(),
                    )
                else:
                    self._send(200, b"<!doctype html><meta charset=utf-8><h1>Inicio (simulado)</h1>")

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(length) or b"{}")
                server.published.append(data)
                item_id = f"canape-canape-{700 + len(server.published)}"
                self._send(200, json.dumps({"id": item_id}).encode(), "application/json")

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self) -> SimulatedWallapop:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def site(self, base_site):
        """Copia de la configuración real apuntando a este servidor local."""
        site = copy.deepcopy(base_site)
        site.urls = dict(site.urls)
        site.urls["inicio"] = self.base + "/"
        site.urls["subir"] = self.base + "/app/catalog/upload"
        site.urls["anuncio_regex"] = re.escape(self.base) + r"/item/[A-Za-z0-9\-_%]+"
        site.check_wait_ms = 300
        return site
