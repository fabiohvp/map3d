"""Servidor local sem cache para a pagina de itens: python items/serve.py [porta]  ->  http://localhost:8087/items/"""
import functools, http.server, os, sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


port = int(sys.argv[1]) if len(sys.argv) > 1 else 8087
print(f'http://localhost:{port}/items/')
http.server.ThreadingHTTPServer(('', port), functools.partial(Handler, directory=ROOT)).serve_forever()
