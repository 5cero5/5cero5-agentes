#!/usr/bin/env python3
"""Herramienta del agente Creativo: arma UNA pieza (post 4:5, post 1:1 o historia 9:16) con las plantillas del repo de
marca, la revisa con el Verificador y abre un PR en 5cero5-piezas. Nunca fusiona ni publica.

  python3 pr_pieza.py nueva   --campana poc-diagnostico --pieza post-agencia --formato post-4x5 [--foto]
  python3 pr_pieza.py foto    --campana ... --pieza ... --prompt "Fotografía editorial de ..., sin texto y sin logos"
  python3 pr_pieza.py foto    --campana ... --pieza ... --repo-id <id>          (foto del cliente tal cual, sin Higgsfield)
  python3 pr_pieza.py foto    --campana ... --pieza ... --referencia <id> --prompt "..."  (foto del cliente como referencia)
  python3 pr_pieza.py llenar  --campana ... --pieza ...      (escribe copia.json en los SLOT de la plantilla)
  python3 pr_pieza.py revisar --campana ... --pieza ...      (render con Playwright + Verificador de marca)
  python3 pr_pieza.py abrir   --campana ... --pieza ... --titulo "..." [--cuerpo "..."]
  python3 pr_pieza.py revisar-pr --campana ... --pieza ... --pr <n> --foto-ronda Igual|Editar|Nueva
                      [--cambios cambios.json] [--prompt "..."]   (ronda de cambios: commit nuevo en la rama del mismo PR)

Rutas: --trabajo /tmp/creativo (piezas en curso), --marca /tmp/marca (copia del repo de marca).
Variables: GITHUB_TOKEN (lo pone el harness; solo hacia api.github.com). HIGGSFIELD_API_KEY (solo para 'foto'; solo
hacia api.higgsfield.ai; nunca hacia la URL firmada donde se sube una imagen). Opcionales: GH_PIEZAS_REPO
(5cero5/5cero5-piezas), HF_ENDPOINT, HF_EDICION_ENDPOINT, GITHUB_API_BASE y HIGGSFIELD_API_BASE (solo pruebas).

Lo que se impone:
  - La copia la escribe la herramienta en los SLOT; el agente no edita el HTML a mano.
  - Foto: solo si la pieza se creó con --foto (el brief lo pide), una generación por pieza y dos por sesión como máximo
    (FOTOS_POR_SESION la puede bajar, nunca subir). Cada generación o edición que termina se cobra del saldo de Higgsfield.
  - Fotos del cliente: solo las de fotos/fotos.json del repo de marca montado (el del cliente), autorizadas y con el uso
    que se pide ("directo" para --repo-id, "referencia_ia" para --referencia y además personas=false).
  - Ronda (revisar-pr): parte de la punta de la rama del PR, que tiene que estar abierto y sin fusionar; cambia solo las
    claves de copia que trae --cambios y la foto según --foto-ronda (Igual no llama a Higgsfield y deja el mismo archivo);
    vuelve a revisar y hace UN commit en la misma rama. Nunca abre otro PR.
  - Fuentes, titular y resaltado salen del repo de marca: las fuentes que deben cargar son las de tokens.json con archivo
    (si la marca no trae archivos de fuente, no se exige ninguna) y la última línea va en .marca solo si la plantilla lo define.
  - 'abrir' se niega si la pieza no pasó 'revisar' en esta corrida o cambió después; sube solo piezas/<campaña>/<pieza>/
    con una lista fija de archivos; solo ramas agente/*; nunca main, nunca fusiona.
"""
from __future__ import annotations

import argparse
import hashlib
import math
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
from gh_pr import blob_sha, commit_en_rama, die, gh, lee_carpeta, repo_exclusivo, sube_carpeta  # noqa: E402

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
FORMATOS = ("post-4x5", "post-1x1", "historia-9x16")
REPO = os.environ.get("GH_PIEZAS_REPO", "5cero5/5cero5-piezas")
HF_API = os.environ.get("HIGGSFIELD_API_BASE", "https://api.higgsfield.ai")
HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "/higgsfield-ai/soul/v2/standard")
# Edición con instrucción e imagen de entrada (Editar en una ronda, y --referencia). Visto el 3 nov 2026 con /estimate (sin
# generar): pide image_urls (lista de URLs públicas), 0.040 USD por edición; no hay modelo con máscara en el catálogo.
HF_EDICION = os.environ.get("HF_EDICION_ENDPOINT", "/alibaba/qwen-image-3/edit")
FOTOS_RONDA = ("Igual", "Editar", "Nueva")
FOTOS_MAX = 2  # tope duro: ninguna variable lo sube
FOTOS_POR_SESION = max(0, min(FOTOS_MAX, int(os.environ.get("FOTOS_POR_SESION", "").strip() or FOTOS_MAX)
                                 if os.environ.get("FOTOS_POR_SESION", "").strip().isdigit() or not os.environ.get("FOTOS_POR_SESION", "").strip()
                                 else 0))  # un valor raro no sube el tope: lo deja en 0
EXT_FOTO = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
# Proporciones que acepta Higgsfield Soul v2 (soul/v2/standard). Con otra responde 400 (pasó con 21:9 el 3 nov 2026).
ASPECTOS = ("9:16", "16:9", "4:3", "3:4", "1:1", "2:3", "3:2")
# HF_ASPECTOS (opcional, separadas por coma) solo puede achicar la lista, nunca agregar una que v2 no acepte.
ASPECTOS_USO = tuple(x for x in ASPECTOS if not os.environ.get("HF_ASPECTOS", "").strip()
                     or x in {y.strip() for y in os.environ["HF_ASPECTOS"].split(",")})
CLAVES_COPIA = ("kicker", "titular", "subtitulo", "nota")
# Lo único que viaja al PR (más la foto, si la lleva).
SUBE = ("pieza.png", "pieza.html", "copia.json", "pieza.json", "informe.json")
UA = "5cero5-agente-creativo"


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


H1_PX = re.compile(r"(h1\s*\{[^}]*?font:\s*(?:\d{3}\s+)?)(\d+)(px)")
MARCA_CSS = re.compile(r"h1\s+\.marca\s*\{")


def fuentes_requeridas(tokens: dict) -> list[str]:
    """"Familia peso" de cada fuente de tokens.json que trae archivo en el repo de marca (las que la plantilla carga con
    @font-face). Una marca sin archivos de fuente (licencia sin aclarar) no exige ninguna: usa las del sistema."""
    out = []
    for rol in ("titular", "texto"):
        t = (tokens.get("tipografia") or {}).get(rol) or {}
        archivos = t.get("archivos") or ([t["archivo"]] if t.get("archivo") else [])
        if t.get("familia") and archivos:
            out += [f"{t['familia']} {p}" for p in (t.get("pesos") or [t.get("peso", 400)])]
    return out

AJUSTE_MIN = 0.70   # el titular puede bajar hasta 70 % del tamaño de la plantilla (reglas: se baja el tamaño, no se cambia la fuente)


def tam_h1(html_txt: str) -> int:
    m = H1_PX.search(html_txt)
    if not m:
        die("No encontré el tamaño del titular (h1) en la plantilla.")
    return int(m.group(2))


def con_tam_h1(html_txt: str, px: int) -> str:
    return H1_PX.sub(lambda m: f"{m.group(1)}{px}{m.group(3)}", html_txt, count=1)


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


def aspecto_de(html_txt: str, permitidos: tuple = ASPECTOS) -> str | None:
    """La proporción permitida más cercana al marco .foto de la plantilla (ancho/alto en px del CSS). La foto llega con una
    forma parecida a su marco y object-fit: cover recorta el resto (21:9 → 16:9, 4:5 → 3:4). Sin marco legible: 4:3.
    None si no hay ninguna permitida: entonces no se llama a Higgsfield."""
    if not permitidos:
        return None
    m = re.search(r"\.foto\s*\{[^}]*?width:\s*(\d+)px;[^}]*?height:\s*(\d+)px", html_txt)
    if not m or not int(m.group(2)):
        return "4:3" if "4:3" in permitidos else permitidos[0]
    r = math.log(int(m.group(1)) / int(m.group(2)))
    return min(permitidos, key=lambda x: abs(math.log(int(x.split(':')[0]) / int(x.split(':')[1])) - r))


def contador_fotos(a) -> tuple[Path, int]:
    contador = Path(a.trabajo) / ".fotos_de_la_sesion"
    usadas = int(contador.read_text()) if contador.exists() else 0
    if usadas >= FOTOS_POR_SESION:
        die(f"Ya se generaron {usadas} fotos en esta sesión (máximo {FOTOS_POR_SESION}).")
    return contador, usadas


def revisa_prompt(prompt: str) -> str:
    prompt = prompt.strip()
    p = prompt.lower()
    if len(prompt) < 40:
        die("El prompt es muy corto (mínimo 40 caracteres): describe la escena, la luz y el encuadre.")
    if re.search(r"testimonio|cliente real|caso de éxito|customer|testimonial", p):
        die("El prompt pide un cliente, caso o testimonio (reglas.md §1 y §6).")
    if not (re.search(r"sin texto|no text", p) and re.search(r"sin logos|no logos", p)):
        die('El prompt debe pedir "sin texto" y "sin logos" (reglas.md §6).')
    return prompt


def foto_del_cliente(marca: Path, fid: str, uso: str) -> tuple[dict, Path]:
    """La foto <fid> de fotos/fotos.json del repo de marca montado (el del cliente). Falla cerrado si no existe, no está
    autorizada, su uso no incluye el pedido o, como referencia para IA, tiene personas (o no lo dice)."""
    idx = marca / "fotos" / "fotos.json"
    if not idx.exists():
        die("El repo de marca no tiene fotos/fotos.json: no hay fotos del cliente.")
    datos = lee_json(idx)
    fotos = datos if isinstance(datos, list) else datos.get("fotos", [])
    f = next((x for x in fotos if isinstance(x, dict) and x.get("id") == fid), None)
    if not f:
        die(f"La foto {fid!r} no está en fotos/fotos.json del repo de marca de este cliente.")
    if not f.get("autorizo"):
        die(f"La foto {fid!r} no dice quién autorizó su uso (autorizo).")
    if uso not in (f.get("uso") or []):
        die(f"La foto {fid!r} no se puede usar como {uso} (uso: {', '.join(f.get('uso') or []) or 'ninguno'}).")
    if uso == "referencia_ia" and f.get("personas") is not False:
        die(f"La foto {fid!r} tiene personas (o no lo dice): no se manda a un modelo de IA.")
    base = (marca / "fotos").resolve()
    archivo = (base / str(f.get("archivo") or "")).resolve()
    if base not in archivo.parents or not archivo.is_file() or archivo.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
        die(f"El archivo de la foto {fid!r} no está en fotos/ o no es jpg, png o webp.")
    return f, archivo


def pon_foto(d: Path, datos: bytes, ext: str) -> Path:
    """Deja la foto como fotos/fondo.<ext> (borra la anterior) y apunta la plantilla a ella."""
    for viejo in (d / "fotos").glob("fondo.*"):
        viejo.unlink()
    destino = d / "fotos" / f"fondo.{ext}"
    destino.write_bytes(datos)
    p = d / "plantillas" / "pieza.html"
    h = p.read_text(encoding="utf-8")
    p.write_text(re.sub(r'(<img class="foto" id="foto" src=")\.\./fotos/[\w.-]+(")', rf"\g<1>../fotos/{destino.name}\g<2>", h), encoding="utf-8")
    return destino


def sube_a_higgsfield(datos: bytes, tipo: str) -> str:
    """Sube una imagen para usarla de entrada: URL firmada de Higgsfield y PUT del archivo SIN la llave (otro host).
    Devuelve la URL pública que se pasa en image_urls."""
    r = hf("POST", HF_API + "/files/generate-upload-url", {"content_type": tipo})
    subir, publica = r.get("upload_url"), r.get("public_url")
    prueba_local = HF_API.startswith("http://127.0.0.1")
    if not subir or not publica or (urlparse(subir).scheme != "https" and not prueba_local):
        die(f"Higgsfield no regresó upload_url y public_url: {json.dumps(r)[:200]}")
    enc = {k: v for k, v in (r.get("upload_headers") or {}).items() if k.lower() != "authorization"}
    try:
        with urllib.request.urlopen(urllib.request.Request(subir, data=datos, method="PUT", headers={"User-Agent": "5cero5-creativo", **enc}), timeout=120):
            pass
    except Exception as e:  # noqa: BLE001
        die(f"No pude subir la imagen a {urlparse(subir).netloc} ({e}). Si es un host nuevo, hay que agregarlo a la red del entorno.")
    return publica


def pide_a_higgsfield(d: Path, meta: dict, endpoint: str, body: dict, prompt: str, extra: dict) -> None:
    """Una solicitud (generar o editar), espera a que termine y deja la foto en fotos/. Se registra en pieza.json → higgsfield
    con el blob_sha del archivo (el harness lo compara con el PR). La anterior, si había, queda en fotos_anteriores."""
    r = hf("POST", HF_API + endpoint, body)
    rid, status_url = r.get("request_id"), r.get("status_url")
    if not rid or not status_url:
        die(f"Higgsfield no regresó request_id y status_url: {json.dumps(r)[:200]}")
    if meta.get("higgsfield"):
        meta.setdefault("fotos_anteriores", []).append(meta["higgsfield"])
    meta["higgsfield"] = {"request_id": rid, "endpoint": endpoint, **extra, "estado": r.get("status", "queued")}
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
    destino = pon_foto(d, datos, EXT_FOTO[tipo])
    meta["higgsfield"].update(imagen_host=urlparse(url).netloc, sha1=hashlib.sha1(datos).hexdigest(), bytes=len(datos),
                              blob_sha=blob_sha(datos))  # el harness lo compara con fotos/ del PR al cerrar
    meta.pop("foto_cliente", None)
    escribe_json(d / "pieza.json", meta)
    print(f"✓ Foto de Higgsfield guardada ({destino.name}, {len(datos) // 1024} KB, request {rid}). Prompt en prompt.txt.")


ALT_FOTO = re.compile(r'(<img class="foto" id="foto" src="[^"]*" alt=")([^"]*)(")')


def pon_alt(d: Path, alt: str) -> None:
    ph = d / "plantillas" / "pieza.html"
    ph.write_text(ALT_FOTO.sub(lambda m: m.group(1) + alt + m.group(3), ph.read_text(encoding="utf-8")), encoding="utf-8")


def alt_de_cliente(d: Path, descripcion: str, personas) -> None:
    """La plantilla dice que la foto es de IA; una foto del cliente no lo es: el alt pasa a ser su descripción de fotos.json.
    Sin personas (personas=false), además dice que no es un cliente ni un testimonio, que entonces es cierto."""
    extra = " No es un cliente, un caso ni un testimonio." if personas is False else ""
    pon_alt(d, html.escape(f"Foto de la marca: {descripcion}.{extra}", quote=True))


def foto_repo(a, d: Path, meta: dict) -> None:
    """Foto del cliente tal cual (uso directo): se copia del repo de marca, sin Higgsfield y sin contar contra el tope."""
    f, archivo = foto_del_cliente(Path(a.marca), a.repo_id, "directo")
    datos = archivo.read_bytes()
    ext = "jpg" if archivo.suffix.lower() == ".jpeg" else archivo.suffix.lower().lstrip(".")
    destino = pon_foto(d, datos, ext)
    alt_de_cliente(d, f.get("descripcion") or f["id"], f.get("personas"))
    if meta.get("higgsfield"):
        meta.setdefault("fotos_anteriores", []).append(meta.pop("higgsfield"))
    meta["higgsfield"] = None
    meta["foto_cliente"] = {"id": f["id"], "archivo": f"fotos/{f['archivo']}", "uso": "directo", "blob_sha": blob_sha(datos),
                            "descripcion": f.get("descripcion") or "", "personas": f.get("personas")}
    escribe_json(d / "pieza.json", meta)
    # El Verificador de marca pide el prompt guardado junto a la foto: aquí va de dónde sale (no hay IA).
    (d / "prompt.txt").write_text(f"Foto del cliente {f['id']} (repo de marca, fotos/{f['archivo']}), usada tal cual, sin IA. "
                                  f"{f.get('descripcion', '')}".strip() + "\n", encoding="utf-8")
    print(f"✓ Foto del cliente {f['id']} puesta tal cual ({destino.name}). Sin Higgsfield.")


def cmd_foto(a) -> None:
    d = pieza_dir(a)
    meta = lee_json(d / "pieza.json")
    if not meta.get("foto"):
        die("Esta pieza se creó sin foto. Si el brief pide foto, crea la pieza con 'nueva --foto'.")
    if meta.get("ronda"):
        die("En una ronda la foto la cambia 'revisar-pr' según --foto-ronda.")
    if meta.get("higgsfield") or meta.get("foto_cliente"):
        die("Esta pieza ya tiene su foto (una por pieza). Si no sirve, termina y explícalo: no se pone otra.")
    if a.repo_id:
        return foto_repo(a, d, meta)
    if not a.prompt:
        die("Falta --prompt.")
    prompt = revisa_prompt(a.prompt)
    if a.referencia:
        f, archivo = foto_del_cliente(Path(a.marca), a.referencia, "referencia_ia")
        contador, usadas = contador_fotos(a)
        contador.write_text(str(usadas + 1))  # se cuenta ANTES de pedir
        tipo = {".png": "image/png", ".webp": "image/webp"}.get(archivo.suffix.lower(), "image/jpeg")
        url = sube_a_higgsfield(archivo.read_bytes(), tipo)
        return pide_a_higgsfield(d, meta, HF_EDICION, {"prompt": prompt, "image_urls": [url]}, prompt, {"referencia": f["id"]})
    # La proporción se elige y se valida ANTES de contar y de llamar: con una que Soul v2 no acepta responde 400.
    aspecto = aspecto_de((d / "plantillas" / "pieza.html").read_text(encoding="utf-8"), ASPECTOS_USO)
    if aspecto not in ASPECTOS:
        die(f"No hay una proporción válida para Higgsfield (permitidas: {', '.join(ASPECTOS_USO) or 'ninguna'}). No se pidió la foto.")
    # Se cuenta ANTES de pedir: si algo se cae a medias, no hay segunda generación por error.
    contador, usadas = contador_fotos(a)
    contador.write_text(str(usadas + 1))
    pide_a_higgsfield(d, meta, HF_ENDPOINT, {"prompt": prompt, "aspect_ratio": aspecto}, prompt, {"aspect_ratio": aspecto})


# ------------------------------------------------------------------ llenar
def cmd_llenar(a) -> None:
    d = pieza_dir(a)
    c = lee_json(d / "copia.json")
    falta = [k for k in CLAVES_COPIA if k not in c and k != "nota"]
    extra = [k for k in c if k not in CLAVES_COPIA]
    if falta or extra:
        die(f"copia.json lleva exactamente {', '.join(CLAVES_COPIA)}. Faltan: {falta or '-'}; sobran: {extra or '-'}.")
    lineas = c["titular"] if isinstance(c["titular"], list) else [c["titular"]]
    lineas = [str(x).strip() for x in lineas if str(x).strip()]
    if not 1 <= len(lineas) <= 4:
        die("El titular va en 1 a 4 líneas (lista en copia.json).")
    if not str(c["subtitulo"]).strip():
        die("copia.json: 'subtitulo' está vacío.")
    # La nota es opcional: vacía, su SLOT queda vacío.
    esc = lambda t: html.escape(str(t).strip(), quote=False)
    p = d / "plantillas" / "pieza.html"
    h = p.read_text(encoding="utf-8")
    ultima = f'<span class="marca">{esc(lineas[-1])}</span>' if MARCA_CSS.search(h) else esc(lineas[-1])
    h1 = "<br>".join(esc(x) for x in lineas[:-1]) + ("<br>" if len(lineas) > 1 else "") + ultima
    meta = lee_json(d / "pieza.json")
    original = Path(a.marca) / meta["plantilla"]
    if original.exists():  # cada llenado empieza con el titular al tamaño de la plantilla
        h = con_tam_h1(h, tam_h1(original.read_text(encoding="utf-8")))
    for patron, valor in ((r'(<div class="kicker">).*?(</div>)', esc(c["kicker"])), (r"(<h1>).*?(</h1>)", h1),
                          (r'(<p class="sub">).*?(</p>)', esc(c["subtitulo"])), (r'(<div class="nota">).*?(</div>)', esc(c.get("nota") or ""))):
        h, n = re.subn(patron, lambda m, v=valor: m.group(1) + v + m.group(2), h, count=1, flags=re.S)
        if n != 1:
            die(f"No encontré el SLOT {patron!r} en la plantilla.")
    p.write_text(h, encoding="utf-8")
    print("✓ Copia escrita en los SLOT de la plantilla. Ahora corre 'revisar'.")


# ------------------------------------------------------------------ revisar
def renderiza(d: Path, ancho: int, alto: int, requeridas: list[str]) -> tuple[bytes, list[str]]:
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
            if not all(x in fuentes for x in requeridas):
                die(f"Las fuentes de marca no cargaron: faltan {[x for x in requeridas if x not in fuentes]} (cargaron {fuentes})")
            if datos["l"] != "ok":
                die("El logo no cargó.")
            if datos["o"] not in (None, "ok"):
                die("La foto no cargó.")
            encimado = json.loads(datos["e"] or "null")
            if encimado is None:
                die("La plantilla no dice si sus textos se enciman (data-encimado): usa la plantilla del repo de marca v0.12.0 o más nueva.")
            return pg.screenshot(full_page=False), encimado
        finally:
            b.close()


def cmd_revisar(a) -> None:
    d = pieza_dir(a)
    (d / ".revisado").unlink(missing_ok=True)  # una revisión fallida nunca deja aprobada la anterior
    meta = lee_json(d / "pieza.json")
    marca = Path(a.marca)
    tokens = lee_json(marca / "tokens.json")
    f = tokens["formatos"][meta["formato"]]
    requeridas = fuentes_requeridas(tokens)
    if meta.get("foto") and not foto_actual(d):
        die("La pieza lleva foto y aún no hay foto: corre 'foto' primero.")
    copia = lee_json(d / "copia.json")
    html_txt = (d / "plantillas" / "pieza.html").read_text(encoding="utf-8")
    sub = re.search(r'<p class="sub">(.*?)</p>', html_txt, flags=re.S)
    if not str(copia.get("subtitulo", "")).strip() or not sub or sub.group(1).strip() != html.escape(str(copia["subtitulo"]).strip(), quote=False):
        die("La plantilla no tiene la copia: corre 'llenar' primero.")
    # Si el titular se encima, se baja su tamaño (como dice la plantilla) hasta 70 % del original; nada más se mueve.
    plantilla_html = d / "plantillas" / "pieza.html"
    inicial = tam_h1(html_txt)
    minimo = int(tam_h1((marca / meta["plantilla"]).read_text(encoding="utf-8")) * AJUSTE_MIN) if (marca / meta["plantilla"]).exists() else int(inicial * AJUSTE_MIN)
    px = inicial
    while True:
        png, encimado = renderiza(d, f["ancho"], f["alto"], requeridas)
        if not encimado:
            break
        if not all("titular" in e for e in encimado) or px <= minimo:
            die(f"Se enciman {', '.join(encimado)}" + (f" aun con el titular a {px} px (mínimo {minimo})" if px <= minimo else "") +
                ": acorta la copia (titular en menos líneas o palabras más cortas, subtítulo más corto) y vuelve a llenar y revisar.")
        px = max(minimo, int(px * 0.92))
        html_txt = con_tam_h1(html_txt, px)
        plantilla_html.write_text(html_txt, encoding="utf-8")
    if px != inicial:
        print(f"· Titular ajustado de {inicial} a {px} px para que no se encime.")
        meta["titular_px"] = px
        escribe_json(d / "pieza.json", meta)
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
    r = sube_carpeta(repo=a.repo or REPO, exclusivo=bool(a.repo), pref=pref, locales=locales, rama_base=f"{a.campana}-{a.pieza}"[:60], ua=UA,
                     mensaje=lambda nueva, n: f"{'Pieza nueva' if nueva else 'Pieza'} {a.campana}/{a.pieza} ({meta['formato']}): {a.titulo}",
                     cuerpo=cuerpo)
    out = {k: r[k] for k in ("pr_url", "pr_numero", "rama", "commit")}
    out.update(campana=a.campana, pieza=a.pieza, formato=meta["formato"], foto=bool(meta.get("foto")),
               png_blob_sha=inf["png_blob_sha"], archivos=r["archivos"])
    print(json.dumps(out, ensure_ascii=False))


# ------------------------------------------------------------------ revisar-pr (ronda de cambios)
def pr_de_la_pieza(a, repo: str, pref: str) -> dict:
    """El PR de la ronda: abierto, sin fusionar, de agente/* a main en este repo y solo con la carpeta de la pieza."""
    if a.repo:
        repo_exclusivo(repo, UA)
    pr = gh("GET", f"/repos/{repo}/pulls/{a.pr}", None, UA)
    mal = []
    if pr.get("state") != "open":
        mal.append(f"está {pr.get('state')}")
    if pr.get("merged") or pr.get("merged_at"):
        mal.append("ya está fusionado")
    if (pr.get("base") or {}).get("ref") != "main":
        mal.append("no va a main")
    if not str((pr.get("head") or {}).get("ref", "")).startswith("agente/"):
        mal.append("su rama no es agente/*")
    if str(((pr.get("head") or {}).get("repo") or {}).get("full_name", "")).lower() != repo.lower():
        mal.append("su rama es de otro repo")
    fuera = [f.get("filename") for f in gh("GET", f"/repos/{repo}/pulls/{a.pr}/files?per_page=100", None, UA)
             if not str(f.get("filename", "")).startswith(pref)]
    if fuera:
        mal.append(f"cambia archivos fuera de {pref}: {', '.join(fuera[:3])}")
    if mal:
        die(f"El PR #{a.pr} no admite una ronda: {'; '.join(mal)}. No se escribe nada.")
    return pr


def prepara_ronda(a, d: Path, pref: str, repo: str, pr: dict) -> None:
    """Rearma la pieza desde la punta de la rama del PR: su copia, su foto y su pieza.json, con la plantilla del repo de marca."""
    head = pr["head"]["sha"]
    archivos = lee_carpeta(repo=repo, ref=head, pref=pref, ua=UA)
    if not {"pieza.json", "copia.json"} <= set(archivos):
        die(f"La rama del PR no trae pieza.json y copia.json en {pref}.")
    meta = json.loads(archivos["pieza.json"])
    if meta.get("campana") != a.campana or meta.get("pieza") != a.pieza or meta.get("formato") not in FORMATOS:
        die("pieza.json de la rama es de otra pieza o de un formato desconocido.")
    marca = Path(a.marca)
    if not (marca / str(meta.get("plantilla", ""))).is_file():
        die(f"El repo de marca ya no tiene la plantilla {meta.get('plantilla')}.")
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    for sub in ("fonts", "logos"):
        shutil.copytree(marca / sub, d / sub)
    (d / "fotos").mkdir()
    (d / "plantillas").mkdir()
    shutil.copy(marca / meta["plantilla"], d / "plantillas" / "pieza.html")
    (d / "copia.json").write_bytes(archivos["copia.json"])
    (d / ".copia_original.json").write_bytes(archivos["copia.json"])
    if "prompt.txt" in archivos:
        (d / "prompt.txt").write_bytes(archivos["prompt.txt"])
    fotos = sorted(k for k in archivos if re.fullmatch(r"fotos/fondo\.(jpg|jpeg|png|webp)", k))
    if fotos:
        pon_foto(d, archivos[fotos[0]], fotos[0].rsplit(".", 1)[1])
        if meta.get("foto_cliente"):
            alt_de_cliente(d, meta["foto_cliente"].get("descripcion") or meta["foto_cliente"].get("id", ""), meta["foto_cliente"].get("personas"))
    meta.pop("titular_px", None)
    meta["ronda"] = {"pr": a.pr, "rama": pr["head"]["ref"], "head": head, "foto": a.foto_ronda,
                     "foto_antes": blob_sha(archivos[fotos[0]]) if fotos else None, "foto_hecha": False}
    escribe_json(d / "pieza.json", meta)
    print(f"· Pieza rearmada desde {pr['head']['ref']} ({head[:7]}).")


def cmd_revisar_pr(a) -> None:
    d = pieza_dir(a)
    pref = f"piezas/{a.campana}/{a.pieza}/"
    repo = a.repo or REPO
    pr = pr_de_la_pieza(a, repo, pref)
    head = pr["head"]["sha"]
    previa = (lee_json(d / "pieza.json").get("ronda") or {}) if (d / "pieza.json").exists() else {}
    # Un reintento de la misma ronda (por ejemplo, tras un rechazo del Verificador) no vuelve a bajar ni a pedir la foto.
    if not (previa.get("pr") == a.pr and previa.get("head") == head and previa.get("foto") == a.foto_ronda):
        prepara_ronda(a, d, pref, repo, pr)
    meta = lee_json(d / "pieza.json")
    # Solo los cambios: la copia de la rama con encima las claves que trae --cambios.
    cambios = lee_json(Path(a.cambios)) if a.cambios else {}
    if not isinstance(cambios, dict) or [k for k in cambios if k not in CLAVES_COPIA]:
        die(f"--cambios lleva solo claves de copia ({', '.join(CLAVES_COPIA)}).")
    escribe_json(d / "copia.json", {**lee_json(d / ".copia_original.json"), **cambios})
    ronda = meta["ronda"]
    if a.foto_ronda != "Igual" and not meta.get("foto"):
        die("La pieza no lleva foto: la ronda va con Foto en la ronda = Igual.")
    if a.foto_ronda != "Igual" and not ronda.get("foto_hecha"):
        if not a.prompt:
            die("Falta --prompt: en Editar, los cambios pedidos para la foto; en Nueva, el prompt de la foto nueva.")
        if a.foto_ronda == "Editar":
            instr = a.prompt.strip()
            if len(instr) < 10 or re.search(r"testimonio|cliente real|caso de éxito|customer|testimonial", instr.lower()):
                die("La instrucción de edición es muy corta o pide un cliente, caso o testimonio.")
            instr += " Sin agregar texto ni logos."
            actual = foto_actual(d)
            if not actual:
                die("La pieza no tiene foto que editar.")
            cliente = meta.get("foto_cliente")
            if cliente:  # editar con IA una foto del cliente es usarla como referencia: tiene que permitirlo y no tener personas
                foto_del_cliente(Path(a.marca), cliente.get("id", ""), "referencia_ia")
            contador, usadas = contador_fotos(a)
            contador.write_text(str(usadas + 1))
            tipo = {".png": "image/png", ".webp": "image/webp"}.get(actual.suffix.lower(), "image/jpeg")
            url = sube_a_higgsfield(actual.read_bytes(), tipo)
            pide_a_higgsfield(d, meta, HF_EDICION, {"prompt": instr, "image_urls": [url]}, instr, {"edita": ronda.get("foto_antes")})
            if cliente:
                alt_de_cliente(d, f"{cliente.get('descripcion') or cliente.get('id')} (editada con IA)", cliente.get("personas"))
        else:
            prompt = revisa_prompt(a.prompt)
            aspecto = aspecto_de((d / "plantillas" / "pieza.html").read_text(encoding="utf-8"), ASPECTOS_USO)
            if aspecto not in ASPECTOS:
                die("No hay una proporción válida para Higgsfield. No se pidió la foto.")
            contador, usadas = contador_fotos(a)
            contador.write_text(str(usadas + 1))
            pide_a_higgsfield(d, meta, HF_ENDPOINT, {"prompt": prompt, "aspect_ratio": aspecto}, prompt, {"aspect_ratio": aspecto})
            m = ALT_FOTO.search((Path(a.marca) / meta["plantilla"]).read_text(encoding="utf-8"))
            if m:  # foto nueva de IA: el alt vuelve a ser el de la plantilla
                pon_alt(d, m.group(2))
        meta = lee_json(d / "pieza.json")
        meta["ronda"]["foto_hecha"] = True
        escribe_json(d / "pieza.json", meta)
    cmd_llenar(a)
    cmd_revisar(a)
    meta = lee_json(d / "pieza.json")
    if a.foto_ronda == "Igual" and meta.get("foto"):
        f = foto_actual(d)
        if not f or blob_sha(f.read_bytes()) != meta["ronda"]["foto_antes"]:
            die("Foto en la ronda = Igual y la foto cambió. No se escribe nada.")
    if (d / ".revisado").read_text() != huella(d):
        die("La pieza cambió después de revisar.")
    titulo = (a.titulo or "cambios pedidos").strip()
    r = commit_en_rama(repo=repo, pref=pref, locales=para_subir(d), rama=meta["ronda"]["rama"], head=head, ua=UA,
                       mensaje=f"Ronda {a.campana}/{a.pieza} ({meta['formato']}): {titulo}")
    inf = lee_json(d / "informe.json")
    print(json.dumps({"pr_url": pr.get("html_url"), "pr_numero": a.pr, "rama": r["rama"], "commit": r["commit"],
                      "campana": a.campana, "pieza": a.pieza, "formato": meta["formato"], "foto": bool(meta.get("foto")),
                      "ronda": True, "foto_ronda": a.foto_ronda, "png_blob_sha": inf["png_blob_sha"], "archivos": r["archivos"]},
                     ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="org/repo de piezas del cliente; con él, el token tiene que ser exclusivo de ese repo")
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
    fo = sub("foto", cmd_foto)
    fo.add_argument("--prompt")
    fo.add_argument("--repo-id", help="foto del cliente (fotos/fotos.json del repo de marca), tal cual y sin Higgsfield")
    fo.add_argument("--referencia", help="foto del cliente como referencia para el modelo de edición (con --prompt)")
    sub("llenar", cmd_llenar)
    sub("revisar", cmd_revisar)
    b = sub("abrir", cmd_abrir)
    b.add_argument("--titulo", required=True)
    b.add_argument("--cuerpo")
    rp = sub("revisar-pr", cmd_revisar_pr)
    rp.add_argument("--pr", type=int, required=True)
    rp.add_argument("--foto-ronda", required=True, choices=FOTOS_RONDA)
    rp.add_argument("--cambios", help="JSON con solo las claves de copia que cambian")
    rp.add_argument("--prompt")
    rp.add_argument("--titulo")
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
