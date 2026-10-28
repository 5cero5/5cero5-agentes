#!/usr/bin/env python3
"""Destino permitido por cliente: las herramientas solo escriben donde el token de la sesión es exclusivo.

  uv run --with httpx python test_destino.py

GitHub y HighLevel FALSOS (servidores locales) con dos clientes, A y B. No necesita navegador, red ni los repos de marca:
prueba gh_pr.sube_carpeta (lo que usan pr_landing.py y pr_pieza.py), pr_landing.py y pr_pieza.py con --repo, y correo.py
con --location. El token de A solo ve lo de A; cualquier intento contra B se rechaza antes de escribir."""
import importlib, json, os, re, subprocess, sys, tempfile, threading, types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REPO_A, REPO_B = "cliente-a/landings-a", "cliente-b/landings-b"
TOKENS = {"Bearer ghs_a": [REPO_A], "Bearer ghs_b": [REPO_B], "Bearer ghs_amplio": [REPO_A, REPO_B]}
LOC_A, LOC_B = "locA000001", "locB000002"
HL = {"Bearer pit-a": LOC_A, "Bearer pit-b": LOC_B}


class S:
    escrituras, lecturas = [], []


class GH(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, o, code=200):
        b = json.dumps(o).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def visibles(self):
        return TOKENS.get(self.headers.get("Authorization"), [])

    def do_GET(self):
        p = self.path.split("?")[0]; S.lecturas.append(p); vis = self.visibles()
        if p == "/installation/repositories":
            return self.send({"repositories": [{"full_name": r} for r in vis]})
        m = re.match(r"/repos/([^/]+/[^/]+)/", p)
        if not m or m.group(1) not in vis:  # GitHub responde 404 a un repo que el token no ve
            return self.send({"message": "Not Found"}, 404)
        if p.endswith("/git/ref/heads/main"): return self.send({"object": {"sha": "c0"}})
        if "/git/commits/" in p: return self.send({"tree": {"sha": "t0"}})
        if "/git/trees/" in p: return self.send({"tree": []})
        self.send({}, 404)

    def do_POST(self):
        p = self.path; vis = self.visibles()
        n = int(self.headers.get("Content-Length", 0)); self.rfile.read(n)
        m = re.match(r"/repos/([^/]+/[^/]+)/", p)
        if not m or m.group(1) not in vis:
            return self.send({"message": "Not Found"}, 404)
        S.escrituras.append(p)
        if p.endswith("/pulls"): return self.send({"number": 1, "html_url": f"https://github.com/{m.group(1)}/pull/1"}, 201)
        if p.endswith("/git/refs"): return self.send({"ref": "x"}, 201)
        return self.send({"sha": f"s{len(S.escrituras)}"}, 201)


class HLH(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, o, code=200):
        b = json.dumps(o).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        p = self.path.split("?")[0]; S.lecturas.append(p)
        propia = HL.get(self.headers.get("Authorization"))
        if p.startswith("/locations/"):
            # Un token de integración privada solo lee su propia subcuenta.
            return self.send({"location": {"id": propia}}) if p == f"/locations/{propia}" else self.send({"message": "forbidden"}, 403)
        self.send({}, 404)

    def do_POST(self):
        S.escrituras.append(self.path); self.send({"id": "t1"}, 201)


def arranca(h):
    s = ThreadingHTTPServer(("127.0.0.1", 0), h); threading.Thread(target=s.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{s.server_port}"


GH_BASE, HL_BASE = arranca(GH), arranca(HLH)
os.environ["GITHUB_API_BASE"] = GH_BASE
res = []


def caso(n, c, o=""):
    res.append(bool(c)); print(("✓" if c else "✗"), n, "" if c else str(o)[-600:])


def sube(repo, token):
    """gh_pr.sube_carpeta en el mismo proceso. Devuelve (salió_bien, salida o error)."""
    os.environ["GITHUB_TOKEN"] = token
    import gh_pr
    importlib.reload(gh_pr)
    try:
        return True, gh_pr.sube_carpeta(repo=repo, pref="landings/promo/", locales={"index.html": b"<p>hola</p>"},
                                        mensaje="m", rama_base="promo", cuerpo="c")
    except SystemExit:
        return False, ""


# 1) gh_pr: el token de A escribe en A; nunca en B, aunque el brief lo pida
S.escrituras.clear()
ok, r = sube(REPO_A, "ghs_a")
caso("gh_pr: token de A abre el PR en el repo de A", ok and r["pr_url"].startswith(f"https://github.com/{REPO_A}/"), r)
S.escrituras.clear()
ok, _ = sube(REPO_B, "ghs_a")
caso("gh_pr: --repo de B con el token de A se rechaza y no escribe nada en B", not ok and not S.escrituras, S.escrituras)
S.escrituras.clear()
ok, _ = sube(REPO_A, "ghs_amplio")
caso("gh_pr: un token que ve dos repos no escribe (debe ser exclusivo)", not ok and not S.escrituras, S.escrituras)
ok, _ = sube("../otro", "ghs_a")
caso("gh_pr: --repo con forma inválida se rechaza", not ok)

# 2) Token de A contra un recurso de B: GitHub responde 404 (lo que haría con un token limitado a A)
os.environ["GITHUB_TOKEN"] = "ghs_a"
import gh_pr  # noqa: E402
importlib.reload(gh_pr)
try:
    gh_pr.gh("GET", f"/repos/{REPO_B}/git/ref/heads/main"); leyo = True
except SystemExit:
    leyo = False
caso("gh_pr: el token de A no lee el repo de B (404)", not leyo)


# 3) pr_landing.py y pr_pieza.py reciben --repo (y sin --repo usan el de siempre). cmd_abrir le pasa a.repo a sube_carpeta.
def repo_de(modulo, argv):
    m = importlib.import_module(modulo)
    visto = {}
    m.cmd_abrir = lambda a: visto.update(repo=a.repo)
    sys.argv = [modulo + ".py", *argv]
    m.main()
    return visto.get("repo")


caso("pr_landing.py: --repo llega a sube_carpeta", repo_de("pr_landing", ["--repo", REPO_A, "abrir", "--slug", "promo", "--titulo", "t"]) == REPO_A)
caso("pr_landing.py: sin --repo usa GH_LANDINGS_REPO o 5cero5/5cero5-landings (ruteo apagado)",
     repo_de("pr_landing", ["abrir", "--slug", "promo", "--titulo", "t"]) == os.environ.get("GH_LANDINGS_REPO", "5cero5/5cero5-landings"))
caso("pr_pieza.py: --repo llega a sube_carpeta",
     repo_de("pr_pieza", ["--repo", REPO_A, "abrir", "--campana", "c", "--pieza", "p", "--titulo", "t"]) == REPO_A)

# 4) correo.py: --location de B con el token de A se rechaza antes de verificar o subir
tmp = Path(tempfile.mkdtemp()); (tmp / "c.html").write_text("<p>hola</p>")


def correo(loc, token):
    S.escrituras.clear()
    env = {**os.environ, "HL_TOKEN": token, "HL_API_BASE": HL_BASE, "MARCA_REPO": str(tmp)}
    r = subprocess.run([sys.executable, str(HERE.parent / "poc-conectores" / "correo.py"), "--location", loc, "subir",
                        "--html", str(tmp / "c.html"), "--nombre", "[agente] W1"], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


rc, out = correo(LOC_B, "pit-a")
caso("correo.py: --location de B con el token de A se rechaza (403) y no sube nada", rc != 0 and "403" in out and not S.escrituras, out)
rc, out = correo(LOC_A, "pit-a")
caso("correo.py: --location de A con el token de A pasa la comprobación de subcuenta (sigue al Verificador)",
     "403" not in out and "no confirmó" not in out and not S.escrituras, out)

print(f"\n{sum(res)}/{len(res)} casos")
sys.exit(0 if all(res) else 1)
