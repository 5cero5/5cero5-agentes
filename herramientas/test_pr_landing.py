#!/usr/bin/env python3
"""Prueba de pr_landing.py contra un GitHub FALSO (servidor local) y copias de los repos de marca y de landings.

  MARCA_REPO=../../5cero5-marca LANDINGS_REPO=../../5cero5-landings python3 test_pr_landing.py

Necesita Playwright con Chromium (el Verificador de marca revisa en navegador) y node (build del repo de landings)."""
import base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARCA = Path(os.environ.get("MARCA_REPO", HERE.parent.parent / "5cero5-marca")).resolve()
LANDINGS = Path(os.environ.get("LANDINGS_REPO", HERE.parent.parent / "5cero5-landings")).resolve()
blob_sha = lambda b: hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


class GH:
    """Lo mínimo de la API de Git de GitHub: main apunta a un commit con el árbol del repo de landings."""
    def __init__(self):
        self.blobs, self.trees, self.commits, self.refs, self.prs, self.llamadas = {}, {}, {}, {}, [], []
        arbol = []
        for p in sorted(LANDINGS.rglob("*")):
            rel = p.relative_to(LANDINGS).as_posix()
            if p.is_file() and not rel.startswith((".git/", "sitio/", "node_modules/")) and not rel.endswith("generado.js"):
                b = p.read_bytes(); s = blob_sha(b); self.blobs[s] = b
                arbol.append({"path": rel, "mode": "100644", "type": "blob", "sha": s})
        self.trees["t0"] = arbol; self.commits["c0"] = {"tree": "t0", "parents": []}; self.refs["refs/heads/main"] = "c0"
        self.n = 0

    def nuevo(self, pref):
        self.n += 1; return f"{pref}{self.n}"


G = GH()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, obj, code=200):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def auth_ok(self):
        if self.headers.get("Authorization") != "Bearer ghs_prueba":
            self.send({"message": "Bad credentials"}, 401); return False
        return True

    def do_GET(self):
        G.llamadas.append(("GET", self.path))
        if not self.auth_ok(): return
        p = self.path.split("?")[0]
        if m := re.fullmatch(r"/repos/5cero5/5cero5-landings/git/ref/heads/(.+)", p):
            r = G.refs.get("refs/heads/" + m.group(1)); return self.send({"object": {"sha": r}}) if r else self.send({}, 404)
        if m := re.fullmatch(r"/repos/5cero5/5cero5-landings/git/commits/(\w+)", p):
            return self.send({"sha": m.group(1), "tree": {"sha": G.commits[m.group(1)]["tree"]}})
        if m := re.fullmatch(r"/repos/5cero5/5cero5-landings/git/trees/(\w+)", p):
            return self.send({"sha": m.group(1), "tree": G.trees[m.group(1)]})
        self.send({}, 404)

    def do_POST(self):
        G.llamadas.append(("POST", self.path))
        if not self.auth_ok(): return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        p = self.path
        if p.endswith("/git/blobs"):
            b = base64.b64decode(body["content"]); s = blob_sha(b); G.blobs[s] = b; return self.send({"sha": s}, 201)
        if p.endswith("/git/trees"):
            base = {e["path"]: e for e in G.trees[body["base_tree"]]}
            for e in body["tree"]:
                if e["sha"] is None: base.pop(e["path"], None)
                else: base[e["path"]] = e
            t = G.nuevo("t"); G.trees[t] = list(base.values()); G.ultimo_arbol = body["tree"]; return self.send({"sha": t}, 201)
        if p.endswith("/git/commits"):
            c = G.nuevo("c"); G.commits[c] = {"tree": body["tree"], "parents": body["parents"], "message": body["message"]}; return self.send({"sha": c}, 201)
        if p.endswith("/git/refs"):
            G.refs[body["ref"]] = body["sha"]; return self.send({"ref": body["ref"]}, 201)
        if p.endswith("/pulls"):
            n = len(G.prs) + 1; G.prs.append(body); return self.send({"number": n, "html_url": f"https://github.com/5cero5/5cero5-landings/pull/{n}"}, 201)
        self.send({}, 404)

    def do_PUT(self):  # merge u otra escritura: nunca debe llegar aquí
        G.llamadas.append(("PUT", self.path)); self.send({"message": "no"}, 405)

    do_PATCH = do_PUT
    do_DELETE = do_PUT


srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
tmp = Path(tempfile.mkdtemp())
shutil.copytree(MARCA, tmp / "marca", ignore=shutil.ignore_patterns(".git"))
shutil.copytree(LANDINGS, tmp / "landings", ignore=shutil.ignore_patterns(".git", "sitio", "node_modules"))
ENV = {**os.environ, "GITHUB_TOKEN": "ghs_prueba", "GITHUB_API_BASE": f"http://127.0.0.1:{srv.server_port}"}
res = []


def run(*args, env=None):
    r = subprocess.run([sys.executable, str(HERE / "pr_landing.py"), "--landings", str(tmp / "landings"), "--marca", str(tmp / "marca"), *args],
                       capture_output=True, text=True, env=env or ENV, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout + r.stderr


def check(nombre, cond, extra=""):
    res.append(bool(cond)); print(("✓" if cond else "✗"), nombre, ("" if cond else f"\n    {extra[-700:]}"))


def ultimo_json(o):
    for linea in reversed(o.strip().splitlines()):
        try: return json.loads(linea)
        except ValueError: continue
    return {}


c, o = run("nueva", "--slug", "../fuera", "--nombre", "x"); check("rechaza un slug que sale de landings/", c != 0 and "Slug inválido" in o, o)
c, o = run("nueva", "--slug", "assets", "--nombre", "x"); check("rechaza un slug reservado", c != 0 and "Slug inválido" in o, o)
c, o = run("nueva", "--slug", "diagnostico", "--nombre", "x"); check("nueva no pisa una landing que ya existe", c != 0 and "Ya existe" in o, o)
c, o = run("nueva", "--slug", "buen-fin", "--nombre", "Buen Fin 2026")
L = json.loads((tmp / "landings/landings/buen-fin/landing.json").read_text()) if c == 0 else {}
html = (tmp / "landings/landings/buen-fin/index.html").read_text() if c == 0 else ""
check("nueva arma la carpeta desde la plantilla de marca con su landing.json", c == 0 and L.get("tags_siempre") == ["buen-fin"] and 'value="/buen-fin/"' in html and "/buen-fin/estilo.css" in html, o)
c, o = run("abrir", "--slug", "buen-fin", "--titulo", "sin revisar"); check("abrir se niega si no se revisó", c != 0 and "revisar" in o and not G.prs, o)
c, o = run("revisar", "--slug", "buen-fin"); check("revisar: build del repo y Verificador de marca aprueban la landing nueva", c == 0 and "revisada" in o, o)
f = tmp / "landings/landings/buen-fin/index.html"; f.write_text(f.read_text().replace("</h1>", " ya</h1>", 1))
c, o = run("abrir", "--slug", "buen-fin", "--titulo", "cambiada"); check("abrir se niega si la carpeta cambió después de revisar", c != 0 and "cambió" in o and not G.prs, o)
c, o = run("revisar", "--slug", "buen-fin"); c2, o2 = run("abrir", "--slug", "buen-fin", "--titulo", "Promo de Buen Fin", "--cuerpo", "Brief: promo.")
out = ultimo_json(o2)
check("abrir crea rama agente/, commit sobre main y PR a main", c2 == 0 and out.get("rama", "").startswith("agente/buen-fin-") and out.get("pr_numero") == 1
      and G.prs[0]["base"] == "main" and G.prs[0]["head"] == out["rama"] and G.refs.get("refs/heads/" + out["rama"]) == out["commit"], o + o2)
check("el PR solo trae archivos de landings/buen-fin/", out.get("archivos") and all(a.startswith("landings/buen-fin/") for a in out["archivos"])
      and all(e["path"].startswith("landings/buen-fin/") for e in G.ultimo_arbol), json.dumps(out))
check("main no se movió y nada intentó fusionar", G.refs["refs/heads/main"] == "c0" and not any(m in ("PUT", "PATCH", "DELETE") for m, _ in G.llamadas), str(G.llamadas[-5:]))
check("el commit cuelga de main", G.commits[out["commit"]]["parents"] == ["c0"], json.dumps(G.commits.get(out.get("commit"), {})))
# editar una landing existente: solo sube lo que cambió
f = tmp / "landings/landings/diagnostico/index.html"; f.write_text(f.read_text().replace("</h1>", " hoy</h1>", 1))
run("revisar", "--slug", "diagnostico"); c, o = run("abrir", "--slug", "diagnostico", "--titulo", "Titular nuevo")
out2 = ultimo_json(o)
check("en una landing existente solo sube el archivo que cambió", c == 0 and out2.get("archivos") == ["landings/diagnostico/index.html"], o)
# sin cambios
shutil.rmtree(tmp / "landings/landings/diagnostico"); shutil.copytree(LANDINGS / "landings/diagnostico", tmp / "landings/landings/diagnostico")
run("revisar", "--slug", "diagnostico"); c, o = run("abrir", "--slug", "diagnostico", "--titulo", "nada")
check("sin cambios contra main no abre PR", c != 0 and "No hay cambios" in o and len(G.prs) == 2, o)
# borrar un archivo de la landing → entrada con sha null
(tmp / "landings/landings/diagnostico/fonts/Anton-Regular.ttf").unlink()
c, o = run("revisar", "--slug", "diagnostico")
check("revisar detiene una landing a la que le falta un archivo que usa", c != 0, o)
# sin token
c, o = run("abrir", "--slug", "buen-fin", "--titulo", "x", env={**ENV, "GITHUB_TOKEN": ""})
check("sin GITHUB_TOKEN no hace nada", c != 0 and ("GITHUB_TOKEN" in o or "revisar" in o), o)
print(f"\n{sum(res)}/{len(res)} comprobaciones correctas."); sys.exit(0 if all(res) else 1)
