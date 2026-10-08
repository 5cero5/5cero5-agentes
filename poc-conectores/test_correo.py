#!/usr/bin/env python3
"""correo.py contra un HighLevel FALSO: crea, actualiza, comprueba y rechaza. No prueba la API real."""
import json, os, re, shutil, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ["MARCA_REPO"])
T = {}; ESTADO = {"altera": False, "creados": 0, "datos": 0}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, o, code=200, raw=None):
        b = raw if raw is not None else json.dumps(o).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/emails/builder":
            return self.send({"builders": [{"id": k, "name": v["name"], "previewUrl": f"http://127.0.0.1:{self.server.server_port}/preview/{k}"} for k, v in T.items()]})
        if p.startswith("/preview/"):
            h = T[p.split("/")[-1]].get("html", "")
            if ESTADO["altera"]: h = h.replace("Empieza la entrevista", "Otro texto").replace("utm_campaign", "x")
            return self.send(None, 200, h.encode())
        self.send({}, 404)
    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Authorization") != "Bearer pit-x": return self.send({}, 401)
        if self.path == "/emails/builder":
            ESTADO["creados"] += 1; k = f"t{ESTADO['creados']}"; T[k] = {"name": b["title"]}; return self.send({"redirect": k})
        if self.path == "/emails/builder/data":
            ESTADO["datos"] += 1; T[b["templateId"]]["html"] = b["html"]; return self.send({"ok": True})
        self.send({}, 404)

srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
ENV = {**os.environ, "HL_TOKEN": "pit-x", "HL_LOCATION_ID": "loc", "HL_API_BASE": f"http://127.0.0.1:{srv.server_port}"}
tmp = Path(tempfile.mkdtemp()); shutil.copy(REPO / "correos" / "w1-entrevista.json", tmp / "w1.json")
run = lambda *a, env=ENV: subprocess.run([sys.executable, str(HERE / "correo.py"), *a], capture_output=True, text=True, env=env)
res = []
def check(n, c, o=""): res.append(bool(c)); print(("✓" if c else "✗"), n, "" if c else o[-500:])

o = run("armar", "--copia", str(tmp / "w1.json")); check("armar desde la copia JSON", o.returncode == 0 and (tmp / "w1.html").exists(), o.stdout + o.stderr)
o = run("subir", "--html", str(tmp / "w1.html"), "--nombre", "W1 · Entrada"); check("subir crea la plantilla y la comprueba", o.returncode == 0 and ESTADO["creados"] == 1 and "con el botón y todas las frases" in o.stdout, o.stdout + o.stderr)
o = run("subir", "--html", str(tmp / "w1.html"), "--nombre", "W1 · Entrada"); check("subir de nuevo actualiza, no duplica", o.returncode == 0 and ESTADO["creados"] == 1 and ESTADO["datos"] == 2, o.stdout)
mala = (tmp / "w1.html").read_text().replace("Con tus respuestas preparamos tu llamada con Al.", "Te garantizamos más ventas!"); (tmp / "malo.html").write_text(mala)
o = run("subir", "--html", str(tmp / "malo.html"), "--nombre", "W1 · Entrada"); check("no sube un correo que el Verificador rechaza", o.returncode != 0 and ESTADO["datos"] == 2, o.stdout)
ESTADO["altera"] = True; o = run("comprobar", "--html", str(tmp / "w1.html"), "--nombre", "W1 · Entrada"); check("comprobar detecta si HighLevel cambió el contenido", o.returncode != 0 and "no trae" in o.stdout, o.stdout); ESTADO["altera"] = False
o = run("subir", "--html", str(tmp / "w1.html"), "--nombre", "W2", env={**ENV, "HL_TOKEN": "otro"}); check("token inválido: mensaje claro", o.returncode != 0 and "401" in o.stdout, o.stdout)
print(f"\n{sum(res)}/{len(res)} comprobaciones correctas."); sys.exit(0 if all(res) else 1)
