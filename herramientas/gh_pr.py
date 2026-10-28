"""Lo común de las herramientas que abren PRs (pr_landing.py y pr_pieza.py): la API de Git de GitHub con el token
de la sesión y una sola operación de escritura, subir UNA carpeta a una rama agente/* nueva y abrir el PR a main.

Lo que se impone aquí, para todas las herramientas:
  - Solo cambia archivos bajo el prefijo que se le da (una carpeta). Nada fuera de ella.
  - Solo crea ramas agente/*. No toca main, no fusiona y no cierra PRs.
  - GITHUB_TOKEN solo viaja en el encabezado hacia la API de GitHub (lo pone el harness; dura una hora).
  - Solo escribe en el repo que se le da, y solo si el token es EXCLUSIVO de ese repo (el harness lo saca limitado al repo
    del cliente). Un brief que pida otro repo no cambia a dónde se escribe: la herramienta se niega antes de escribir.
Variables: GITHUB_TOKEN; GITHUB_API_BASE solo para pruebas.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone


def die(m: str) -> None:
    print(f"\n✗ {m}")
    sys.exit(1)


def api() -> str:
    return os.environ.get("GITHUB_API_BASE", "https://api.github.com")


def gh(method: str, path: str, body: dict | None = None, ua: str = "5cero5-agente") -> dict:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        die("Falta GITHUB_TOKEN.")
    req = urllib.request.Request(api() + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28", "User-Agent": ua,
                                          **({"Content-Type": "application/json"} if body is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            t = r.read()
            return json.loads(t) if t else {}
    except urllib.error.HTTPError as e:
        die(f"GitHub respondió {e.code} a {method} {path.split('?')[0]}: {e.read()[:300].decode('utf-8', 'ignore')}")


REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")


def repo_exclusivo(repo: str, ua: str = "5cero5-agente") -> None:
    """El token de la sesión tiene que ver exactamente un repo, y ese repo es el que se pide. Si no, no se escribe nada."""
    if not REPO.match(repo or ""):
        die(f"--repo inválido: {repo!r} (debe ser org/repo)")
    vistos = [r.get("full_name", "") for r in gh("GET", "/installation/repositories?per_page=100", None, ua).get("repositories", [])]
    if [v.lower() for v in vistos] != [repo.lower()]:
        die(f"El token de la sesión no es exclusivo de {repo} (ve: {', '.join(vistos) or 'ninguno'}). No se escribe nada.")


def blob_sha(b: bytes) -> str:
    """El sha que GitHub le da a un archivo (blob). Sirve para comprobar sin bajar el archivo."""
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


def sube_carpeta(*, repo: str, pref: str, locales: dict[str, bytes], mensaje, rama_base: str, cuerpo,
                 ua: str = "5cero5-agente") -> dict:
    """Sube los archivos de una carpeta (rutas relativas a pref) contra main: crea, cambia o borra solo dentro de pref.
    Abre una rama agente/<rama_base>-<fecha> y un PR a main. Devuelve {pr_url, pr_numero, rama, commit, archivos, nueva}.
    mensaje y cuerpo pueden ser texto o funciones (nueva, n_cambios) -> texto, para decir si la carpeta es nueva."""
    if not pref.endswith("/") or pref.startswith("/") or ".." in pref.split("/"):
        die(f"Prefijo inválido: {pref!r}")
    repo_exclusivo(repo, ua)
    g = lambda m, p, b=None: gh(m, p, b, ua)
    base = g("GET", f"/repos/{repo}/git/ref/heads/main")["object"]["sha"]
    tree_base = g("GET", f"/repos/{repo}/git/commits/{base}")["tree"]["sha"]
    remoto = {e["path"][len(pref):]: e["sha"] for e in g("GET", f"/repos/{repo}/git/trees/{tree_base}?recursive=1").get("tree", [])
              if e.get("type") == "blob" and e["path"].startswith(pref)}
    cambios = []
    for k, b in locales.items():
        if remoto.get(k) == blob_sha(b):
            continue
        sha = g("POST", f"/repos/{repo}/git/blobs", {"content": base64.b64encode(b).decode(), "encoding": "base64"})["sha"]
        cambios.append({"path": pref + k, "mode": "100644", "type": "blob", "sha": sha})
    for k in remoto:
        if k not in locales:
            cambios.append({"path": pref + k, "mode": "100644", "type": "blob", "sha": None})
    if not cambios:
        die("No hay cambios contra main en esa carpeta.")
    if any(not c["path"].startswith(pref) or ".." in c["path"].split("/") for c in cambios):
        die("Un cambio cae fuera de la carpeta.")  # no debería pasar nunca
    nueva = not remoto
    if callable(mensaje):
        mensaje = mensaje(nueva, len(cambios))
    if callable(cuerpo):
        cuerpo = cuerpo(nueva, len(cambios))
    arbol = g("POST", f"/repos/{repo}/git/trees", {"base_tree": tree_base, "tree": cambios})["sha"]
    commit = g("POST", f"/repos/{repo}/git/commits", {"message": mensaje, "tree": arbol, "parents": [base]})["sha"]
    rama = f"agente/{rama_base}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    g("POST", f"/repos/{repo}/git/refs", {"ref": f"refs/heads/{rama}", "sha": commit})
    pr = g("POST", f"/repos/{repo}/pulls", {"title": mensaje[:120], "head": rama, "base": "main", "body": cuerpo})
    return {"pr_url": pr.get("html_url"), "pr_numero": pr.get("number"), "rama": rama, "commit": commit,
            "archivos": [c["path"] for c in cambios], "nueva": nueva}
