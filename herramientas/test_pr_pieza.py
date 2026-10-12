#!/usr/bin/env python3
"""Prueba de pr_pieza.py contra un GitHub FALSO y un Higgsfield FALSO (servidores locales) y una copia del repo de marca.

  MARCA_REPO=../../5cero5-marca python3 test_pr_pieza.py

Necesita Pillow y Playwright con Chromium (render y Verificador de marca)."""
import base64, hashlib, io, json, os, random, re, shutil, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARCA = Path(os.environ.get("MARCA_REPO", HERE.parent.parent / "5cero5-marca")).resolve()
blob_sha = lambda b: hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()
REPO = "5cero5/5cero5-piezas"


class GH:
    def __init__(self):
        readme = b"# piezas\n"
        self.blobs = {blob_sha(readme): readme}
        self.trees = {"t0": [{"path": "README.md", "mode": "100644", "type": "blob", "sha": blob_sha(readme)}]}
        self.commits = {"c0": {"tree": "t0", "parents": []}}
        self.refs = {"refs/heads/main": "c0"}
        self.prs, self.llamadas, self.n = [], [], 0

    def nuevo(self, p):
        self.n += 1
        return f"{p}{self.n}"


G = GH()
HF = {"posts": [], "status_gets": 0, "auth_imagen": [], "final": "completed"}
IMAGEN = None


class Base(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, obj, code=200, tipo="application/json"):
        b = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", tipo); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


class HGit(Base):
    def ok(self):
        if self.headers.get("Authorization") != "Bearer ghs_prueba":
            self.send({"message": "Bad credentials"}, 401); return False
        return True

    def do_GET(self):
        G.llamadas.append(("GET", self.path))
        if not self.ok(): return
        p = self.path.split("?")[0]
        pre = f"/repos/{REPO}/git/"
        if p == pre + "ref/heads/main": return self.send({"object": {"sha": G.refs["refs/heads/main"]}})
        if m := re.fullmatch(re.escape(pre) + r"commits/(\w+)", p): return self.send({"sha": m.group(1), "tree": {"sha": G.commits[m.group(1)]["tree"]}})
        if m := re.fullmatch(re.escape(pre) + r"trees/(\w+)", p): return self.send({"sha": m.group(1), "tree": G.trees[m.group(1)]})
        self.send({}, 404)

    def do_POST(self):
        G.llamadas.append(("POST", self.path))
        if not self.ok(): return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        p = self.path
        if not p.startswith(f"/repos/{REPO}/"): return self.send({}, 404)
        if p.endswith("/git/blobs"):
            b = base64.b64decode(body["content"]); s = blob_sha(b); G.blobs[s] = b; return self.send({"sha": s}, 201)
        if p.endswith("/git/trees"):
            base = {e["path"]: e for e in G.trees[body["base_tree"]]}
            for e in body["tree"]:
                if e["sha"] is None: base.pop(e["path"], None)
                else: base[e["path"]] = e
            t = G.nuevo("t"); G.trees[t] = list(base.values()); G.ultimo = body["tree"]; return self.send({"sha": t}, 201)
        if p.endswith("/git/commits"):
            c = G.nuevo("c"); G.commits[c] = {"tree": body["tree"], "parents": body["parents"]}; return self.send({"sha": c}, 201)
        if p.endswith("/git/refs"):
            G.refs[body["ref"]] = body["sha"]; return self.send({"ref": body["ref"]}, 201)
        if p.endswith("/pulls"):
            n = len(G.prs) + 1; G.prs.append(body); return self.send({"number": n, "html_url": f"https://github.com/{REPO}/pull/{n}"}, 201)
        self.send({}, 404)


class HHiggs(Base):
    def do_POST(self):
        if self.headers.get("Authorization") != "Key hf_prueba": return self.send({"detail": "no auth"}, 401)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        HF["posts"].append((self.path, body))
        self.send({"status": "queued", "request_id": "req-1", "status_url": f"{API_HF}/requests/req-1/status"})

    def do_GET(self):
        if self.headers.get("Authorization") != "Key hf_prueba": return self.send({"detail": "no auth"}, 401)
        HF["status_gets"] += 1
        if HF["status_gets"] < 2: return self.send({"status": "in_progress", "request_id": "req-1"})
        self.send({"status": HF["final"], "request_id": "req-1", "images": [{"url": f"{URL_IMG}/archivo/foto.jpg"}]})


class HImagen(Base):
    def do_GET(self):
        HF["auth_imagen"].append(self.headers.get("Authorization"))
        self.send(IMAGEN, tipo="image/jpeg")


def servidor(h):
    s = ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{s.server_address[1]}"


API_GH, API_HF, URL_IMG = servidor(HGit), servidor(HHiggs), servidor(HImagen)
TMP = Path(tempfile.mkdtemp())
MARCA_COPIA, TRABAJO = TMP / "marca", TMP / "creativo"
shutil.copytree(MARCA, MARCA_COPIA, ignore=shutil.ignore_patterns(".git", "__pycache__"))
ENV = {**os.environ, "GITHUB_API_BASE": API_GH, "GITHUB_TOKEN": "ghs_prueba", "HIGGSFIELD_API_BASE": API_HF,
       "HIGGSFIELD_API_KEY": "hf_prueba", "HF_ESPERA_S": "0.05",
       "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
TOOL = [sys.executable, str(HERE / "pr_pieza.py"), "--trabajo", str(TRABAJO), "--marca", str(MARCA_COPIA)]
BIEN = {"kicker": "Sin coordinar a ocho proveedores", "titular": ["Ocho", "proveedores,", "no."],
        "subtitulo": "Un solo equipo arma tus citas, pedidos y visitas.", "nota": "Desde $20,000 al mes + IVA. Licencias incluidas."}
PROMPT = "Fotografía editorial del mostrador de una papelería de barrio en Monterrey, luz natural, encuadre horizontal, sin personas, sin texto y sin logos"


def corre(*args, env=None):
    r = subprocess.run(TOOL + list(args), capture_output=True, text=True, env=env or ENV, timeout=300)
    return r.returncode, r.stdout + r.stderr


def dir_(c, p): return TRABAJO / c / p


def copia(c, p, d): (dir_(c, p) / "copia.json").write_text(json.dumps(d, ensure_ascii=False))


res = []
def check(nombre, ok, detalle=""):
    res.append(ok); print(f"{'✓' if ok else '✗'} {nombre} {'' if ok else detalle[-1500:]}")


def main():
    global IMAGEN
    random.seed(4)
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (1400, 700), (120, 90, 60)); d = ImageDraw.Draw(im)
    for _ in range(500):
        x, y, r = random.randint(0, 1400), random.randint(0, 700), random.randint(10, 80)
        d.ellipse([x, y, x + r, y + r], fill=(random.randint(40, 230), random.randint(40, 200), random.randint(30, 180)))
    b = io.BytesIO(); im.save(b, "JPEG", quality=90); IMAGEN = b.getvalue()

    c, o = corre("nueva", "--campana", "../x", "--pieza", "p", "--formato", "post-4x5")
    check("rechaza una campaña que sale de la carpeta", c != 0 and "inválido" in o, o)
    c, o = corre("nueva", "--campana", "poc", "--pieza", "post-a", "--formato", "post-4x5")
    d1 = dir_("poc", "post-a")
    check("nueva arma la pieza con la plantilla, fuentes, logo y pieza.json", c == 0 and (d1 / "plantillas/pieza.html").exists()
          and (d1 / "fonts/Anton-Regular.ttf").exists() and json.loads((d1 / "pieza.json").read_text())["foto"] is False, o)
    c, o = corre("nueva", "--campana", "poc", "--pieza", "post-a", "--formato", "post-4x5")
    check("nueva no pisa una pieza que ya existe", c != 0 and "Ya existe" in o, o)
    c, o = corre("abrir", "--campana", "poc", "--pieza", "post-a", "--titulo", "x")
    check("abrir se niega si no se revisó", c != 0 and "revisar" in o, o)
    c, o = corre("revisar", "--campana", "poc", "--pieza", "post-a")
    check("revisar se niega antes de llenar", c != 0 and "llenar" in o, o)
    copia("poc", "post-a", {**BIEN, "cta_extra": "Agenda"})
    c, o = corre("llenar", "--campana", "poc", "--pieza", "post-a")
    check("llenar rechaza claves de más en copia.json", c != 0 and "sobran" in o, o)
    copia("poc", "post-a", {**BIEN, "subtitulo": "Garantizamos resultados para tu negocio."})
    corre("llenar", "--campana", "poc", "--pieza", "post-a")
    c, o = corre("revisar", "--campana", "poc", "--pieza", "post-a")
    check("revisar rechaza una promesa (Verificador de marca)", c != 0 and "sin_promesas" in o and not (d1 / ".revisado").exists(), o)
    copia("poc", "post-a", {**BIEN, "titular": ["Una agencia", "y seis", "licencias,", "no."]})
    corre("llenar", "--campana", "poc", "--pieza", "post-a")
    c, o = corre("revisar", "--campana", "poc", "--pieza", "post-a")
    check("revisar detiene un titular que se encima con el subtítulo", c != 0 and "titular/subtitulo" in o and not (d1 / ".revisado").exists(), o)
    copia("poc", "post-a", BIEN)
    corre("llenar", "--campana", "poc", "--pieza", "post-a")
    c, o = corre("revisar", "--campana", "poc", "--pieza", "post-a")
    inf = json.loads((d1 / "informe.json").read_text()) if (d1 / "informe.json").exists() else {}
    check("revisar aprueba la pieza buena y deja PNG e informe del formato", c == 0 and inf.get("aprobada") and inf.get("formato") == "post-4x5"
          and inf.get("png_blob_sha") == blob_sha((d1 / "pieza.png").read_bytes()), o)
    check("la copia declarada coincide con el HTML", any(r["id"] == "copia_declarada_coincide" and r["ok"] for r in inf.get("revisiones", [])), json.dumps(inf)[:500])
    c, o = corre("foto", "--campana", "poc", "--pieza", "post-a", "--prompt", PROMPT)
    check("foto se niega si la pieza no la pide", c != 0 and "sin foto" in o and not HF["posts"], o)

    copia("poc", "post-a", {**BIEN, "kicker": "Otro texto"})
    c, o = corre("abrir", "--campana", "poc", "--pieza", "post-a", "--titulo", "x")
    check("abrir se niega si la pieza cambió después de revisar", c != 0 and "cambió" in o, o)
    copia("poc", "post-a", BIEN)
    c, o = corre("abrir", "--campana", "poc", "--pieza", "post-a", "--titulo", "Post diagnóstico", env={**ENV, "GITHUB_TOKEN": ""})
    check("sin GITHUB_TOKEN no abre nada", c != 0 and "GITHUB_TOKEN" in o and not G.prs, o)
    c, o = corre("abrir", "--campana", "poc", "--pieza", "post-a", "--titulo", "Post diagnóstico")
    out = json.loads(o.strip().splitlines()[-1]) if c == 0 else {}
    pr = G.prs[-1] if G.prs else {}
    nombres = sorted(e["path"] for e in getattr(G, "ultimo", []))
    check("abrir crea rama agente/ y PR a main", c == 0 and pr.get("base") == "main" and str(pr.get("head", "")).startswith("agente/poc-post-a-"), o)
    check("el PR trae exactamente la lista fija de piezas/poc/post-a/", nombres == sorted(f"piezas/poc/post-a/{n}" for n in
          ("pieza.png", "pieza.html", "copia.json", "pieza.json", "informe.json")), str(nombres))
    check("el PNG del PR es el del informe (blob sha)", out.get("png_blob_sha") in G.blobs and blob_sha(G.blobs[out["png_blob_sha"]]) == out["png_blob_sha"], o)
    check("main no se movió y nada intentó fusionar", G.refs["refs/heads/main"] == "c0" and not any("merge" in p for _, p in G.llamadas), str(G.llamadas[-5:]))

    # Historia con foto de Higgsfield
    c, o = corre("nueva", "--campana", "poc", "--pieza", "historia-a", "--formato", "historia-9x16", "--foto")
    d2 = dir_("poc", "historia-a")
    check("nueva con --foto usa la plantilla con foto", c == 0 and 'class="foto"' in (d2 / "plantillas/pieza.html").read_text(), o)
    c, o = corre("revisar", "--campana", "poc", "--pieza", "historia-a")
    check("revisar se niega si la pieza lleva foto y aún no la tiene", c != 0 and "foto" in o, o)
    c, o = corre("foto", "--campana", "poc", "--pieza", "historia-a", "--prompt", "Fotografía editorial de una bodega chica en Monterrey con luz natural")
    check("foto exige pedir sin texto y sin logos (sin gastar)", c != 0 and "sin texto" in o and not HF["posts"]
          and not (TRABAJO / ".fotos_de_la_sesion").exists(), o)
    c, o = corre("foto", "--campana", "poc", "--pieza", "historia-a", "--prompt", "Retrato de un cliente real dando su testimonio en su tienda, sin texto y sin logos")
    check("foto rechaza un prompt de testimonio (sin gastar)", c != 0 and "testimonio" in o and not HF["posts"], o)
    c, o = corre("foto", "--campana", "poc", "--pieza", "historia-a", "--prompt", PROMPT)
    meta = json.loads((d2 / "pieza.json").read_text())
    check("foto: una sola solicitud a Higgsfield con la llave en el encabezado", c == 0 and len(HF["posts"]) == 1
          and HF["posts"][0] == ("/higgsfield-ai/soul/v2/standard", {"prompt": PROMPT}), o)
    check("la imagen se baja SIN la llave (otro host)", HF["auth_imagen"] == [None], str(HF["auth_imagen"]))
    check("foto guarda fondo.jpg, prompt.txt y el request en pieza.json", (d2 / "fotos/fondo.jpg").read_bytes() == IMAGEN
          and (d2 / "prompt.txt").read_text().strip() == PROMPT and meta["higgsfield"]["request_id"] == "req-1"
          and meta["higgsfield"]["estado"] == "completed", json.dumps(meta))
    c, o = corre("foto", "--campana", "poc", "--pieza", "historia-a", "--prompt", PROMPT)
    check("una sola foto por pieza", c != 0 and "una por pieza" in o and len(HF["posts"]) == 1, o)
    copia("poc", "historia-a", {**BIEN, "titular": ["Ocho", "proveedores,", "no."]})
    corre("llenar", "--campana", "poc", "--pieza", "historia-a")
    c, o = corre("revisar", "--campana", "poc", "--pieza", "historia-a")
    inf2 = json.loads((d2 / "informe.json").read_text()) if (d2 / "informe.json").exists() else {}
    check("revisar aprueba la historia 9:16 con foto", c == 0 and inf2.get("formato") == "historia-9x16" and inf2.get("aprobada"), o)
    c, o = corre("abrir", "--campana", "poc", "--pieza", "historia-a", "--titulo", "Historia diagnóstico")
    nombres = sorted(e["path"] for e in G.ultimo)
    check("el PR de la historia trae la foto y su prompt", c == 0 and "piezas/poc/historia-a/fotos/fondo.jpg" in nombres
          and "piezas/poc/historia-a/prompt.txt" in nombres and all(n.startswith("piezas/poc/historia-a/") for n in nombres), str(nombres) + o)

    # Tope de la sesión: dos fotos
    corre("nueva", "--campana", "poc", "--pieza", "post-b", "--formato", "post-1x1", "--foto")
    HF["status_gets"] = 0; HF["final"] = "failed"
    c, o = corre("foto", "--campana", "poc", "--pieza", "post-b", "--prompt", PROMPT)
    check("una foto fallida se reporta y no se reintenta sola", c != 0 and "failed" in o and len(HF["posts"]) == 2, o)
    corre("nueva", "--campana", "poc", "--pieza", "post-c", "--formato", "post-1x1", "--foto")
    c, o = corre("foto", "--campana", "poc", "--pieza", "post-c", "--prompt", PROMPT)
    check("máximo dos fotos por sesión", c != 0 and "máximo 2" in o and len(HF["posts"]) == 2, o)

    # Post 1:1 sin foto
    corre("nueva", "--campana", "poc", "--pieza", "cuadro", "--formato", "post-1x1")
    copia("poc", "cuadro", BIEN)
    corre("llenar", "--campana", "poc", "--pieza", "cuadro")
    c, o = corre("revisar", "--campana", "poc", "--pieza", "cuadro")
    check("revisar aprueba el post 1:1", c == 0 and json.loads((dir_("poc", "cuadro") / "informe.json").read_text())["formato"] == "post-1x1", o)

    print(f"\n{sum(res)}/{len(res)} comprobaciones correctas.")
    sys.exit(0 if all(res) else 1)


if __name__ == "__main__":
    main()
