#!/usr/bin/env python3
"""Landing de captura: construir -> borrador -> promover (-> revertir). Todo desde la terminal.

  python3 landing.py construir --ruta landingtest    arma el sitio (lo publicado antes + la landing en /landingtest),
                                                    lo revisa con el Verificador y guarda su manifiesto
  python3 landing.py borrador                       sube la carpeta a Netlify como borrador y verifica byte por byte
  python3 landing.py promover --deploy ID ...       APROBACIÓN: publica ese borrador en producción
  python3 landing.py revertir                       regresa al deploy que estaba publicado antes
  python3 landing.py estado

Variables: NETLIFY_TOKEN, NETLIFY_SITE_ID. Opcionales: MARCA_REPO (carpeta del repo 5cero5-marca; por defecto ../5cero5-marca),
NETLIFY_API_BASE (solo para pruebas con servidor falso).

Reglas que este script se impone:
  - Solo promueve un borrador que ÉL subió y verificó, con exactamente los archivos del manifiesto.
  - Antes de publicar, vuelve a revisar la carpeta con el Verificador y compara los SHA1 que Netlify tiene contra el manifiesto.
  - Publicar pide escribir una frase exacta. Nada de --yes.
  - Guarda el deploy anterior para poder revertir, y después de publicar verifica la URL pública.
  - Un deploy de Netlify es el sitio COMPLETO. Para que la landing viva en /<ruta> sin borrar lo que hay en la raíz,
    'construir' baja los archivos del deploy base (por defecto, el que estaba publicado antes de la primera
    promoción) y verifica cada uno contra el SHA1 que Netlify tiene registrado.
  - Todo el sitio sale con noindex (cabecera X-Robots-Tag en _headers y robots.txt).
"""
from __future__ import annotations

import argparse
import hashlib
import zipfile
import json
import os
import posixpath
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
DIST = HERE / "landing_dist"
MANIFIESTO = HERE / ".manifiesto_landing.json"
ESTADO = HERE / ".estado_landing.json"
CAPTURAS = HERE / "landing_capturas"
FUNCS = HERE / "landing_funciones"      # zips de las funciones de Netlify (fuera de la carpeta del sitio)
RUTA_FUNCION = ".netlify/functions/prospecto"
NF_BASE = os.environ.get("NETLIFY_API_BASE", "https://api.netlify.com/api/v1")
UA = "5cero5-poc (landing)"
ARCHIVOS_FIJOS = ("index.html", "gracias.html", "aviso.html", "estilo.css")


def step(m: str) -> None:
    print(f"\n▸ {m}", flush=True)


def die(m: str) -> None:
    print(f"\n✗ {m}")
    sys.exit(1)


def need(v: str) -> str:
    x = os.environ.get(v, "").strip()
    if not x:
        die(f"Falta la variable de entorno {v}.")
    return x


def sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def repo_dir() -> Path:
    r = Path(os.environ.get("MARCA_REPO", HERE.parent / "5cero5-marca" if (HERE.parent / "5cero5-marca").exists() else HERE / "5cero5-marca"))
    if not (r / "tokens.json").exists():
        die(f"No encuentro el repo de marca en {r}. Pon MARCA_REPO=/ruta/a/5cero5-marca (versión 0.4.0 o mayor).")
    return r


def carga_estado() -> dict:
    return json.loads(ESTADO.read_text()) if ESTADO.exists() else {}


def guarda_estado(e: dict) -> None:
    ESTADO.write_text(json.dumps(e, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- Netlify
class NF:
    def __init__(self, token: str, site: str):
        self.site = site
        self.c = httpx.Client(base_url=NF_BASE, timeout=60, headers={"Authorization": f"Bearer {token}", "User-Agent": UA, "Accept": "application/json"})

    def req(self, m: str, path: str, **kw) -> httpx.Response:
        r = self.c.request(m, path, **kw)
        return r

    def ok(self, m: str, path: str, esperados=(200, 201), **kw):
        r = self.req(m, path, **kw)
        if r.status_code == 401:
            die(f"Netlify rechazó el token (401) en {m} {path}. El token está mal copiado, venció o fue revocado. "
                "Revisa NETLIFY_TOKEN (sin comillas extra ni espacios) o genera uno nuevo en Netlify > User settings > Applications.")
        if r.status_code == 404 and path.startswith("/sites/"):
            die(f"Netlify no encuentra el sitio ({path}). O NETLIFY_SITE_ID está mal, o el token es de una cuenta que no es del equipo de poc505.")
        if r.status_code not in esperados:
            die(f"Netlify respondió {r.status_code} a {m} {path}: {r.text[:300]}")
        return r.json() if r.text else {}

    def sitio(self) -> dict:
        return self.ok("GET", f"/sites/{self.site}")

    def nombre(self) -> str:
        return self.sitio().get("name", "")

    def baja_archivo(self, id_: str, ruta: str, sha: str) -> bytes | None:
        """Baja un archivo de un deploy y solo lo acepta si su SHA1 es el que Netlify registró.
        Primero por la API (formato crudo); si no, por la URL fija del deploy."""
        r = self.req("GET", f"/deploys/{id_}/files/{ruta}", headers={"Accept": "application/vnd.bitballoon.v1.raw"})
        if r.status_code == 200 and sha1(r.content) == sha:
            return r.content
        try:
            u = f"https://{id_}--{self.nombre()}.netlify.app/{ruta}"
            r = httpx.get(u, timeout=60, headers={"User-Agent": UA})
            if r.status_code == 200 and sha1(r.content) == sha:
                return r.content
        except httpx.HTTPError:
            pass
        return None

    def publicado(self) -> str | None:
        return (self.sitio().get("published_deploy") or {}).get("id")

    def deploy(self, id_: str) -> dict:
        return self.ok("GET", f"/deploys/{id_}")

    def archivos(self, id_: str, esperados=()) -> dict[str, str]:
        """SHA1 que Netlify registró por archivo. Si la lista no trae alguno (pasa con subcarpetas),
        lo pide uno por uno: ese endpoint devuelve la ficha del archivo, no su contenido."""
        out = {}
        for f in self.ok("GET", f"/deploys/{id_}/files", params={"per_page": 1000}):
            k = (f.get("id") or f.get("path") or "").lstrip("/")
            out[k] = f.get("sha")
        for k in esperados:
            if not out.get(k):
                r = self.req("GET", f"/deploys/{id_}/files/{k}")
                if r.status_code == 200:
                    try:
                        out[k] = r.json().get("sha")
                    except ValueError:
                        out[k] = None
        self.ultima_lista = sorted(out)
        return out

    def espera(self, id_: str, estados=("ready",), intentos=24, pausa=5) -> dict:
        d = {}
        for _ in range(intentos):
            d = self.deploy(id_)
            if d.get("state") in estados:
                return d
            if d.get("state") in ("error", "rejected"):
                die(f"El deploy {id_} quedó en {d.get('state')}: {d.get('error_message')}")
            time.sleep(pausa)
        die(f"El deploy {id_} no llegó a {estados} (último estado: {d.get('state')}).")


# ---------------------------------------------------------------- funciones
def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def zip_funcion(fuente: Path, nombre: str, destino: Path, extras: dict[str, bytes] | None = None) -> bytes:
    """Zip determinista (fechas fijas) con <nombre>.js en la raíz, como lo espera Netlify con runtime=js,
    más los archivos que la función lee junto a ella (por ejemplo, el HTML del correo W1)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destino, "w") as z:
        for n, datos in [(f"{nombre}.js", fuente.read_bytes())] + sorted((extras or {}).items()):
            info = zipfile.ZipInfo(n, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, datos)
    return destino.read_bytes()


def verifica_correo_de_funcion(repo: Path, rel: str) -> bytes:
    f = repo / rel
    if not f.exists():
        die(f"Falta {rel} en el repo de marca.")
    sys.path.insert(0, str(repo / "verificador"))
    from verificar_correo import verificar_correo  # type: ignore
    res = verificar_correo(f.read_text(encoding="utf-8"), repo, render=True)
    if not res["aprobada"]:
        for b in res["bloqueos"]:
            print(f"   ✗ {b['id']}: {b['detalle']}")
        die(f"El Verificador de correos rechazó {rel}. No se arma la función.")
    print(f"  ✓ Correo {rel}: aprobado por el Verificador de correos")
    return f.read_bytes()


def revisa_funcion(base_url: str, intentos=6, pausa=5) -> dict | None:
    """Llama a la función con ?verificar=1: revisa su configuración contra HighLevel sin crear nada."""
    u = base_url.rstrip("/") + "/" + RUTA_FUNCION
    for _ in range(intentos):
        try:
            r = httpx.get(u, params={"verificar": "1"}, timeout=30, headers={"User-Agent": UA})
            if r.status_code == 200:
                return r.json()
            ultimo = f"HTTP {r.status_code}"
        except (httpx.HTTPError, ValueError) as e:
            ultimo = str(e)
        time.sleep(pausa)
    return {"ok": False, "faltan": [f"la función no responde ({ultimo})"]}


def imprime_funcion(res: dict) -> bool:
    if res.get("ok"):
        print("  ✓ Función prospecto: responde y su configuración de HighLevel está completa")
    else:
        print(f"  ✗ Función prospecto: falta {res.get('faltan')}")
    for x in res.get("avisos") or []:
        print(f"   ⚠ {x}")
    w1 = res.get("w1")
    if w1:
        print(f"   Correo W1: envío {w1.get('envio')}, plantilla {w1.get('plantilla')}, asunto «{w1.get('asunto')}»")
    return bool(res.get("ok"))


# ---------------------------------------------------------------- construir
BASURA_DEL_SISTEMA = (".DS_Store", "Thumbs.db", "desktop.ini")


def lee_dist() -> dict[str, bytes]:
    """Archivos de la carpeta a subir. Ignora lo que crea el sistema (Finder deja .DS_Store al abrir la carpeta)."""
    out = {}
    for p in sorted(DIST.rglob("*")):
        if p.name in BASURA_DEL_SISTEMA or p.name.startswith("._"):
            continue
        if p.is_file():
            out[p.relative_to(DIST).as_posix()] = p.read_bytes()
    return out


def dir_landing(ruta: str) -> Path:
    return DIST / ruta if ruta else DIST


def revisa(repo: Path, capturas: Path | None, ruta: str = "") -> dict:
    sys.path.insert(0, str(repo / "verificador"))
    import importlib

    vl = importlib.import_module("verificar_landing")
    importlib.reload(vl)
    from verificar import imprime  # type: ignore

    res = vl.verificar_landing(dir_landing(ruta), repo, render=True, capturas=capturas, raiz=DIST)
    imprime(res)
    return res


ROBOTS = "User-agent: *\nDisallow: /\n"
RAIZ_REDIRIGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="robots" content="noindex">
<meta http-equiv="refresh" content="0; url=/{ruta}/"><title>5cero5</title></head>
<body><a href="/{ruta}/">Ir a 5cero5</a></body></html>
"""
HEADERS_NOINDEX = "/*\n  X-Robots-Tag: noindex\n"


def refs_locales(texto: str, ruta_archivo: str) -> set[str]:
    """Rutas locales que un HTML o CSS del deploy base pide (para no perder archivos que la lista de Netlify omita)."""
    base = ruta_archivo.rsplit("/", 1)[0] + "/" if "/" in ruta_archivo else ""
    out = set()
    for v in re.findall(r'(?:src|href)="([^"]+)"', texto) + re.findall(r"url\(['\"]?([^)'\"]+)", texto):
        v = re.split(r"[?#]", v)[0]
        if not v or re.match(r"(https?:)?//|#|mailto:|tel:|data:", v):
            continue
        p = v[1:] if v.startswith("/") else posixpath.normpath(base + v)
        if p and not p.startswith(".."):
            if p.endswith("/") or "." not in p.rsplit("/", 1)[-1]:
                out.add(p.rstrip("/") + "/index.html")
            else:
                out.add(p)
    return out


def lee_base_local(nf: NF, base: str, carpeta: Path, ruta: str) -> dict[str, bytes]:
    """Sitio base desde una carpeta local (la descarga del deploy en Netlify). Cada archivo debe tener el SHA1
    que Netlify registró para ese deploy, y no puede faltar ninguno de los que Netlify lista."""
    step(f"Leyendo el sitio base desde {carpeta} y comparándolo con el deploy {base}")
    if not carpeta.is_dir():
        die(f"No existe la carpeta {carpeta}.")
    locales: dict[str, bytes] = {}
    for p in sorted(carpeta.rglob("*")):
        if p.is_file() and p.name not in BASURA_DEL_SISTEMA and not p.name.startswith("._"):
            locales[p.relative_to(carpeta).as_posix()] = p.read_bytes()
    if not locales:
        die("La carpeta del sitio base está vacía.")
    # Netlify guarda las rutas en minúsculas (README.md aparece como readme.md): se compara sin distinguir mayúsculas.
    registro_crudo = nf.archivos(base, list(locales))
    registro = {}
    for k, v in registro_crudo.items():
        if v:
            registro[k.lower()] = v
    por_min = {k.lower(): k for k in locales}
    distintos = [k for k, b in locales.items() if registro.get(k.lower()) and registro[k.lower()] != sha1(b)]
    desconocidos = [k for k in locales if not registro.get(k.lower())]
    faltan = [k for k in registro if k not in por_min]
    if distintos:
        die(f"Estos archivos no son los del deploy {base} (SHA1 distinto): {distintos[:6]}")
    if faltan:
        die(f"Faltan en la carpeta archivos que el deploy {base} sí tiene: {faltan[:10]}\n"
            f"  Revisa que pasaste la carpeta descomprimida completa (la que contiene index.html), no una subcarpeta.")
    if desconocidos:
        print(f"  ⚠ Archivos que Netlify no reporta para ese deploy (se suben igual): {desconocidos[:6]}")
    choque = [k for k in locales if ruta and (k == ruta or k.startswith(ruta + "/"))]
    if choque:
        die(f"El sitio base ya tiene archivos en /{ruta}: {choque[:5]}. Elige otra ruta.")
    print(f"  ✓ {len(locales)} archivo(s) del sitio base, idénticos byte por byte a los que Netlify registró")
    return locales


def baja_base(nf: NF, base: str, ruta: str) -> dict[str, bytes]:
    step(f"Bajando el sitio base (deploy {base}) para conservar la raíz")
    if ruta and nf.archivos(base, [f"{ruta}/index.html"]).get(f"{ruta}/index.html"):
        die(f"El deploy base ya tiene /{ruta}/index.html. Elige otra ruta.")
    lista = nf.archivos(base)
    pendientes = dict(lista)
    bajados: dict[str, bytes] = {}
    revisados = set()
    while pendientes:
        k, sha = pendientes.popitem()
        revisados.add(k)
        if not sha:
            continue
        b = nf.baja_archivo(base, k, sha)
        if b is None:
            die(f"No pude bajar {k} del deploy {base} con su SHA1 registrado. No se arma nada a medias.")
        bajados[k] = b
        if k.endswith((".html", ".css")):
            for r in refs_locales(b.decode("utf-8", "ignore"), k):
                if r not in revisados and r not in pendientes and r not in bajados:
                    extra = nf.archivos(base, [r]).get(r)
                    if extra:
                        pendientes[r] = extra
                    revisados.add(r)
    if not bajados:
        die(f"El deploy base {base} no trajo ningún archivo. No armo un sitio que borre la raíz; revisa el ID o usa --base-deploy ninguno.")
    choque = [k for k in bajados if ruta and (k == ruta or k.startswith(ruta + "/"))]
    if choque:
        die(f"El deploy base ya tiene archivos en /{ruta}: {choque[:5]}. Elige otra ruta.")
    print(f"  ✓ {len(bajados)} archivo(s) del sitio base, cada uno con su SHA1 de Netlify: {sorted(bajados)[:8]}{' …' if len(bajados) > 8 else ''}")
    return bajados


def cmd_construir(a) -> None:
    repo = repo_dir()
    version = (repo / "VERSION").read_text().strip()
    ruta = (a.ruta or "").strip("/")
    sys.path.insert(0, str(repo / "landing"))
    try:
        from armar import RUTA_OK, arma  # type: ignore
    except ImportError:
        die(f"El repo no tiene landing/armar.py. Usa la versión 0.5.0 o mayor ({repo}).")
    if ruta and not RUTA_OK.match(ruta):
        die(f"Ruta inválida: {ruta!r}. Usa minúsculas, números y guiones.")
    est = carga_estado()
    base = a.base_deploy
    if base == "anterior":
        # el sitio que había ANTES de que este script publicara por primera vez
        base = est.get("base_original") or (est.get("publicacion") or {}).get("anterior") or "ninguno"
        if base != "ninguno" and not est.get("base_original"):
            est["base_original"] = base
            guarda_estado(est)
    if a.base_dir:
        if base == "ninguno":
            base = est.get("base_original") or "ninguno"
        if base == "ninguno":
            die("--base-dir necesita saber de qué deploy salió esa carpeta: agrega --base-deploy <ID>.")
    elif base == "ninguno" and est.get("base_original") and not a.reemplazar_raiz:
        die(f"La raíz de mkt.5cero5.com se conserva como está (deploy {est['base_original']}).\n"
            "  Baja ese deploy desde Netlify (Deploys > el deploy > Download) y pasa la carpeta con --base-dir.\n"
            "  Solo si de verdad quieres reemplazar la raíz: --reemplazar-raiz.")
    print(f"  Sitio base: {base}")
    shutil.rmtree(DIST, ignore_errors=True)
    DIST.mkdir(parents=True)
    base_archivos: dict[str, bytes] = {}
    if base != "ninguno":
        nf = NF(need("NETLIFY_TOKEN"), need("NETLIFY_SITE_ID"))
        base_archivos = lee_base_local(nf, base, Path(a.base_dir).expanduser(), ruta) if a.base_dir else baja_base(nf, base, ruta)
        for k, b in base_archivos.items():
            f = DIST / k
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b)
    elif ruta:
        # raíz mínima: manda a la landing. Meta refresh (no depende de que Netlify procese _redirects).
        (DIST / "index.html").write_text(RAIZ_REDIRIGE.format(ruta=ruta), encoding="utf-8")
        print(f"  La raíz de mkt.5cero5.com mandará a /{ruta}/ (el sitio anterior no se conserva).")
    build_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + sha1(os.urandom(8))[:6]
    step(f"Armando la landing en /{ruta} desde el repo de marca v{version} (build {build_id})")
    arma(repo, DIST, ruta, build_id)
    # noindex: con sitio base, solo para la landing (la raíz queda como está); sin base, todo el sitio
    if base_archivos:
        regla = f"/{ruta}/*\n  X-Robots-Tag: noindex\n" if ruta else HEADERS_NOINDEX
        previo = base_archivos.get("_headers", b"").decode("utf-8")
        (DIST / "_headers").write_text((previo + "\n" if previo else "") + regla)
    else:
        (DIST / "_headers").write_text(HEADERS_NOINDEX)
        (DIST / "robots.txt").write_text(ROBOTS)
    step("Revisando con el Verificador de landing (incluye navegador: contraste medido y fuentes cargadas)")
    res = revisa(repo, CAPTURAS, ruta)
    if not res["aprobada"]:
        die("El Verificador rechazó la landing. No se guarda manifiesto.")
    archivos = lee_dist()
    landing = [k for k in archivos if (k.startswith(ruta + "/") if ruta else k not in base_archivos)]
    funciones = {}
    shutil.rmtree(FUNCS, ignore_errors=True)
    mod = sys.modules.get("armar")
    for nombre in getattr(mod, "FUNCIONES", ()):
        fuente = repo / "landing" / "funciones" / f"{nombre}.js"
        if not fuente.exists():
            die(f"Falta la función {fuente}")
        extras = {}
        for rel in getattr(mod, "FUNCIONES_ARCHIVOS", {}).get(nombre, ()):
            datos = verifica_correo_de_funcion(repo, rel) if rel.endswith(".html") else (repo / rel).read_bytes()
            extras[Path(rel).name] = datos
        funciones[nombre] = sha256(zip_funcion(fuente, nombre, FUNCS / f"{nombre}.zip", extras))
        print(f"  Función {nombre}: lista para subir")
    man = {
        "creado": ahora(), "repo_version": version, "ruta": ruta, "base": base, "build": build_id,
        "archivos": {k: sha1(v) for k, v in archivos.items()},
        "landing": sorted(landing),
        "funciones": funciones,
        "reemplaza_raiz": bool(a.reemplazar_raiz),
        "avisos": [{"id": x["id"], "detalle": x["detalle"]} for x in res["avisos"]],
    }
    MANIFIESTO.write_text(json.dumps(man, indent=2, ensure_ascii=False))
    print(f"\n✓ Manifiesto guardado: {len(archivos)} archivos ({len(landing)} de la landing, {len(base_archivos)} del sitio base). Capturas en {CAPTURAS}")
    print(f"  La landing quedará en /{ruta}" if ruta else "  La landing quedará en la raíz")


def manifiesto() -> dict:
    if not MANIFIESTO.exists():
        die("No hay manifiesto. Corre primero: landing construir")
    return json.loads(MANIFIESTO.read_text())


def dist_igual_al_manifiesto(man: dict) -> list[str]:
    actual = {k: sha1(v) for k, v in lee_dist().items()}
    difs = [f"{k}: {'falta' if k not in actual else 'cambió'}" for k, v in man["archivos"].items() if actual.get(k) != v]
    difs += [f"{k}: sobra" for k in actual if k not in man["archivos"]]
    return difs


# ---------------------------------------------------------------- borrador
def cmd_borrador(a) -> None:
    nf = NF(need("NETLIFY_TOKEN"), need("NETLIFY_SITE_ID"))
    man = manifiesto()
    difs = dist_igual_al_manifiesto(man)
    if difs:
        die(f"La carpeta cambió después de revisarla ({difs}). Corre 'construir' otra vez.")
    repo = repo_dir()
    step("Revisando otra vez la carpeta antes de subir")
    if not revisa(repo, None, man.get("ruta", ""))["aprobada"]:
        die("El Verificador rechazó la carpeta.")
    antes = nf.publicado()
    print(f"  Deploy publicado hoy: {antes}")
    archivos = lee_dist()
    step("Creando el deploy como BORRADOR")
    funciones = man.get("funciones") or {}
    for n, h in funciones.items():
        z = FUNCS / f"{n}.zip"
        if not z.exists() or sha256(z.read_bytes()) != h:
            die(f"El zip de la función {n} cambió o falta. Corre 'construir' otra vez.")
    cuerpo = {"files": {"/" + k: v for k, v in man["archivos"].items()}, "draft": True}
    if funciones:
        cuerpo["functions"] = funciones
    d = nf.ok("POST", f"/sites/{nf.site}/deploys", json=cuerpo)
    did = d["id"]
    por_sha = {}
    for k, v in man["archivos"].items():
        por_sha.setdefault(v, []).append(k)
    requeridos = d.get("required") or []
    print(f"  Deploy {did} · Netlify pide {len(requeridos)} archivo(s) distinto(s)")
    for s in requeridos:
        for k in por_sha.get(s, []):
            r = nf.req("PUT", f"/deploys/{did}/files/{k}", content=archivos[k], headers={"Content-Type": "application/octet-stream"})
            if r.status_code not in (200, 201):
                die(f"No se pudo subir {k}: {r.status_code} {r.text[:200]}")
            print(f"  ↑ {k}")
    req_f = set(d.get("required_functions") or [])
    for n, h in funciones.items():
        if h in req_f:
            r = nf.req("PUT", f"/deploys/{did}/functions/{n}", params={"runtime": "js"},
                       content=(FUNCS / f"{n}.zip").read_bytes(), headers={"Content-Type": "application/octet-stream"})
            if r.status_code not in (200, 201):
                die(f"No se pudo subir la función {n}: {r.status_code} {r.text[:200]}")
            print(f"  ↑ función {n}")
    d = nf.espera(did)
    step("Verificando contra lo que Netlify guardó")
    reg = nf.archivos(did, man["archivos"])
    malos = [f"{k}: Netlify {reg.get(k)} ≠ manifiesto {v}" for k, v in man["archivos"].items() if reg.get(k) != v]
    if malos:
        print(f"  Archivos que Netlify reporta en el deploy {did}: {nf.ultima_lista}")
        die("Los SHA1 de Netlify no coinciden con el manifiesto: " + "; ".join(malos) +
            f"\n  El deploy {did} quedó como borrador (no se publicó nada). Pega esta salida completa.")
    print(f"  ✓ {len(reg)} archivos con SHA1 idéntico al manifiesto")
    despues = nf.publicado()
    if despues != antes:
        die(f"¡El deploy PUBLICADO cambió! antes {antes}, ahora {despues}. Un borrador no debía hacerlo.")
    print("  ✓ El deploy publicado no cambió")
    url_b = d.get("deploy_ssl_url") or d.get("deploy_url")
    if funciones:
        step("Revisando la función en el borrador (no crea nada en HighLevel)")
        imprime_funcion(revisa_funcion(url_b))
    est = carga_estado()
    est["borrador"] = {"id": did, "creado": ahora(), "manifiesto_creado": man["creado"], "publicado_antes": antes,
                       "url": d.get("deploy_ssl_url") or d.get("deploy_url")}
    guarda_estado(est)
    ruta = man.get("ruta", "")
    print(f"\n✓ Borrador listo. Ábrelo y revísalo: {est['borrador']['url']}/{ruta + '/' if ruta else ''}")
    if man.get("base") not in (None, "ninguno"):
        print(f"  Y revisa que la raíz siga igual: {est['borrador']['url']}/")
    print(f"  Para publicarlo: landing promover --deploy {did} --acepto-aviso-provisional --confirmo 'PUBLICAR {did[:8]}'")
    if man["avisos"]:
        print("\n  Avisos del Verificador:")
        for x in man["avisos"]:
            print(f"   ⚠ {x['id']}: {x['detalle']}")


# ---------------------------------------------------------------- promover
def pide_frase(esperada: str, dada: str | None) -> None:
    if dada is None:
        if not sys.stdin.isatty():
            die(f"Sin terminal interactiva. Pasa --confirmo '{esperada}'.")
        dada = input(f"\nEscribe exactamente  {esperada}  para continuar: ")
    if dada.strip() != esperada:
        die("La frase no coincide. No se publicó nada.")


def fetch_vivo(url: str, ruta: str) -> bytes | None:
    try:
        r = httpx.get(url.rstrip("/") + "/" + ruta, params={"cb": str(time.time())}, timeout=30, follow_redirects=True, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
        return r.content if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


def verifica_vivo(man: dict, url: str, intentos=6, pausa=5) -> list[str]:
    """Netlify puede reescribir los HTML al servirlos (formularios, snippets), así que un HTML no se compara byte
    por byte: se exige que traiga la marca del build. Todo lo demás (CSS, fuentes, logo) sí, byte por byte."""
    malos = []
    ruta = man.get("ruta", "")
    marca = f'name="x-5cero5-build" content="{man.get("build", "")}"'
    revisar = [k for k in man["landing"] if not k.endswith(("_headers", "robots.txt"))]
    for _ in range(intentos):
        malos = []
        for k in revisar:
            b = fetch_vivo(url, k)
            if b is None:
                malos.append(f"{k}: no responde")
            elif k.endswith(".html"):
                if marca not in b.decode("utf-8", "ignore"):
                    malos.append(f"{k}: no trae la marca del build {man.get('build')}")
            elif sha1(b) != man["archivos"][k]:
                malos.append(f"{k}: bytes distintos")
        if ruta:
            b = fetch_vivo(url, ruta)
            if b is None or marca not in b.decode("utf-8", "ignore"):
                malos.append(f"/{ruta} (sin diagonal final): no sirve la landing")
        if "index.html" in man["archivos"] and fetch_vivo(url, "") is None:
            malos.append("la raíz (/) no responde")
        if not malos:
            return []
        time.sleep(pausa)
    return malos


def revisa_noindex(url: str, ruta: str) -> str | None:
    try:
        r = httpx.get(url.rstrip("/") + "/" + (ruta + "/" if ruta else ""), timeout=30, follow_redirects=True, headers={"User-Agent": UA})
        return r.headers.get("x-robots-tag")
    except httpx.HTTPError:
        return None


def cmd_promover(a) -> None:
    nf = NF(need("NETLIFY_TOKEN"), need("NETLIFY_SITE_ID"))
    est = carga_estado()
    b = est.get("borrador")
    if not b or b["id"] != a.deploy:
        die(f"Ese deploy ({a.deploy}) no es el borrador que verificó este script ({(b or {}).get('id')}). No se promueve.")
    man = manifiesto()
    if man["creado"] != b["manifiesto_creado"]:
        die("El manifiesto es distinto al del borrador. Sube otro borrador.")
    step("Comprobaciones antes de publicar")
    difs = dist_igual_al_manifiesto(man)
    if difs:
        die(f"La carpeta local cambió: {difs}")
    d = nf.deploy(a.deploy)
    if d.get("state") != "ready":
        die(f"El deploy no está listo (estado {d.get('state')}).")
    reg = nf.archivos(a.deploy, man["archivos"])
    malos = [k for k, v in man["archivos"].items() if reg.get(k) != v]
    if malos:
        die(f"Netlify tiene archivos distintos al manifiesto: {malos}")
    print("  ✓ El borrador en Netlify es byte por byte el que se revisó")
    if not revisa(repo_dir(), None, man.get("ruta", ""))["aprobada"]:
        die("El Verificador rechazó la carpeta.")
    actual = nf.publicado()
    if actual == a.deploy:
        die("Ese deploy ya es el publicado.")
    if est.get("base_original") and man.get("base") in (None, "ninguno") and not man.get("reemplaza_raiz"):
        die(f"Este borrador no conserva la raíz (deploy {est['base_original']}). Vuelve a construir con --base-dir.")
    provisional = any(x["id"] == "aviso_provisional" for x in man["avisos"])
    if provisional and not a.acepto_aviso_provisional:
        die("El aviso de privacidad es PROVISIONAL. Si aun así quieres publicar, agrega --acepto-aviso-provisional (decisión de Al o Bonzo, tarea 4).")
    print(f"\n  Publicado hoy: {actual}\n  Se publicará:  {a.deploy}")
    pide_frase(f"PUBLICAR {a.deploy[:8]}", a.confirmo)
    step("Publicando")
    nf.ok("POST", f"/deploys/{a.deploy}/restore")
    for _ in range(12):
        if nf.publicado() == a.deploy:
            break
        time.sleep(3)
    else:
        die("Netlify no marca ese deploy como publicado. Revisa el sitio antes de seguir.")
    est["publicacion"] = {"deploy": a.deploy, "anterior": actual, "cuando": ahora(), "aviso_provisional": provisional}
    guarda_estado(est)
    print("  ✓ Netlify marca el deploy como publicado")
    url = nf.sitio().get("ssl_url") or nf.sitio().get("url")
    step(f"Verificando la URL pública ({url})")
    mal = verifica_vivo(man, url)
    if mal:
        print(f"  ✗ La URL pública no sirve lo esperado: {mal}")
        print("  Puede ser caché. Si persiste: landing revertir")
        sys.exit(2)
    print("  ✓ La URL pública sirve este build: HTML con su marca, y CSS, fuentes y logo byte por byte")
    if man.get("funciones"):
        if not imprime_funcion(revisa_funcion(url)):
            print("  El formulario no llegará a HighLevel hasta corregir eso (variables HL_TOKEN y HL_LOCATION_ID en Netlify, y redeploy).")
    xr = revisa_noindex(url, man.get("ruta", ""))
    print(f"  {'✓' if xr and 'noindex' in xr.lower() else '⚠'} Cabecera X-Robots-Tag: {xr or 'no llegó (revisa _headers)'}")
    ruta = man.get("ruta", "")
    print(f"\n✓ Publicado: {url.rstrip('/')}/{ruta + '/' if ruta else ''}")
    print(f"  Para deshacer: landing revertir  (vuelve a {actual})")


def cmd_revertir(a) -> None:
    nf = NF(need("NETLIFY_TOKEN"), need("NETLIFY_SITE_ID"))
    est = carga_estado()
    p = est.get("publicacion")
    if not p or not p.get("anterior"):
        die("No hay una publicación registrada de la que volver.")
    actual = nf.publicado()
    print(f"  Publicado hoy: {actual}\n  Se regresará a: {p['anterior']}")
    pide_frase("REVERTIR", a.confirmo)
    nf.ok("POST", f"/deploys/{p['anterior']}/restore")
    for _ in range(12):
        if nf.publicado() == p["anterior"]:
            break
        time.sleep(3)
    else:
        die("Netlify no marca el deploy anterior como publicado.")
    est["reversion"] = {"a": p["anterior"], "desde": actual, "cuando": ahora()}
    guarda_estado(est)
    print(f"\n✓ Revertido: el sitio vuelve a {p['anterior']}")


# ---------------------------------------------------------------- lead: verificar en HighLevel
HL_API = os.environ.get("HL_API_BASE", "https://services.leadconnectorhq.com")


def hl_get(path: str, token: str, **params) -> dict:
    r = httpx.get(HL_API + path, params=params, timeout=30,
                  headers={"Authorization": f"Bearer {token}", "Version": "2021-07-28", "Accept": "application/json"})
    if r.status_code != 200:
        die(f"HighLevel respondió {r.status_code} a GET {path}: {r.text[:200]}")
    return r.json()


def cmd_lead(a) -> None:
    """Revisa en HighLevel (no en lo que dice la función) que el lead llegó completo."""
    token, loc = need("HL_TOKEN"), need("HL_LOCATION_ID")
    email = a.email.strip().lower()
    step(f"Buscando {email} en HighLevel")
    cs = [c for c in hl_get("/contacts/", token, locationId=loc, query=email).get("contacts", []) if (c.get("email") or "").lower() == email]
    if not cs:
        die("No existe un contacto con ese correo en HighLevel.")
    if len(cs) > 1:
        print(f"  ⚠ Hay {len(cs)} contactos con ese correo (duplicados).")
    c = hl_get(f"/contacts/{cs[0]['id']}", token).get("contact", cs[0])
    claves = {f["id"]: str(f.get("fieldKey", "")).replace("contact.", "")
              for f in hl_get(f"/locations/{loc}/customFields", token, model="contact").get("customFields", [])}
    campos = {claves.get(x.get("id"), x.get("id")): x.get("value") for x in c.get("customFields") or []}
    ok = True

    def chk(nombre, cond, detalle=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'✓' if cond else '✗'} {nombre}{': ' + str(detalle) if detalle else ''}")

    chk("nombre", c.get("firstName") or c.get("contactName") or c.get("name"), c.get("contactName") or c.get("firstName"))
    chk("teléfono", c.get("phone"), c.get("phone"))
    chk("empresa", c.get("companyName"), c.get("companyName"))
    tags = c.get("tags") or []
    chk("tags prospecto y discovery-pendiente", {"prospecto", "discovery-pendiente"} <= set(tags), tags)
    for k in ("utm_source", "utm_campaign", "pagina", "aviso_version"):
        chk(f"campo {k}", campos.get(k), campos.get(k))
    if a.w1:
        chk("correo W1 enviado desde HighLevel (tag w1-enviado)", "w1-enviado" in tags and "w1-fallo" not in tags, tags)
    if a.campana:
        chk("utm_campaign esperado", campos.get("utm_campaign") == a.campana, f"{campos.get('utm_campaign')} (esperado {a.campana})")
    pipes = {p["id"]: p for p in hl_get("/opportunities/pipelines", token, locationId=loc).get("pipelines", [])}
    ops = hl_get("/opportunities/search", token, location_id=loc, contact_id=c["id"]).get("opportunities", [])
    abiertas = [o for o in ops if o.get("status") == "open"]
    chk("una oportunidad abierta", len(abiertas) == 1, f"{len(abiertas)} abierta(s)")
    for o in abiertas[:1]:
        p = pipes.get(o.get("pipelineId"), {})
        etapa = next((s_["name"] for s_ in p.get("stages", []) if s_["id"] == o.get("pipelineStageId")), "?")
        chk("pipeline y etapa", p.get("name") == "Ventas 5cero5" and etapa == "Prospecto nuevo", f"{p.get('name')} / {etapa}")
    print("\n" + ("✓ El lead llegó completo a HighLevel." if ok else "✗ El lead llegó incompleto. Pega esta salida."))
    sys.exit(0 if ok else 1)


def cmd_estado(a) -> None:
    print(json.dumps(carga_estado(), indent=2, ensure_ascii=False))
    if MANIFIESTO.exists():
        m = json.loads(MANIFIESTO.read_text())
        print(f"\nManifiesto: {m['creado']} · repo v{m['repo_version']} · {len(m['archivos'])} archivos")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("construir")
    c.add_argument("--ruta", default="landingtest", help="ruta de la landing en el sitio (vacío = raíz). Por defecto: landingtest")
    c.add_argument("--base-dir", help="carpeta con el sitio base (la descarga del deploy original en Netlify); se conserva tal cual")
    c.add_argument("--reemplazar-raiz", action="store_true", help="no conservar la raíz (requiere decisión explícita)")
    c.add_argument("--base-deploy", default="ninguno",
                   help="'ninguno' (por defecto: la raíz manda a la landing), 'anterior' (conserva el sitio publicado antes de la primera promoción) o un ID de deploy")
    c.set_defaults(f=cmd_construir)
    sp.add_parser("borrador").set_defaults(f=cmd_borrador)
    p = sp.add_parser("promover")
    p.add_argument("--deploy", required=True)
    p.add_argument("--acepto-aviso-provisional", action="store_true")
    p.add_argument("--confirmo")
    p.set_defaults(f=cmd_promover)
    r = sp.add_parser("revertir")
    r.add_argument("--confirmo")
    r.set_defaults(f=cmd_revertir)
    sp.add_parser("estado").set_defaults(f=cmd_estado)
    le = sp.add_parser("lead", help="revisa en HighLevel que un lead llegó completo (necesita HL_TOKEN y HL_LOCATION_ID)")
    le.add_argument("--email", required=True)
    le.add_argument("--campana", help="utm_campaign esperado, p. ej. e2e")
    le.add_argument("--w1", action="store_true", help="revisa también que se mandó el correo W1")
    le.set_defaults(f=cmd_lead)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
