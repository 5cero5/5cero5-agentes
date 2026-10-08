#!/usr/bin/env python3
"""Prueba de landing.py contra un Netlify FALSO (servidor local). Verifica la lógica y los rechazos,
no la API real: que Netlify acepte publicar un borrador con /restore sigue sin probarse."""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("MARCA_REPO", HERE.parent / "5cero5-marca"))
sha = lambda b: hashlib.sha1(b).hexdigest()

class Fake:
    def __init__(self):
        self.deploys = {"dep_old": {"files": {"/index.html": b'<html><link href="/css/viejo.css">viejo</html>', "/css/viejo.css": b"body{}", "/README.md": b"leeme"}, "state": "ready"}}
        self.raw_malo = False
        self.published = "dep_old"; self.n = 0; self.tamper = False; self.publica_en_borrador = False; self.restore_noop = False; self.lista_sin_subcarpetas = True; self.hl_tags = ["prospecto", "discovery-pendiente"]

F = Fake()

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, obj, code=200, raw=None):
        b = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def base(self): return f"http://127.0.0.1:{self.server.server_port}"
    def do_GET(self):
        p = self.path.split("?")[0]
        if p.startswith("/hl/"):
            q = dict(x.split("=", 1) for x in self.path.split("?", 1)[1].split("&")) if "?" in self.path else {}
            c = {"id": "c1", "email": "ana@ejemplo.com", "contactName": "Ana", "firstName": "Ana", "phone": "+528112345678", "companyName": "Abarrotes",
                 "tags": F.hl_tags, "customFields": [{"id": "f1", "value": "prueba"}, {"id": "f2", "value": "e2e"}, {"id": "f3", "value": "/landingtest/"}, {"id": "f4", "value": "provisional-2026-10"}]}
            if p == "/hl/contacts/": return self.send({"contacts": [c]})
            if p == "/hl/contacts/c1": return self.send({"contact": c})
            if p == "/hl/locations/loc/customFields": return self.send({"customFields": [{"id": "f1", "fieldKey": "contact.utm_source"}, {"id": "f2", "fieldKey": "contact.utm_campaign"}, {"id": "f3", "fieldKey": "contact.pagina"}, {"id": "f4", "fieldKey": "contact.aviso_version"}]})
            if p == "/hl/opportunities/pipelines": return self.send({"pipelines": [{"id": "p1", "name": "Ventas 5cero5", "stages": [{"id": "s1", "name": "Prospecto nuevo"}]}]})
            if p == "/hl/opportunities/search": return self.send({"opportunities": [{"status": "open", "pipelineId": "p1", "pipelineStageId": "s1"}]})
            return self.send({}, 404)
        if p.endswith("/.netlify/functions/prospecto"):
            did = p.split("/")[1] if not p.startswith("/live") else F.published
            ok = "prospecto" in F.deploys.get(did, {}).get("funcs", {})
            return self.send({"ok": ok, "faltan": [] if ok else ["no hay función"], "avisos": []})
        if p == "/live" or p.startswith("/live/"):
            ruta = p[5:] or "/"
            files = F.deploys[F.published]["files"]
            f = files.get(ruta) or files.get(ruta.rstrip("/") + "/index.html")
            if f is not None and ruta.endswith(".html") is False and "/" + ruta.strip("/") + "/index.html" in files:
                f = files["/" + ruta.strip("/") + "/index.html"]
            if f is None:
                return self.send({}, 404)
            self.send_response(200); self.send_header("Content-Length", str(len(f))); self.send_header("X-Robots-Tag", "noindex"); self.end_headers(); self.wfile.write(f); return
        if m := re.fullmatch(r"/api/v1/sites/(\w+)", p):
            return self.send({"id": m.group(1), "name": "poc505", "url": self.base() + "/live", "ssl_url": self.base() + "/live", "published_deploy": {"id": F.published}})
        if m := re.fullmatch(r"/api/v1/deploys/([\w]+)/files/(.+)", p):
            fs = F.deploys[m.group(1)]["files"]
            f = fs.get("/" + m.group(2)) or {k.lower(): v for k, v in fs.items()}.get("/" + m.group(2).lower())
            if f is None:
                return self.send({}, 404)
            if "raw" in self.headers.get("Accept", ""):
                return self.send(None, 200, f + (b"x" if F.raw_malo else b""))
            return self.send({"id": "/" + m.group(2), "sha": sha(f)})
        if m := re.fullmatch(r"/api/v1/deploys/([\w]+)/files", p):
            d = F.deploys[m.group(1)]
            out = [{"id": k.lower(), "sha": sha(v)} for k, v in d["files"].items() if not (F.lista_sin_subcarpetas and k.count("/") > 1)]
            if F.tamper and out: out[0]["sha"] = "0" * 40
            return self.send(out)
        if m := re.fullmatch(r"/api/v1/deploys/([\w]+)", p):
            d = F.deploys[m.group(1)]
            return self.send({"id": m.group(1), "state": d["state"], "deploy_ssl_url": self.base() + "/" + m.group(1)})
        self.send({}, 404)
    def body(self): return self.rfile.read(int(self.headers.get("Content-Length", 0)))
    def do_POST(self):
        p = self.path
        if m := re.fullmatch(r"/api/v1/sites/(\w+)/deploys", p):
            data = json.loads(self.body()); F.n += 1; did = f"dep_new{F.n}x{'a'*8}"
            F.deploys[did] = {"files": {}, "state": "uploading", "esperado": data["files"], "funcs": {}, "funcs_esperadas": data.get("functions", {})}
            if F.publica_en_borrador: F.published = did
            return self.send({"id": did, "state": "uploading", "required": sorted(set(data["files"].values())), "required_functions": sorted(set(data.get("functions", {}).values()))}, 200)
        if m := re.fullmatch(r"/api/v1/deploys/([\w]+)/restore", p):
            if not F.restore_noop: F.published = m.group(1)
            return self.send({"id": m.group(1)})
        self.send({}, 404)
    def do_PUT(self):
        mf = re.fullmatch(r"/api/v1/deploys/([\w]+)/functions/(\w+)\?runtime=js", self.path)
        if mf:
            d = F.deploys[mf.group(1)]; b = self.body()
            assert hashlib.sha256(b).hexdigest() == d["funcs_esperadas"][mf.group(2)]
            d["funcs"][mf.group(2)] = b
            return self.send({})
        m = re.fullmatch(r"/api/v1/deploys/([\w]+)/files/(.+)", self.path)
        d = F.deploys[m.group(1)]; d["files"]["/" + m.group(2)] = self.body()
        if len(d["files"]) >= len(d["esperado"]): d["state"] = "ready"
        self.send({})

srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
tmp = Path(tempfile.mkdtemp()); shutil.copy(HERE / "landing.py", tmp / "landing.py")
ENV = {**os.environ, "HL_TOKEN": "h", "HL_LOCATION_ID": "loc", "HL_API_BASE": f"http://127.0.0.1:{srv.server_port}/hl", "NETLIFY_TOKEN": "x", "NETLIFY_SITE_ID": "sitio1", "MARCA_REPO": str(REPO),
       "NETLIFY_API_BASE": f"http://127.0.0.1:{srv.server_port}/api/v1"}

def run(*args):
    r = subprocess.run([sys.executable, str(tmp / "landing.py"), *args], capture_output=True, text=True, env=ENV, cwd=tmp, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout + r.stderr

res = []
def check(nombre, cond, extra=""):
    res.append(bool(cond)); print(("✓" if cond else "✗"), nombre, ("" if cond else f"\n    {extra[-600:]}"))

def ultimo_borrador(): return json.loads((tmp / ".estado_landing.json").read_text())["borrador"]["id"]

F.raw_malo = True; c, o = run("construir", "--base-deploy", "dep_old"); check("construir rechaza un archivo base con bytes distintos a Netlify", c != 0 and "SHA1 registrado" in o, o); F.raw_malo = False
c, o = run("construir", "--base-deploy", "dep_old")
man = json.loads((tmp / ".manifiesto_landing.json").read_text()) if c == 0 else {}
check("construir arma raíz base + /landingtest y guarda manifiesto", c == 0 and "index.html" in man.get("archivos", {}) and "landingtest/index.html" in man.get("archivos", {}), o)
import zipfile as _z
_zf = tmp / "landing_funciones" / "prospecto.zip"
check("el zip de la función lleva el correo W1 verificado", _zf.exists() and sorted(_z.ZipFile(_zf).namelist()) == ["prospecto.js", "w1-entrevista.html"], o)
check("conserva un archivo base que la lista de Netlify omite (css/viejo.css)", "css/viejo.css" in man.get("archivos", {}), o)
check("con sitio base: _headers para la landing y sin robots.txt (la raíz no se toca)", "_headers" in man.get("archivos", {}) and "robots.txt" not in man.get("archivos", {}), o)
c, o = run("borrador"); check("borrador sube y verifica", c == 0 and "idéntico al manifiesto" in o, o)
check("borrador sube la función y la revisa", "↑ función prospecto" in o and "Función prospecto: responde" in o, o)
d1 = ultimo_borrador()
check("el borrador NO cambió el publicado", F.published == "dep_old")
c, o = run("promover", "--deploy", "dep_old", "--acepto-aviso-provisional", "--confirmo", "PUBLICAR dep_old"); check("rechaza un deploy que no es su borrador", c != 0 and F.published == "dep_old", o)
c, o = run("promover", "--deploy", d1, "--confirmo", f"PUBLICAR {d1[:8]}"); check("rechaza sin --acepto-aviso-provisional", c != 0 and F.published == "dep_old", o)
c, o = run("promover", "--deploy", d1, "--acepto-aviso-provisional", "--confirmo", "publicar ya"); check("rechaza frase equivocada", c != 0 and F.published == "dep_old", o)
c, o = run("promover", "--deploy", d1, "--acepto-aviso-provisional"); check("rechaza sin terminal interactiva ni --confirmo", c != 0 and F.published == "dep_old", o)
F.tamper = True; c, o = run("promover", "--deploy", d1, "--acepto-aviso-provisional", "--confirmo", f"PUBLICAR {d1[:8]}"); check("rechaza si Netlify tiene otro SHA1", c != 0 and F.published == "dep_old", o); F.tamper = False
f = tmp / "landing_dist" / "landingtest" / "estilo.css"; orig = f.read_bytes(); f.write_bytes(orig + b"\n/* x */")
c, o = run("promover", "--deploy", d1, "--acepto-aviso-provisional", "--confirmo", f"PUBLICAR {d1[:8]}"); check("rechaza si la carpeta local cambió", c != 0 and F.published == "dep_old", o); f.write_bytes(orig)
c, o = run("promover", "--deploy", d1, "--acepto-aviso-provisional", "--confirmo", f"PUBLICAR {d1[:8]}")
check("promueve y verifica la URL pública (landing en /landingtest, raíz viva)", c == 0 and F.published == d1 and "sirve este build" in o and "/landingtest/" in o, o)
check("al publicar revisa la función en la URL pública", "Función prospecto: responde" in o, o)
check("la raíz publicada sigue siendo la del sitio base", F.deploys[d1]["files"].get("/index.html", b"").startswith(b"<html><link"))
c, o = run("revertir", "--confirmo", "no"); check("revertir rechaza frase equivocada", c != 0 and F.published == d1, o)
c, o = run("revertir", "--confirmo", "REVERTIR"); check("revertir regresa al deploy anterior", c == 0 and F.published == "dep_old", o)
F.publica_en_borrador = True; c, o = run("borrador"); check("detecta si un borrador cambia el publicado", c != 0 and "PUBLICADO cambió" in o, o); F.publica_en_borrador = False; F.published = "dep_old"
c, o = run("construir"); man2 = json.loads((tmp / ".manifiesto_landing.json").read_text()) if c == 0 else {}
raiz = (tmp / "landing_dist" / "index.html").read_text() if c == 0 else ""
check("por defecto: sin sitio base, la raíz manda a /landingtest/", c == 0 and man2.get("base") == "ninguno" and 'url=/landingtest/' in raiz, o)
F.deploys["dep_choque"] = {"files": {"/landingtest/index.html": b"otro"}, "state": "ready"}
c, o = run("construir", "--base-deploy", "dep_choque"); check("rechaza una ruta que ya existe en el sitio base", c != 0 and "Elige otra ruta" in o, o)
c, o = run("construir", "--base-deploy", "dep_old")
F.restore_noop = True; c, o = run("borrador"); d2 = ultimo_borrador()
c, o = run("promover", "--deploy", d2, "--acepto-aviso-provisional", "--confirmo", f"PUBLICAR {d2[:8]}"); check("avisa si Netlify no publica", c != 0 and "no marca" in o, o)
# --- la raíz se conserva: base desde la descarga del deploy original
est = json.loads((tmp / ".estado_landing.json").read_text()); est["base_original"] = "dep_old"
(tmp / ".estado_landing.json").write_text(json.dumps(est))
c, o = run("construir"); check("sin --base-dir no deja reemplazar la raíz", c != 0 and "se conserva como está" in o, o)
bd = tmp / "descarga"; (bd / "css").mkdir(parents=True, exist_ok=True)
for k, v in F.deploys["dep_old"]["files"].items(): (bd / k.lstrip("/")).write_bytes(v)
(bd / ".DS_Store").write_bytes(b"x")
c, o = run("construir", "--base-dir", str(bd)); man3 = json.loads((tmp / ".manifiesto_landing.json").read_text()) if c == 0 else {}
hdr = (tmp / "landing_dist" / "_headers").read_text() if c == 0 else ""
check("--base-dir: raíz idéntica al deploy original + /landingtest", c == 0 and man3.get("base") == "dep_old" and man3["archivos"].get("index.html") == hashlib.sha1(F.deploys["dep_old"]["files"]["/index.html"]).hexdigest() and "landingtest/index.html" in man3["archivos"], o)
check("--base-dir: noindex solo en /landingtest y sin robots.txt", hdr.startswith("/landingtest/*") and "robots.txt" not in man3.get("archivos", {}), hdr)
(bd / "index.html").write_bytes(b"cambiado")
c, o = run("construir", "--base-dir", str(bd)); check("--base-dir rechaza un archivo distinto al original", c != 0 and "SHA1 distinto" in o, o)
(bd / "index.html").unlink()
c, o = run("construir", "--base-dir", str(bd)); check("--base-dir rechaza si falta un archivo del original", c != 0 and "Faltan" in o, o)
c, o = run("construir", "--reemplazar-raiz"); c2, o2 = run("borrador"); d3 = ultimo_borrador()
m = json.loads((tmp / ".manifiesto_landing.json").read_text()); m["reemplaza_raiz"] = False; (tmp / ".manifiesto_landing.json").write_text(json.dumps(m))
c, o = run("promover", "--deploy", d3, "--acepto-aviso-provisional", "--confirmo", f"PUBLICAR {d3[:8]}"); check("promover no publica un borrador que no conserva la raíz", c != 0 and "no conserva la raíz" in o, o)
c, o = run("lead", "--email", "Ana@Ejemplo.com", "--campana", "e2e"); check("lead: confirma en HighLevel un lead completo", c == 0 and "llegó completo" in o, o)
F.hl_tags = ["prospecto"]; c, o = run("lead", "--email", "ana@ejemplo.com"); check("lead: detecta un tag que falta", c != 0 and "incompleto" in o, o)
print(f"\n{sum(res)}/{len(res)} comprobaciones correctas."); sys.exit(0 if all(res) else 1)
