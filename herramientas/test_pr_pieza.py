#!/usr/bin/env python3
"""Prueba de pr_pieza.py contra un GitHub FALSO y un Higgsfield FALSO (servidores locales) y una copia del repo de marca.

  MARCA_REPO=../../5cero5-marca python3 test_pr_pieza.py

Necesita Pillow y Playwright con Chromium (render y Verificador de marca)."""
import base64, hashlib, io, json, os, random, re, shutil, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARCA = Path(os.environ.get("MARCA_REPO", HERE.parent.parent / "5cero5-marca")).resolve()
# Lo que la prueba espera sale del repo de marca que se le pase (5cero5 u otro cliente), no de valores fijos.
TOKENS_M = json.loads((MARCA / "tokens.json").read_text(encoding="utf-8"))
BLOQ_M = json.loads((MARCA / "verificador" / "bloqueos.json").read_text(encoding="utf-8")) if (MARCA / "verificador" / "bloqueos.json").exists() else {}
PLANT_M = (MARCA / TOKENS_M["formatos"]["post-4x5"]["plantilla"]).read_text(encoding="utf-8")
T_H1 = int(re.search(r"h1\s*\{[^}]*?font:\s*(?:\d{3}\s+)?(\d+)px", PLANT_M).group(1))
ARCH_FUENTES = [Path(a).name for r in ("titular", "texto") for t in [TOKENS_M["tipografia"].get(r) or {}]
                for a in (t.get("archivos") or ([t["archivo"]] if t.get("archivo") else []))]
CON_PROMESAS = bool(BLOQ_M.get("promesas"))          # 5cero5 sí; un cliente sin voz definida, no
sys.path.insert(0, str(HERE))
from pr_pieza import ASPECTOS, aspecto_de  # noqa: E402
ASPECTO_HIST = aspecto_de((MARCA / TOKENS_M["formatos"]["historia-9x16"]["plantilla_con_foto"]).read_text(encoding="utf-8"))
CON_MARCA_CSS = bool(re.search(r"h1\s+\.marca\s*\{", PLANT_M))
AJUSTA_4_LINEAS = "'Anton'" in PLANT_M             # solo en la plantilla de 5cero5 un titular de 4 líneas toca el subtítulo
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
HF = {"posts": [], "status_gets": 0, "auth_imagen": [], "final": "completed", "puts": [], "imagen": None,
      "expira": [], "deletes": [], "delete_code": 200}
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
        if m := re.fullmatch(re.escape(pre) + r"ref/heads/(.+)", p):
            return self.send({"object": {"sha": G.refs["refs/heads/" + m.group(1)]}}) if "refs/heads/" + m.group(1) in G.refs else self.send({}, 404)
        if m := re.fullmatch(re.escape(pre) + r"blobs/(\w+)", p): return self.send({"content": base64.b64encode(G.blobs[m.group(1)]).decode()})
        if m := re.fullmatch(rf"/repos/{re.escape(REPO)}/pulls/(\d+)(/files)?", p):
            pr = G.prs[int(m.group(1)) - 1]; head = G.refs["refs/heads/" + pr["head"]]
            if m.group(2):  # lo que cambia la rama contra main
                arbol = lambda c: {e["path"]: e["sha"] for e in G.trees[G.commits[c]["tree"]]}
                h, b = arbol(head), arbol(G.refs["refs/heads/main"])
                return self.send([{"filename": k} for k in h if b.get(k) != h[k]])
            return self.send({"number": int(m.group(1)), "state": pr.get("state", "open"), "merged": pr.get("merged", False),
                              "merged_at": "2026-11-04T00:00:00Z" if pr.get("merged") else None, "base": {"ref": "main"},
                              "head": {"ref": pr["head"], "sha": head, "repo": {"full_name": REPO}},
                              "html_url": f"https://github.com/{REPO}/pull/{m.group(1)}"})
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

    def do_PATCH(self):
        G.llamadas.append(("PATCH", self.path))
        if not self.ok(): return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        m = re.fullmatch(rf"/repos/{re.escape(REPO)}/git/refs/heads/(.+)", self.path)
        if not m or body.get("force"): return self.send({}, 422)
        G.refs["refs/heads/" + m.group(1)] = body["sha"]; self.send({"object": {"sha": body["sha"]}})


V2_ASPECTOS = {"9:16", "16:9", "4:3", "3:4", "1:1", "2:3", "3:2"}


class HHiggs(Base):
    def do_POST(self):
        if self.headers.get("Authorization") != "Key hf_prueba": return self.send({"detail": "no auth"}, 401)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        HF["posts"].append((self.path, body))
        if self.path != "/files/generate-upload-url":
            HF["expira"].append(self.headers.get("Hf-Expires-After"))
        if self.path == "/files/generate-upload-url":  # URL firmada: otro host, sin la llave
            return self.send({"upload_url": f"{URL_IMG}/subir/x", "public_url": "https://cdn.prueba/x.jpg", "content_type": body["content_type"],
                              "upload_headers": {"Content-Type": body["content_type"], "x-amz-tagging": "retention=temporary"}})
        # Como el Soul v2 real (3 nov 2026): una proporción fuera de su lista es 400 y no se cobra.
        if "aspect_ratio" in body and body["aspect_ratio"] not in V2_ASPECTOS:
            return self.send({"detail": f"aspect_ratio must be one of {sorted(V2_ASPECTOS)}"}, 400)
        self.send({"status": "queued", "request_id": "req-1", "status_url": f"{API_HF}/requests/req-1/status"})

    def do_DELETE(self):
        if self.headers.get("Authorization") != "Key hf_prueba": return self.send({"detail": "no auth"}, 401)
        HF["deletes"].append(self.path)
        if HF["delete_code"] != 200: return self.send({"detail": "Deletion temporarily unavailable"}, HF["delete_code"])
        self.send({"request_id": self.path.rsplit("/", 1)[-1], "status": "deleted"})

    def do_GET(self):
        if self.headers.get("Authorization") != "Key hf_prueba": return self.send({"detail": "no auth"}, 401)
        HF["status_gets"] += 1
        if HF["status_gets"] < 2: return self.send({"status": "in_progress", "request_id": "req-1"})
        self.send({"status": HF["final"], "request_id": "req-1", "images": [{"url": f"{URL_IMG}/archivo/foto.jpg"}]})


class HImagen(Base):
    def do_GET(self):
        HF["auth_imagen"].append(self.headers.get("Authorization"))
        self.send(HF["imagen"] or IMAGEN, tipo="image/jpeg")

    def do_PUT(self):
        HF["puts"].append((self.headers.get("Authorization"), len(self.rfile.read(int(self.headers.get("Content-Length", 0))))))
        self.send({})


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
          and (d1 / "fonts").is_dir() and all((d1 / "fonts" / f).exists() for f in ARCH_FUENTES)
          and json.loads((d1 / "pieza.json").read_text())["foto"] is False, o)
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
    if CON_PROMESAS:
        check("revisar rechaza una promesa (Verificador de marca)", c != 0 and "sin_promesas" in o and not (d1 / ".revisado").exists(), o)
    else:  # sin voz definida, el Verificador no bloquea por texto: lo avisa
        check("sin reglas de voz, una promesa no bloquea pero sale el aviso", c == 0 and "voz_sin_definir" in o, o)
    copia("poc", "post-a", {**BIEN, "titular": ["Ocho", "proveedores", "para vender,", "no."]})
    corre("llenar", "--campana", "poc", "--pieza", "post-a")
    c, o = corre("revisar", "--campana", "poc", "--pieza", "post-a")
    px = json.loads((d1 / "pieza.json").read_text()).get("titular_px", 0)
    if AJUSTA_4_LINEAS:
        check("un titular de 4 líneas se ajusta bajando su tamaño (no más de 30 %)", c == 0 and f"Titular ajustado de {T_H1}" in o and int(T_H1 * 0.7) <= px < T_H1, o)
    else:
        check("un titular de 4 líneas que cabe no se ajusta", c == 0 and "Titular ajustado" not in o and px in (0, T_H1), o)
    h_4 = (d1 / "plantillas/pieza.html").read_text()
    check("la última línea va en .marca solo si la plantilla lo define", ('class="marca"' in h_4) == CON_MARCA_CSS, "")
    corre("llenar", "--campana", "poc", "--pieza", "post-a")
    check("llenar regresa el titular al tamaño de la plantilla",
          int(re.search(r"h1\s*\{[^}]*?font:\s*(?:\d{3}\s+)?(\d+)px", (d1 / "plantillas/pieza.html").read_text()).group(1)) == T_H1, "")
    copia("poc", "post-a", {**BIEN, "subtitulo": "Un solo equipo profesional coordina diariamente todas tus citas, pedidos, visitas y cobranzas." * (1 if AJUSTA_4_LINEAS else 8)})
    corre("llenar", "--campana", "poc", "--pieza", "post-a")
    c, o = corre("revisar", "--campana", "poc", "--pieza", "post-a")
    check("revisar detiene un subtítulo que se encima (eso no se ajusta solo)", c != 0 and re.search(r"subtitulo/\w+", o) and not (d1 / ".revisado").exists(), o)
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
          and HF["posts"][0] == ("/higgsfield-ai/soul/v2/standard", {"prompt": PROMPT, "aspect_ratio": ASPECTO_HIST}), o)
    check("la imagen se baja SIN la llave (otro host)", HF["auth_imagen"] == [None], str(HF["auth_imagen"]))
    check("retención: la generación va con Hf-Expires-After: 3600 y, bajada la imagen, se borra con DELETE /requests/{id}",
          HF["expira"] == ["3600"] and HF["deletes"] == ["/requests/req-1"] and meta["higgsfield"].get("borrado") == {"ok": True, "estado": "deleted"},
          f"{HF['expira']} {HF['deletes']} {meta['higgsfield'].get('borrado')}")
    check("foto guarda fondo.jpg, prompt.txt y el request en pieza.json", (d2 / "fotos/fondo.jpg").read_bytes() == IMAGEN
          and (d2 / "prompt.txt").read_text().strip() == PROMPT and meta["higgsfield"]["request_id"] == "req-1"
          and meta["higgsfield"]["estado"] == "completed" and meta["higgsfield"].get("blob_sha") == blob_sha(IMAGEN), json.dumps(meta))
    check("aspect_ratio sale del marco .foto y es un valor que acepta Higgsfield",
          ASPECTO_HIST in ASPECTOS and meta["higgsfield"].get("aspect_ratio") == ASPECTO_HIST
          and aspecto_de(".foto { width: 1000px; height: 1000px; }") == "1:1" and aspecto_de(".foto { width: 900px; height: 1600px; }") == "9:16"
          and aspecto_de("<p>sin marco</p>") == "4:3", f"{ASPECTO_HIST} {meta.get('higgsfield')}")
    check("los marcos de foto se mapean a la proporción v2 más cercana (21:9 → 16:9, 4:5 → 3:4)",
          ASPECTO_HIST == "16:9" and aspecto_de(".foto { width: 904px; height: 330px; }") == "16:9"
          and aspecto_de(".foto { width: 800px; height: 1000px; }") == "3:4" and set(ASPECTOS) == V2_ASPECTOS, ASPECTO_HIST)
    r = subprocess.run([sys.executable, "-c", "import pr_pieza as p; p.hf('POST', p.HF_API + p.HF_ENDPOINT, {'prompt': 'x', 'aspect_ratio': '21:9'})"],
                       cwd=HERE, env=ENV, capture_output=True, text=True)
    HF["posts"].pop()  # esta llamada directa solo reproduce el error; no cuenta como foto de la sesión
    check("reproduce el 400 de Soul v2 con 21:9 (Higgsfield simulado)", r.returncode != 0 and "respondió 400" in (r.stdout + r.stderr)
          and "aspect_ratio must be one of" in (r.stdout + r.stderr), r.stdout + r.stderr)
    corre("nueva", "--campana", "poc", "--pieza", "historia-z", "--formato", "historia-9x16", "--foto")
    cont = TRABAJO / ".fotos_de_la_sesion"; antes = cont.read_text() if cont.exists() else ""
    n0 = len(HF["posts"])
    c, o = corre("foto", "--campana", "poc", "--pieza", "historia-z", "--prompt", PROMPT, env={**ENV, "HF_ASPECTOS": "21:9"})
    check("sin proporción válida se detiene SIN llamar a Higgsfield ni contar la foto", c != 0 and "No hay una proporción válida" in o
          and len(HF["posts"]) == n0 and (cont.read_text() if cont.exists() else "") == antes, o)
    shutil.rmtree(dir_("poc", "historia-z"))
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
    topes = {}
    for v in ("", "1", "2", "5", "abc"):
        r = subprocess.run([sys.executable, "-c", "import pr_pieza; print(pr_pieza.FOTOS_POR_SESION)"], cwd=HERE,
                           env={**os.environ, "FOTOS_POR_SESION": v}, capture_output=True, text=True)
        topes[v] = r.stdout.strip()
    check("FOTOS_POR_SESION baja el tope pero nunca lo sube (vacío 2, 1→1, 5→2, raro→0)",
          topes == {"": "2", "1": "1", "2": "2", "5": "2", "abc": "0"}, json.dumps(topes))

    # Post 1:1 sin foto
    corre("nueva", "--campana", "poc", "--pieza", "cuadro", "--formato", "post-1x1")
    copia("poc", "cuadro", BIEN)
    corre("llenar", "--campana", "poc", "--pieza", "cuadro")
    c, o = corre("revisar", "--campana", "poc", "--pieza", "cuadro")
    check("revisar aprueba el post 1:1", c == 0 and json.loads((dir_("poc", "cuadro") / "informe.json").read_text())["formato"] == "post-1x1", o)

    fotos_del_cliente_y_rondas()
    print(f"\n{sum(res)}/{len(res)} comprobaciones correctas.")
    sys.exit(0 if all(res) else 1)



def imagen(semilla):
    from PIL import Image, ImageDraw
    random.seed(semilla)
    im = Image.new("RGB", (1400, 700), (60, 90, 120)); d = ImageDraw.Draw(im)
    for _ in range(500):
        x, y, r = random.randint(0, 1400), random.randint(0, 700), random.randint(10, 80)
        d.ellipse([x, y, x + r, y + r], fill=(random.randint(40, 230), random.randint(40, 200), random.randint(30, 180)))
    b = io.BytesIO(); im.save(b, "JPEG", quality=90); return b.getvalue()


def fotos_del_cliente_y_rondas():
    """Fotos del repo de marca (repo: y referencia:), nota opcional y rondas sobre el mismo PR (Igual, Editar, fusionado)."""
    trabajo = TMP / "creativo2"  # sesión aparte: su propio tope de fotos
    tool = lambda *a, env=None: subprocess.run([sys.executable, str(HERE / "pr_pieza.py"), "--trabajo", str(trabajo), "--marca", str(MARCA_COPIA)] + list(a),
                                               capture_output=True, text=True, env=env or ENV, timeout=300)
    def corre2(*a):
        r = tool(*a); return r.returncode, r.stdout + r.stderr
    fdir = MARCA_COPIA / "fotos"; fdir.mkdir(exist_ok=True)
    (fdir / "mostrador.jpg").write_bytes(IMAGEN); (fdir / "equipo.jpg").write_bytes(imagen(7))
    (fdir / "fotos.json").write_text(json.dumps({"fotos": [
        {"id": "mostrador", "archivo": "mostrador.jpg", "descripcion": "Mostrador de la sucursal centro con luz de mañana",
         "autorizo": "Dueña, 2 nov 2026", "fecha": "2026-11-02", "uso": ["directo", "referencia_ia"], "personas": False},
        {"id": "equipo", "archivo": "equipo.jpg", "descripcion": "Equipo de la sucursal", "autorizo": "Dueña, 2 nov 2026",
         "fecha": "2026-11-02", "uso": ["directo", "referencia_ia"], "personas": True}]}, ensure_ascii=False))
    d3 = trabajo / "poc" / "foto-repo"
    corre2("nueva", "--campana", "poc", "--pieza", "foto-repo", "--formato", "post-4x5", "--foto")
    n0 = len(HF["posts"])
    c, o = corre2("foto", "--campana", "poc", "--pieza", "foto-repo", "--repo-id", "vitrina-de-otro-cliente")
    check("repo:<id> de otro cliente (no está en fotos.json de esta marca) falla sin llamar a nadie", c != 0 and "no está en fotos/fotos.json" in o and len(HF["posts"]) == n0, o)
    c, o = corre2("foto", "--campana", "poc", "--pieza", "foto-repo", "--repo-id", "mostrador")
    meta = json.loads((d3 / "pieza.json").read_text())
    check("repo:<id> válido: la foto del cliente va tal cual, sin Higgsfield", c == 0 and (d3 / "fotos/fondo.jpg").read_bytes() == IMAGEN
          and meta["foto_cliente"]["blob_sha"] == blob_sha(IMAGEN) and len(HF["posts"]) == n0
          and "Foto de la marca: Mostrador" in (d3 / "plantillas/pieza.html").read_text(), o + json.dumps(meta))
    corre2("nueva", "--campana", "poc", "--pieza", "foto-ref", "--formato", "post-4x5", "--foto")
    c, o = corre2("foto", "--campana", "poc", "--pieza", "foto-ref", "--referencia", "equipo", "--prompt", PROMPT)
    check("una foto con personas no se manda como referencia a la IA", c != 0 and "personas" in o and len(HF["posts"]) == n0 and not HF["puts"], o)
    HF["status_gets"] = 0; HF["final"] = "completed"; HF["delete_code"] = 503
    c, o = corre2("foto", "--campana", "poc", "--pieza", "foto-ref", "--referencia", "mostrador", "--prompt", PROMPT)
    HF["delete_code"] = 200
    borr = json.loads((trabajo / "poc/foto-ref/pieza.json").read_text())["higgsfield"].get("borrado") or {}
    check("si el DELETE en Higgsfield falla, la pieza sigue y el fallo queda en pieza.json", c == 0 and borr.get("ok") is False
          and "503" in borr.get("error", "") and "No se pudo borrar" in o, o + json.dumps(borr))
    edic = [b for p, b in HF["posts"][n0:] if p == "/alibaba/qwen-image-3/edit"]
    check("referencia:<id>: sube la foto sin la llave y la manda al modelo de edición en image_urls",
          c == 0 and edic == [{"prompt": PROMPT, "image_urls": ["https://cdn.prueba/x.jpg"]}] and HF["puts"] == [(None, len(IMAGEN))]
          and json.loads((trabajo / "poc/foto-ref/pieza.json").read_text())["higgsfield"]["referencia"] == "mostrador", o + str(HF["posts"][n0:]))

    copia_ = lambda pz, dd: (trabajo / "poc" / pz / "copia.json").write_text(json.dumps(dd, ensure_ascii=False))
    copia_("foto-repo", BIEN)
    corre2("llenar", "--campana", "poc", "--pieza", "foto-repo")
    c, o = corre2("revisar", "--campana", "poc", "--pieza", "foto-repo")
    # La marca decide si acepta fotos reales: la de 5cero5 solo acepta fotos generadas (el alt debe decirlo) y la bloquea.
    solo_ia = "foto_no_es_cliente" in o and c != 0
    check("repo:<id>: el Verificador de la marca decide (alt verdadero, no dice que es de IA)", c == 0 or solo_ia, o)
    copia_("foto-ref", {**BIEN, "nota": ""})
    c, o = corre2("llenar", "--campana", "poc", "--pieza", "foto-ref")
    check("la nota es opcional en llenar", c == 0, o)
    c, o = corre2("revisar", "--campana", "poc", "--pieza", "foto-ref")
    c2, o2 = corre2("abrir", "--campana", "poc", "--pieza", "foto-ref", "--titulo", "Post con foto de referencia")
    check("revisar y abrir la pieza con foto de referencia y sin nota", c == 0 and c2 == 0, o + o2)
    inf_ref = json.loads((trabajo / "poc/foto-ref/informe.json").read_text())
    check("el informe registra el borrado fallido en Higgsfield", (inf_ref.get("higgsfield_borrado") or {}).get("ok") is False, json.dumps(inf_ref.get("higgsfield_borrado")))
    n_pr = len(G.prs); rama = G.prs[-1]["head"]; head0 = G.refs["refs/heads/" + rama]

    arbol = lambda c: {e["path"]: e["sha"] for e in G.trees[G.commits[c]["tree"]]}
    cambios = trabajo / "cambios.json"; cambios.write_text(json.dumps({"kicker": "Ahora con cita en línea"}, ensure_ascii=False))
    n1 = len(HF["posts"])
    c, o = corre2("revisar-pr", "--campana", "poc", "--pieza", "foto-ref", "--pr", str(n_pr), "--foto-ronda", "Igual", "--cambios", str(cambios))
    out = json.loads(o.strip().splitlines()[-1]) if c == 0 else {}
    head1 = G.refs["refs/heads/" + rama]
    pref = "piezas/poc/foto-ref/"
    check("ronda Igual: un commit nuevo en la MISMA rama del PR, sin PR nuevo y sin Higgsfield",
          c == 0 and out.get("pr_numero") == n_pr and head1 != head0 and G.commits[head1]["parents"] == [head0]
          and len(G.prs) == n_pr and len(HF["posts"]) == n1, o)
    check("ronda Igual: misma foto (blob_sha) y la copia cambia solo en lo pedido",
          arbol(head1)[pref + "fotos/fondo.jpg"] == arbol(head0)[pref + "fotos/fondo.jpg"]
          and json.loads(G.blobs[arbol(head1)[pref + "copia.json"]]) == {**BIEN, "nota": "", "kicker": "Ahora con cita en línea"}
          and all(k.startswith(pref) for k in out.get("archivos", [])), json.dumps(out))
    HF["imagen_antes"] = G.blobs[arbol(head1)[pref + "fotos/fondo.jpg"]]
    HF["status_gets"] = 0; HF["imagen"] = imagen(11); HF["puts"].clear()
    c, o = corre2("revisar-pr", "--campana", "poc", "--pieza", "foto-ref", "--pr", str(n_pr), "--foto-ronda", "Editar",
                  "--prompt", "Aclara el fondo y quita el objeto de la izquierda")
    head2 = G.refs["refs/heads/" + rama]
    edic = [b for p, b in HF["posts"][n1:] if p == "/alibaba/qwen-image-3/edit"]
    check("ronda Editar: edita la foto actual con el modelo de edición y hace commit en la misma rama",
          c == 0 and len(edic) == 1 and edic[0]["image_urls"] == ["https://cdn.prueba/x.jpg"] and "quita el objeto" in edic[0]["prompt"]
          and HF["puts"] == [(None, len(HF["imagen_antes"]))] and G.commits[head2]["parents"] == [head1] and len(G.prs) == n_pr
          and arbol(head2)[pref + "fotos/fondo.jpg"] == blob_sha(HF["imagen"]), o)
    HF["imagen"] = None
    G.prs[n_pr - 1].update(state="closed", merged=True)
    c, o = corre2("revisar-pr", "--campana", "poc", "--pieza", "foto-ref", "--pr", str(n_pr), "--foto-ronda", "Igual", "--cambios", str(cambios))
    check("ronda sobre un PR ya fusionado: falla y no escribe nada", c != 0 and "fusionado" in o and G.refs["refs/heads/" + rama] == head2, o)


if __name__ == "__main__":
    main()
