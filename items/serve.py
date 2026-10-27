"""Servidor local sem cache para a pagina de itens: python items/serve.py [porta]  ->  http://localhost:8087/items/"""
import functools, http.server, os, sys, urllib.parse

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def do_POST(self):
        """POST /save?name=proc_meshes.bin: o bake.html grava o resultado em items/data (so esses dois nomes)."""
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        name = (q.get('name') or [''])[0]
        if name not in ('proc_meshes.bin', 'proc_meshes.json'):
            self.send_error(400)
            return
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        with open(os.path.join(ROOT, 'items', 'data', name), 'wb') as f:
            f.write(body)
        self.send_response(204)
        self.end_headers()


port = int(sys.argv[1]) if len(sys.argv) > 1 else 8087
print(f'http://localhost:{port}/items/')
http.server.ThreadingHTTPServer(('', port), functools.partial(Handler, directory=ROOT)).serve_forever()
