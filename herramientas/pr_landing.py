#!/usr/bin/env python3
"""Herramienta del agente Landing: arma o cambia UNA landing del repo 5cero5-landings y abre un PR. Nunca fusiona.

  python3 pr_landing.py nueva   --slug buen-fin --nombre "Buen Fin 2026"   carpeta nueva desde la plantilla de marca
  python3 pr_landing.py revisar --slug buen-fin                            build y pruebas del repo (si hay node) + Verificador de marca
  python3 pr_landing.py abrir   --slug buen-fin --titulo "..." [--cuerpo "..."]   rama agente/<slug>-<fecha> + PR a main

Rutas (por defecto las de la sesión del agente): --landings /tmp/landings (copia del repo), --marca /tmp/marca (copia del repo de marca).
Variables: GITHUB_TOKEN (lo pone el harness; solo viaja en el encabezado hacia api.github.com). Opcionales: GH_LANDINGS_REPO
(por defecto 5cero5/5cero5-landings), GITHUB_API_BASE (solo pruebas).

Lo que se impone:
  - Solo sube archivos de landings/<slug>/. Nada de la función, el build, correos/ u otras landings.
  - Solo crea ramas agente/*. No toca main, no fusiona y no cierra PRs.
  - 'abrir' se niega si la carpeta no pasa 'revisar' en esta misma corrida (marca .revisado con el hash de la carpeta).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
RESERVADAS = {"assets", "netlify", "api", "admin"}
BASURA = {".DS_Store", "Thumbs.db", "desktop.ini"}
MAX_ARCHIVOS, MAX_BYTES = 80, 8 * 1024 * 1024
API = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
REPO = os.environ.get("GH_LANDINGS_REPO", "5cero5/5cero5-landings")


def die(m: str) -> None:
    print(f"\n✗ {m}")
    sys.exit(1)


def carpeta(a) -> Path:
    if not SLUG.match(a.slug or "") or a.slug in RESERVADAS:
        die(f"Slug inválido: {a.slug!r}. Minúsculas, números y guiones (no {', '.join(sorted(RESERVADAS))}).")
    return Path(a.landings) / "landings" / a.slug


def archivos(dir_: Path) -> dict[str, bytes]:
    out = {}
    for p in sorted(dir_.rglob("*")):
        if p.is_symlink():
            die(f"{p} es un enlace simbólico: no se sube.")
        if p.is_file() and p.name not in BASURA and not p.name.startswith("._") and p.name != ".revisado":
            out[p.relative_to(dir_).as_posix()] = p.read_bytes()
    return out


def huella(dir_: Path) -> str:
    h = hashlib.sha256()
    for k, v in archivos(dir_).items():
        h.update(k.encode() + b"\0" + hashlib.sha256(v).digest())
    return h.hexdigest()


# ------------------------------------------------------------------ nueva
def cmd_nueva(a) -> None:
    dest = carpeta(a)
    if dest.exists():
        die(f"Ya existe landings/{a.slug}/. Para cambiarla, edítala y usa 'revisar' y 'abrir'.")
    marca = Path(a.marca)
    sys.path.insert(0, str(marca / "landing"))
    try:
        from armar import arma  # type: ignore
    except ImportError:
        die(f"No encuentro landing/armar.py en {marca}.")
    tmp = Path(a.landings) / ".arma_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    arma(marca, tmp, a.slug)
    shutil.move(str(tmp / a.slug), str(dest))
    shutil.rmtree(tmp, ignore_errors=True)
    config = {"nombre": a.nombre, "pipeline": a.pipeline, "etapa": a.etapa, "tags_nuevo": ["prospecto", "discovery-pendiente"],
              "tags_siempre": [a.slug], "correo_bienvenida": None, "campos": []}
    (dest / "landing.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✓ landings/{a.slug}/ creada desde la plantilla de marca, con landing.json. Ahora cambia sus textos y corre 'revisar'.")


# ------------------------------------------------------------------ revisar
def cmd_revisar(a) -> None:
    dir_ = carpeta(a)
    if not (dir_ / "landing.json").exists():
        die(f"landings/{a.slug}/ no tiene landing.json.")
    landings = Path(a.landings)
    if shutil.which("node"):
        r = subprocess.run(["node", "herramientas/construir.js", "--solo-revisar"], cwd=landings, capture_output=True, text=True)
        print(r.stdout + r.stderr)
        if r.returncode != 0:
            die("El build del repo de landings rechaza los cambios (arriba el detalle).")
        # Las mismas pruebas que corre el deploy preview: si fallan aquí, el preview fallaría.
        r = subprocess.run(["node", "--test"], cwd=landings, capture_output=True, text=True)
        resumen = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith(("not ok", "# pass", "# fail"))]
        print("\n".join(resumen))
        if r.returncode != 0:
            die("Las pruebas del repo de landings fallan (arriba cuáles). El deploy preview fallaría igual: no se abre PR.")
    else:
        print("⚠ No hay node: el build del repo lo revisará el deploy preview de Netlify.")
    # Verificador de marca sobre la landing tal como se publica (sin landing.json), en /<slug>/.
    raiz = Path(a.landings) / ".revision"
    shutil.rmtree(raiz, ignore_errors=True)
    shutil.copytree(dir_, raiz / a.slug, ignore=shutil.ignore_patterns("landing.json", ".revisado", *BASURA))
    marca = Path(a.marca)
    sys.path.insert(0, str(marca / "verificador"))
    try:
        from verificar_landing import verificar_landing  # type: ignore
        from verificar import imprime  # type: ignore
    except ImportError:
        die(f"No encuentro el Verificador en {marca}/verificador.")
    res = verificar_landing(raiz / a.slug, marca, render=not a.sin_navegador, capturas=None, raiz=raiz)
    imprime(res)
    shutil.rmtree(raiz, ignore_errors=True)
    if not res["aprobada"]:
        die("El Verificador rechazó la landing. No se abre PR.")
    (dir_ / ".revisado").write_text(huella(dir_))
    print(f"\n✓ landings/{a.slug}/ revisada. Ya se puede abrir el PR.")


# ------------------------------------------------------------------ abrir (API de GitHub)
def gh(method: str, path: str, body: dict | None = None) -> dict:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        die("Falta GITHUB_TOKEN.")
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "5cero5-agente-landing",
                                          **({"Content-Type": "application/json"} if body is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            t = r.read()
            return json.loads(t) if t else {}
    except urllib.error.HTTPError as e:
        die(f"GitHub respondió {e.code} a {method} {path.split('?')[0]}: {e.read()[:300].decode('utf-8', 'ignore')}")


def blob_sha(b: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


def cmd_abrir(a) -> None:
    dir_ = carpeta(a)
    marca = dir_ / ".revisado"
    if not marca.exists() or marca.read_text() != huella(dir_):
        die("La carpeta cambió después de 'revisar' (o no se revisó). Corre 'revisar' otra vez.")
    locales = archivos(dir_)
    if "landing.json" not in locales:
        die("Falta landing.json.")
    if len(locales) > MAX_ARCHIVOS or sum(map(len, locales.values())) > MAX_BYTES:
        die(f"Demasiados archivos o demasiado peso (máximo {MAX_ARCHIVOS} y {MAX_BYTES // 1024 // 1024} MB).")
    pref = f"landings/{a.slug}/"
    base = gh("GET", f"/repos/{REPO}/git/ref/heads/main")["object"]["sha"]
    tree_base = gh("GET", f"/repos/{REPO}/git/commits/{base}")["tree"]["sha"]
    remoto = {e["path"][len(pref):]: e["sha"] for e in gh("GET", f"/repos/{REPO}/git/trees/{tree_base}?recursive=1").get("tree", [])
              if e.get("type") == "blob" and e["path"].startswith(pref)}
    cambios = []
    for k, b in locales.items():
        if remoto.get(k) == blob_sha(b):
            continue
        sha = gh("POST", f"/repos/{REPO}/git/blobs", {"content": base64.b64encode(b).decode(), "encoding": "base64"})["sha"]
        cambios.append({"path": pref + k, "mode": "100644", "type": "blob", "sha": sha})
    for k in remoto:
        if k not in locales:
            cambios.append({"path": pref + k, "mode": "100644", "type": "blob", "sha": None})
    if not cambios:
        die("No hay cambios contra main en esa carpeta.")
    if any(not c["path"].startswith(pref) for c in cambios):
        die("Un cambio cae fuera de la carpeta de la landing.")  # no debería pasar nunca
    arbol = gh("POST", f"/repos/{REPO}/git/trees", {"base_tree": tree_base, "tree": cambios})["sha"]
    nueva = not remoto
    msg = f"{'Nueva landing' if nueva else 'Landing'} {a.slug}: {a.titulo}"
    commit = gh("POST", f"/repos/{REPO}/git/commits", {"message": msg, "tree": arbol, "parents": [base]})["sha"]
    rama = f"agente/{a.slug}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    gh("POST", f"/repos/{REPO}/git/refs", {"ref": f"refs/heads/{rama}", "sha": commit})
    cuerpo = (a.cuerpo or "") + ("\n\n" if a.cuerpo else "") + \
        f"Abierto por el agente Landing. Solo cambia `{pref}` ({len(cambios)} archivo(s)).\n\n" \
        f"Para revisar: el deploy preview de Netlify en `/{a.slug}/` y `/.netlify/functions/prospecto?verificar=1&landing={a.slug}`.\n" \
        "Publicar = aprobar y fusionar este PR (solo Al o Bonzo)."
    pr = gh("POST", f"/repos/{REPO}/pulls", {"title": msg[:120], "head": rama, "base": "main", "body": cuerpo})
    out = {"pr_url": pr.get("html_url"), "pr_numero": pr.get("number"), "rama": rama, "commit": commit, "slug": a.slug,
           "archivos": [c["path"] for c in cambios]}
    print(json.dumps(out, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--landings", default="/tmp/landings")
    ap.add_argument("--marca", default="/tmp/marca")
    sp = ap.add_subparsers(dest="cmd", required=True)
    n = sp.add_parser("nueva")
    n.add_argument("--slug", required=True)
    n.add_argument("--nombre", required=True)
    n.add_argument("--pipeline", default="Ventas 5cero5")
    n.add_argument("--etapa", default="Prospecto nuevo")
    n.set_defaults(f=cmd_nueva)
    r = sp.add_parser("revisar")
    r.add_argument("--slug", required=True)
    r.add_argument("--sin-navegador", action="store_true", help="solo para pruebas: sin Playwright el Verificador no aprueba")
    r.set_defaults(f=cmd_revisar)
    b = sp.add_parser("abrir")
    b.add_argument("--slug", required=True)
    b.add_argument("--titulo", required=True)
    b.add_argument("--cuerpo")
    b.set_defaults(f=cmd_abrir)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
