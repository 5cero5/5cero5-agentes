#!/usr/bin/env python3
"""Herramienta del agente Creativo: arma UNA pieza (post 4:5, post 1:1 o historia 9:16) con las plantillas del repo de
marca, la revisa con el Verificador y abre un PR en 5cero5-piezas. Nunca fusiona ni publica.

  python3 pr_pieza.py nueva   --campana poc-diagnostico --pieza post-agencia --formato post-4x5 [--foto]
  python3 pr_pieza.py foto    --campana ... --pieza ... --prompt "Fotografía editorial de ..., sin texto y sin logos"
  python3 pr_pieza.py llenar  --campana ... --pieza ...      (escribe copia.json en los SLOT de la plantilla)
  python3 pr_pieza.py revisar --campana ... --pieza ...      (render con Playwright + Verificador de marca)
  python3 pr_pieza.py abrir   --campana ... --pieza ... --titulo "..." [--cuerpo "..."]

Rutas: --trabajo /tmp/creativo (piezas en curso), --marca /tmp/marca (copia del repo de marca).
Variables: GITHUB_TOKEN (lo pone el harness; solo hacia api.github.com). HIGGSFIELD_API_KEY (solo para 'foto'; solo
hacia api.higgsfield.ai). Opcionales: GH_PIEZAS_REPO (5cero5/5cero5-piezas), HF_ENDPOINT, GITHUB_API_BASE y
HIGGSFIELD_API_BASE (solo pruebas).

Lo que se impone:
  - La copia la escribe la herramienta en los SLOT; el agente no edita el HTML a mano.
  - Foto: solo si la pieza se creó con --foto (el brief lo pide), una generación por pieza y dos por sesión. Cada
    generación que termina se cobra del saldo de Higgsfield.
  - 'abrir' se niega si la pieza no pasó 'revisar' en esta corrida o cambió después; sube solo piezas/<campaña>/<pieza>/
    con una lista fija de archivos; solo ramas agente/*; nunca main, nunca fusiona.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gh_pr import blob_sha, die, sube_carpeta  # noqa: E402

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
FORMATOS = ("post-4x5", "post-1x1", "historia-9x16")
REPO = os.environ.get("GH_PIEZAS_REPO", "5cero5/5cero5-piezas")
HF_API = os.environ.get("HIGGSFIELD_API_BASE", "https://api.higgsfield.ai")
HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "/higgsfield-ai/soul/v2/standard")
FOTOS_POR_SESION = 2
EXT_FOTO = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
CLAVES_COPIA = ("kicker", "titular", "subtitulo", "nota")
# Lo único que viaja al PR (más la foto, si la lleva).
SUBE = ("pieza.png", "pieza.html", "copia.json", "pieza.json", "informe.json")


# ------------------------------------------------------------------ rutas
def pieza_dir(a) -> Path:
    for k in ("campana", "pieza"):
        v = getattr(a, k, "") or ""
        if not SLUG.match(v):
            die(f"--{k} inválido: {v!r}. Minúsculas, números y guiones (máximo 41).")
    return Path(a.trabajo) / a.campana / a.pieza


def lee_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"Falta {p.name} en {p.parent}.")
    except json.JSONDecodeError as e:
        die(f"{p.name} no es JSON válido: {e}")


def escribe_json(p: Path, d: dict) -> None:
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def foto_actual(d: Path) -> Path | None:
    fs = sorted((d / "fotos").glob("fondo.*")) if (d / "fotos").exists() else []
    return fs[0] if fs else None


def para_subir(d: Path) -> dict[str, bytes]:
    out = {n: (d / n).read_bytes() for n in SUBE if (d / n).exists()}
    meta = lee_json(d / "pieza.json")
    if meta.get("foto"):
        f = foto_actual(d)
        if f:
            out[f"fotos/{f.name}"] = f.read_bytes()
        if (d / "prompt.txt").exists():
            out["prompt.txt"] = (d / "prompt.txt").read_bytes()
    return out


def huella(d: Path) -> str:
    h = hashlib.sha256()
    for k, v in sorted(para_subir(d).items()):
        h.update(k.encode() + b"\0" + hashlib.sha256(v).digest())
    return h.hexdigest()


# ------------------------------------------------------------------ nueva
def cmd_nueva(a) -> None:
    d = pieza_dir(a)
    if d.exists():
        die(f"Ya existe {a.campana}/{a.pieza} en {a.trabajo}. Usa otro --pieza o sigue con esa.")
    marca = Path(a.marca)
    tokens = lee_json(marca / "tokens.json")
    f = tokens.get("formatos", {}).get(a.formato) or {}
    plantilla = f.get("plantilla_con_foto" if a.foto else "plantilla")
    if not plantilla or not (marca / plantilla).exists():
        die(f"El repo de marca no tiene plantilla para {a.formato}{' con foto' if a.foto else ''}.")
    d.mkdir(parents=True)
    for sub in ("fonts", "logos"):
        shutil.copytree(marca / sub, d / sub)
    (d / "fotos").mkdir()
    (d / "plantillas").mkdir()
    shutil.copy(marca / plantilla, d / "plantillas" / "pieza.html")
    escribe_json(d / "copia.json", {"kicker": "", "titular": ["", "", ""], "subtitulo": "", "nota": ""})
    version = (marca / "VERSION").read_text().strip() if (marca / "VERSION").exists() else "?"
    escribe_json(d / "pieza.json", {"campana": a.campana, "pieza": a.pieza, "formato": a.formato, "foto": bool(a.foto),
                                    "plantilla": plantilla, "marca_version": version, "higgsfield": None})
    print(f"✓ {a.campana}/{a.pieza}: {a.formato}{' con foto' if a.foto else ''} desde {plantilla} (marca v{version}).")
    print(f"  Escribe la copia en {d / 'copia.json'} (titular: lista de líneas; la última va en el tachón o brochazo).")
    if a.foto:
        print("  Luego genera la foto con 'foto' antes de 'revisar'.")


# ------------------------------------------------------------------ foto (Higgsfield)
def hf(method: str, url: str, body: dict | None = None) -> dict:
    key = os.environ.get("HIGGSFIELD_API_KEY", "").strip()
    if not key:
        die("Falta HIGGSFIELD_API_KEY.")
    if urlparse(url).netloc != urlparse(HF_API).netloc:
        die(f"La API de Higgsfield pidió consultar otro host ({urlparse(url).netloc}): no se manda la llave ahí.")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Key {key}", "Accept": "application/json", "User-Agent": "5cero5-creativo",
                                          **({"Content-Type": "application/json"} if body is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        die(f"Higgsfield respondió {e.code} a {method} {urlparse(url).path}: {e.read()[:300].decode('utf-8', 'ignore')}")


def cmd_foto(a) -> None:
    d = pieza_dir(a)
    meta = lee_json(d / "pieza.json")
    if not meta.get("foto"):
        die("Esta pieza se creó sin foto. Si el brief pide foto, crea la pieza con 'nueva --foto'.")
    if meta.get("higgsfield"):
        die("Esta pieza ya tiene su foto generada (una por pieza). Si no sirve, termina y explícalo: no se genera otra.")
    contador = Path(a.trabajo) / ".fotos_de_la_sesion"
    usadas = int(contador.read_text()) if contador.exists() else 0
    if usadas >= FOTOS_POR_SESION:
        die(f"Ya se generaron {usadas} fotos en esta sesión (máximo {FOTOS_POR_SESION}).")
    prompt = a.prompt.strip()
    p = prompt.lower()
    if len(prompt) < 40:
        die("El prompt es muy corto (mínimo 40 caracteres): describe la escena, la luz y el encuadre.")
    if re.search(r"testimonio|cliente real|caso de éxito|customer|testimonial", p):
        die("El prompt pide un cliente, caso o testimonio (reglas.md §1 y §6).")
    if not (re.search(r"sin texto|no text", p) and re.search(r"sin logos|no logos", p)):
        die('El prompt debe pedir "sin texto" y "sin logos" (reglas.md §6).')
    # Se cuenta ANTES de pedir: si algo se cae a medias, no hay segunda generación por error.
    contador.write_text(str(usadas + 1))
    r = hf("POST", HF_API + HF_ENDPOINT, {"prompt": prompt})
    rid, status_url = r.get("request_id"), r.get("status_url")
    if not rid or not status_url:
        die(f"Higgsfield no regresó request_id y status_url: {json.dumps(r)[:200]}")
    meta["higgsfield"] = {"request_id": rid, "endpoint": HF_ENDPOINT, "estado": r.get("status", "queued")}
    escribe_json(d / "pieza.json", meta)
    (d / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    estado = r
    for _ in range(int(os.environ.get("HF_INTENTOS", "40"))):
        if estado.get("status") in ("completed", "failed", "nsfw", "canceled"):
            break
        time.sleep(float(os.environ.get("HF_ESPERA_S", "5")))
        estado = hf("GET", status_url)
    meta["higgsfield"]["estado"] = estado.get("status")
    escribe_json(d / "pieza.json", meta)
    if estado.get("status") != "completed":
        die(f"La foto terminó en '{estado.get('status')}' (request {rid}). No se pide otra: termina y explícalo.")
    url = ((estado.get("images") or [{}])[0] or {}).get("url")
    prueba_local = HF_API.startswith("http://127.0.0.1")  # solo las pruebas sirven la imagen sin https
    if not url or (urlparse(url).scheme != "https" and not prueba_local):
        die(f"Higgsfield no regresó la URL de la imagen (request {rid}).")
    # Descarga SIN la llave: el archivo vive en otro host.
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "5cero5-creativo"}), timeout=120) as resp:
            tipo = resp.headers.get_content_type()
            datos = resp.read(15 * 1024 * 1024 + 1)
    except Exception as e:  # noqa: BLE001
        die(f"No pude bajar la imagen de {urlparse(url).netloc} ({e}). Si es un host nuevo, hay que agregarlo a la red del entorno.")
    if tipo not in EXT_FOTO or len(datos) < 10_000 or len(datos) > 15 * 1024 * 1024:
        die(f"Lo que bajó no es una foto utilizable ({tipo}, {len(datos)} bytes).")
    destino = d / "fotos" / f"fondo.{EXT_FOTO[tipo]}"
    destino.write_bytes(datos)
    meta["higgsfield"].update(imagen_host=urlparse(url).netloc, sha1=hashlib.sha1(datos).hexdigest(), bytes=len(datos))
    escribe_json(d / "pieza.json", meta)
    h = (d / "plantillas" / "pieza.html").read_text(encoding="utf-8")
    h2 = re.sub(r'(<img class="foto" id="foto" src=")\.\./fotos/[\w.-]+(")', rf"\g<1>../fotos/{destino.name}\g<2>", h)
    (d / "plantillas" / "pieza.html").write_text(h2, encoding="utf-8")
    print(f"✓ Foto de Higgsfield guardada ({destino.name}, {len(datos) // 1024} KB, request {rid}). Prompt en prompt.txt.")


# ------------------------------------------------------------------ llenar
def cmd_llenar(a) -> None:
    d = pieza_dir(a)
    c = lee_json(d / "copia.json")
    falta = [k for k in CLAVES_COPIA if k not in c]
    extra = [k for k in c if k not in CLAVES_COPIA]
    if falta or extra:
        die(f"copia.json lleva exactamente {', '.join(CLAVES_COPIA)}. Faltan: {falta or '-'}; sobran: {extra or '-'}.")
    lineas = c["titular"] if isinstance(c["titular"], list) else [c["titular"]]
    lineas = [str(x).strip() for x in lineas if str(x).strip()]
    if not 1 <= len(lineas) <= 4:
        die("El titular va en 1 a 4 líneas (lista en copia.json).")
    for k in ("subtitulo", "nota"):
        if not str(c[k]).strip():
            die(f"copia.json: '{k}' está vacío.")
    esc = lambda t: html.escape(str(t).strip(), quote=False)
    h1 = "<br>".join(esc(x) for x in lineas[:-1]) + ("<br>" if len(lineas) > 1 else "") + f'<span class="marca">{esc(lineas[-1])}</span>'
    p = d / "plantillas" / "pieza.html"
    h = p.read_text(encoding="utf-8")
    for patron, valor in ((r'(<div class="kicker">).*?(</div>)', esc(c["kicker"])), (r"(<h1>).*?(</h1>)", h1),
                          (r'(<p class="sub">).*?(</p>)', esc(c["subtitulo"])), (r'(<div class="nota">).*?(</div>)', esc(c["nota"]))):
        h, n = re.subn(patron, lambda m, v=valor: m.group(1) + v + m.group(2), h, count=1, flags=re.S)
        if n != 1:
            die(f"No encontré el SLOT {patron!r} en la plantilla.")
    p.write_text(h, encoding="utf-8")
    print("✓ Copia escrita en los SLOT de la plantilla. Ahora corre 'revisar'.")


# ------------------------------------------------------------------ revisar
def renderiza(d: Path, ancho: int, alto: int) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        die("Falta Playwright: pip install playwright && python3 -m playwright install --with-deps chromium")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            pg = b.new_page(viewport={"width": ancho, "height": alto})
            pg.route("**/*", lambda r: r.continue_() if r.request.url.startswith("file://") else r.abort())  # nada externo
            pg.goto((d / "plantillas" / "pieza.html").as_uri())
            pg.wait_for_selector('body[data-listo="1"]', timeout=30000)
            datos = pg.evaluate("({f: document.body.dataset.fuentes, l: document.body.dataset.logo, o: document.body.dataset.foto, e: document.body.dataset.encimado})")
            fuentes = datos["f"] or ""
            if not all(x in fuentes for x in ("Anton", "IBM Plex Sans 400", "IBM Plex Sans 700")):
                die(f"Las fuentes de marca no cargaron: {fuentes}")
            if datos["l"] != "ok":
                die("El logo no cargó.")
            if datos["o"] not in (None, "ok"):
                die("La foto no cargó.")
            encimado = json.loads(datos["e"] or "null")
            if encimado is None:
                die("La plantilla no dice si sus textos se enciman (data-encimado): usa la plantilla del repo de marca v0.12.0 o más nueva.")
            if encimado:
                die(f"Se enciman {', '.join(encimado)}: acorta la copia (titular en menos líneas o palabras más cortas, subtítulo más corto) y vuelve a llenar y revisar.")
            return pg.screenshot(full_page=False)
        finally:
            b.close()


def cmd_revisar(a) -> None:
    d = pieza_dir(a)
    meta = lee_json(d / "pieza.json")
    marca = Path(a.marca)
    f = lee_json(marca / "tokens.json")["formatos"][meta["formato"]]
    if meta.get("foto") and not foto_actual(d):
        die("La pieza lleva foto y aún no hay foto: corre 'foto' primero.")
    copia = lee_json(d / "copia.json")
    html_txt = (d / "plantillas" / "pieza.html").read_text(encoding="utf-8")
    if 'class="marca"></span>' in html_txt or "<h1></h1>" in html_txt:
        die("La plantilla no tiene la copia: corre 'llenar' primero.")
    png = renderiza(d, f["ancho"], f["alto"])
    (d / "pieza.png").write_bytes(png)
    shutil.copy(d / "plantillas" / "pieza.html", d / "pieza.html")
    sys.path.insert(0, str(marca / "verificador"))
    try:
        from verificar import imprime, verificar  # type: ignore
    except ImportError:
        die(f"No encuentro el Verificador en {marca}/verificador.")
    tit = copia["titular"] if isinstance(copia["titular"], list) else [copia["titular"]]
    declarada = {**copia, "titular": " ".join(str(x).strip() for x in tit if str(x).strip())}
    prompt = (d / "prompt.txt").read_text(encoding="utf-8") if (d / "prompt.txt").exists() else None
    res = verificar(png, html_txt, marca, declarada, prompt=prompt)
    imprime(res)
    res["png_blob_sha"] = blob_sha(png)
    res["png_sha1"] = hashlib.sha1(png).hexdigest()
    res["formato_pedido"] = meta["formato"]
    escribe_json(d / "informe.json", res)
    if res.get("formato") != meta["formato"]:
        die(f"El PNG salió como {res.get('formato')}, no como {meta['formato']}.")
    if not res["aprobada"]:
        (d / ".revisado").unlink(missing_ok=True)
        die("El Verificador rechazó la pieza (arriba los bloqueos). Corrige la copia y vuelve a 'llenar' y 'revisar'.")
    (d / ".revisado").write_text(huella(d))
    print(f"\n✓ {a.campana}/{a.pieza} revisada. Mira {d / 'pieza.png'} antes de abrir el PR.")


# ------------------------------------------------------------------ abrir
def cmd_abrir(a) -> None:
    d = pieza_dir(a)
    marca_rev = d / ".revisado"
    if not marca_rev.exists() or marca_rev.read_text() != huella(d):
        die("La pieza cambió después de 'revisar' (o no se revisó). Corre 'revisar' otra vez.")
    meta = lee_json(d / "pieza.json")
    inf = lee_json(d / "informe.json")
    locales = para_subir(d)
    if not inf.get("aprobada") or inf.get("png_blob_sha") != blob_sha(locales["pieza.png"]):
        die("El informe no corresponde a este PNG o no está aprobado.")
    if meta.get("foto") and not ("prompt.txt" in locales and any(k.startswith("fotos/") for k in locales)):
        die("La pieza lleva foto: faltan la foto o prompt.txt.")
    pref = f"piezas/{a.campana}/{a.pieza}/"
    foto = " con foto de Higgsfield (ver prompt.txt; no es un cliente)" if meta.get("foto") else ""
    avisos = inf.get("avisos") or []
    cuerpo = lambda nueva, n: (a.cuerpo or "") + ("\n\n" if a.cuerpo else "") + \
        f"Abierto por el agente Creativo. {meta['formato']}{foto}. Solo cambia `{pref}` ({n} archivo(s)).\n\n" \
        f"Verificador de marca v{inf.get('repo_version')}: aprobada, {len(avisos)} aviso(s)" + \
        "".join(f"\n- {x.get('id')}: {x.get('detalle')}" for x in avisos[:8]) + \
        f"\n\nPara revisar: abre `{pref}pieza.png` en la pestaña de archivos.\n" \
        "Aprobar = fusionar este PR (Al). Subirla a Meta la hace Bonzo a mano, con la campaña en pausa."
    r = sube_carpeta(repo=REPO, pref=pref, locales=locales, rama_base=f"{a.campana}-{a.pieza}"[:60], ua="5cero5-agente-creativo",
                     mensaje=lambda nueva, n: f"{'Pieza nueva' if nueva else 'Pieza'} {a.campana}/{a.pieza} ({meta['formato']}): {a.titulo}",
                     cuerpo=cuerpo)
    out = {k: r[k] for k in ("pr_url", "pr_numero", "rama", "commit")}
    out.update(campana=a.campana, pieza=a.pieza, formato=meta["formato"], foto=bool(meta.get("foto")),
               png_blob_sha=inf["png_blob_sha"], archivos=r["archivos"])
    print(json.dumps(out, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trabajo", default="/tmp/creativo")
    ap.add_argument("--marca", default="/tmp/marca")
    sp = ap.add_subparsers(dest="cmd", required=True)

    def sub(nombre, f):
        p = sp.add_parser(nombre)
        p.add_argument("--campana", required=True)
        p.add_argument("--pieza", required=True)
        p.set_defaults(f=f)
        return p
    n = sub("nueva", cmd_nueva)
    n.add_argument("--formato", required=True, choices=FORMATOS)
    n.add_argument("--foto", action="store_true", help="solo si el brief pide foto")
    sub("foto", cmd_foto).add_argument("--prompt", required=True)
    sub("llenar", cmd_llenar)
    sub("revisar", cmd_revisar)
    b = sub("abrir", cmd_abrir)
    b.add_argument("--titulo", required=True)
    b.add_argument("--cuerpo")
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
