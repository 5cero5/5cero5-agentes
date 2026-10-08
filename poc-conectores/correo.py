#!/usr/bin/env python3
"""Correos de HighLevel desde el sistema de marca: armar -> verificar -> subir como plantilla -> comprobar.

  correo armar    --copia w1-entrevista.json      llena plantillas/correo.html (repo de marca) y deja el HTML junto al JSON
  correo verificar --html w1-entrevista.html      Verificador de correos del repo (bloquea si algo rompe la marca)
  correo subir    --html w1-entrevista.html --nombre "W1 · Entrevista de diagnóstico"
                                               verifica otra vez y crea o actualiza la plantilla en HighLevel
  correo comprobar --nombre "W1 · Entrevista de diagnóstico" --html w1-entrevista.html
                                               lee la plantilla en HighLevel y confirma que trae lo aprobado

Lo mismo que corre una persona lo puede correr un agente (Claude Code o Managed Agents) con HL_TOKEN en su
vault. Subir una plantilla no le escribe a nadie: el correo solo sale cuando Al o Bonzo activan el workflow.

Variables: HL_TOKEN (integración privada, con permiso de Email Builder: leer y escribir), HL_LOCATION_ID,
MARCA_REPO (carpeta del repo de marca). Opcional: HL_API_BASE (pruebas).
"""
from __future__ import annotations

import argparse
import html as htmlmod
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

API = os.environ.get("HL_API_BASE", "https://services.leadconnectorhq.com")
VERSION = "2021-07-28"


def die(m: str) -> None:
    print(f"\n✗ {m}")
    sys.exit(1)


def need(v: str) -> str:
    x = os.environ.get(v, "").strip()
    if not x:
        die(f"Falta la variable de entorno {v}.")
    return x


def repo() -> Path:
    r = Path(need("MARCA_REPO")).expanduser()
    if not (r / "plantillas" / "correo.html").exists():
        die(f"{r} no tiene plantillas/correo.html (usa el repo de marca 0.10.0 o mayor).")
    return r


def hl(method: str, path: str, **kw) -> dict:
    r = httpx.request(method, API + path, timeout=60, headers={
        "Authorization": f"Bearer {need('HL_TOKEN')}", "Version": VERSION,
        "Accept": "application/json", "Content-Type": "application/json"}, **kw)
    if r.status_code == 401:
        die("HighLevel rechazó el token (401). Debe ser de integración privada (pit-) de la subcuenta.")
    if r.status_code == 403:
        die(f"HighLevel negó el permiso (403) en {path}. Agrega a la integración privada el permiso de Email Builder (leer y escribir).")
    if r.status_code >= 400:
        die(f"HighLevel respondió {r.status_code} a {method} {path}: {r.text[:300]}")
    try:
        return r.json() if r.text else {}
    except ValueError:
        return {"raw": r.text[:300]}


def verifica(html: str, r: Path) -> dict:
    sys.path.insert(0, str(r / "verificador"))
    from verificar_correo import verificar_correo  # type: ignore
    from verificar import imprime  # type: ignore
    res = verificar_correo(html, r, render=True)
    imprime(res)
    return res


def huellas(html: str) -> list[str]:
    """Lo que debe sobrevivir en HighLevel: el link del botón y cada frase visible del cuerpo."""
    sin = re.sub(r"<!--.*?-->|<style.*?</style>|<head.*?</head>", "", html, flags=re.S)
    out = re.findall(r'class="boton" href="([^"]+)"', sin)
    for p in re.findall(r"<p[^>]*>(.*?)</p>", sin, flags=re.S):
        t = htmlmod.unescape(re.sub(r"<[^>]+>", "", p)).strip()
        if t:
            out.append(t)
    return [htmlmod.unescape(x) for x in out]


def busca(nombre: str) -> dict | None:
    loc = need("HL_LOCATION_ID")
    d = hl("GET", "/emails/builder", params={"locationId": loc, "search": nombre, "limit": 100})
    lista = d.get("builders") or d.get("templates") or []
    return next((t for t in lista if (t.get("name") or t.get("title")) == nombre), None)


def cmd_armar(a) -> None:
    r = repo()
    sys.path.insert(0, str(r / "correos"))
    from armar_correo import arma  # type: ignore
    src = Path(a.copia).expanduser().resolve()
    out = src.with_suffix(".html")
    out.write_text(arma(json.loads(src.read_text(encoding="utf-8"))), encoding="utf-8")
    print(f"✓ {out}")


def cmd_verificar(a) -> None:
    res = verifica(Path(a.html).read_text(encoding="utf-8"), repo())
    sys.exit(0 if res["aprobada"] else 1)


def cmd_subir(a) -> None:
    html = Path(a.html).read_text(encoding="utf-8")
    print("▸ Verificando antes de subir")
    if not verifica(html, repo())["aprobada"]:
        die("El Verificador rechazó el correo. No se sube nada.")
    loc = need("HL_LOCATION_ID")
    t = busca(a.nombre)
    if t:
        tid = t.get("id")
        print(f"▸ La plantilla ya existe ({tid}): se actualiza")
    else:
        print("▸ Creando la plantilla")
        d = hl("POST", "/emails/builder", json={"locationId": loc, "title": a.nombre, "name": a.nombre, "type": "html"})
        tid = d.get("redirect") or d.get("id") or (d.get("template") or {}).get("id")
        if not tid:
            t = busca(a.nombre)
            tid = t and t.get("id")
        if not tid:
            die(f"HighLevel no regresó el id de la plantilla: {d}")
    hl("POST", "/emails/builder/data", json={"locationId": loc, "templateId": tid, "updatedBy": "agente-5cero5",
                                            "editorType": "html", "html": html})
    print(f"✓ Subida como plantilla {tid}. Comprobando lo que guardó HighLevel…")
    a.html_ref = html
    comprueba(a.nombre, html)


def comprueba(nombre: str, html: str, intentos=5, pausa=4) -> None:
    for _ in range(intentos):
        t = busca(nombre)
        url = t and (t.get("previewUrl") or t.get("preview_url"))
        if url:
            try:
                guardado = htmlmod.unescape(httpx.get(url, timeout=30).text)
            except httpx.HTTPError:
                guardado = ""
            faltan = [h for h in huellas(html) if h not in guardado]
            if guardado and not faltan:
                print(f"✓ HighLevel tiene la plantilla «{nombre}» con el botón y todas las frases aprobadas.")
                return
            if guardado:
                die(f"La plantilla en HighLevel no trae: {faltan[:4]}")
        time.sleep(pausa)
    die("No pude leer la plantilla guardada en HighLevel (sin previewUrl). Revísala a mano en Marketing > Emails > Templates.")


def cmd_comprobar(a) -> None:
    comprueba(a.nombre, Path(a.html).read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("armar"); p.add_argument("--copia", required=True); p.set_defaults(f=cmd_armar)
    p = sp.add_parser("verificar"); p.add_argument("--html", required=True); p.set_defaults(f=cmd_verificar)
    p = sp.add_parser("subir"); p.add_argument("--html", required=True); p.add_argument("--nombre", required=True); p.set_defaults(f=cmd_subir)
    p = sp.add_parser("comprobar"); p.add_argument("--html", required=True); p.add_argument("--nombre", required=True); p.set_defaults(f=cmd_comprobar)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
