#!/usr/bin/env python3
"""Crea (o actualiza) en Claude Managed Agents lo que necesita el agente Pauta del harness, y revisa Meta antes.

  0. Revisión en Meta con el token del usuario del sistema (META_TOKEN), por el mismo encabezado que usará el agente:
     quién es el token, qué cuentas publicitarias ve (activa y en MXN), qué es el id de la página (--pagina), su
     Instagram y los Pixeles de la cuenta. Si algo no cuadra, se detiene sin tocar Managed Agents.
  1. Vault "5cero5 · Pauta" con la credencial META_TOKEN, que solo se sustituye en encabezados hacia graph.facebook.com.
  2. Entorno común "5cero5-harness": se le reaplican la red (con graph.facebook.com) y los paquetes.
  3. Agente "5cero5 · Pauta" con el prompt de harness/agentes/pauta.md.

Imprime las variables que van en Netlify. Se puede correr varias veces: no duplica nada. Con --actualizar-agente sube
prompt y modelo a una versión nueva; con --solo-revisar hace solo el paso 0.

  cd harness/infra
  read -rs "META_TOKEN?Token del usuario del sistema de Meta: " && export META_TOKEN && echo
  python3 crear_agente_pauta.py --pagina 1127307763190247 --solo-revisar
  read -rs "ANTHROPIC_API_KEY?Llave de Anthropic: " && export ANTHROPIC_API_KEY && echo
  uv run --with "anthropic>=1.12" python crear_agente_pauta.py --pagina 1127307763190247 [--cuenta act_...] [--pixel ...]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from comun import AGENTES, alta, carga, entorno, need

MODELO = os.environ.get("MODELO_PAUTA", "claude-sonnet-5-5")
API = os.environ.get("META_API_BASE", "https://graph.facebook.com/v25.0")


def g(path: str, **params) -> dict:
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{API}{path}{'?' + q if q else ''}",
                                 headers={"Authorization": f"Bearer {os.environ['META_TOKEN'].strip()}", "User-Agent": "5cero5-infra"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read()).get("error", {})
        except Exception:
            err = {}
        raise SystemExit(f"✗ Meta respondió {e.code} a {path}: {err.get('message', '')} (code {err.get('code')}, subcode {err.get('error_subcode')})")


def revisa_meta(a) -> dict:
    need("META_TOKEN")
    yo = g("/me", fields="id,name")
    print(f"▸ Token de: {yo.get('name')} ({yo.get('id')})")
    try:
        permisos = g("/me/permissions").get("data", [])
    except SystemExit as e:  # algunos tokens de usuario del sistema no dejan leer sus permisos: no es motivo para parar
        print(f"⚠ No se pudieron leer los permisos del token ({e}). Se sigue: la creación de la campaña lo dirá.")
        permisos = []
    if permisos:
        dados = sorted(p["permission"] for p in permisos if p.get("status") == "granted")
        print(f"▸ Permisos: {', '.join(dados)}")
        if "pages_manage_ads" not in dados:
            print("⚠ Falta pages_manage_ads. Si al crear anuncios Meta responde (#200) por permisos de la página, agrégalo a la app y genera el token otra vez.")
        if "ads_management" not in dados:
            raise SystemExit("✗ El token no tiene ads_management. Genéralo otra vez con ads_management, ads_read, pages_show_list y business_management.")

    cuentas = g("/me/adaccounts", fields="id,name,currency,account_status,timezone_name,spend_cap", limit=50).get("data", [])
    for c in cuentas:
        print(f"  · {c['id']} {c.get('name')} · {c.get('currency')} · estado {c.get('account_status')} · {c.get('timezone_name')} · límite {int(c.get('spend_cap') or 0) / 100:g} MXN")
    if a.cuenta:
        cid = a.cuenta if a.cuenta.startswith("act_") else f"act_{a.cuenta}"
        cuenta = next((c for c in cuentas if c["id"] == cid), None)
        if not cuenta:
            raise SystemExit(f"✗ El token no ve la cuenta {cid}. Asígnala al usuario del sistema (Configuración del negocio › Usuarios del sistema › Asignar activos).")
    elif len(cuentas) == 1:
        cuenta = cuentas[0]
    else:
        raise SystemExit(f"✗ El token ve {len(cuentas)} cuentas publicitarias: di cuál con --cuenta act_...")
    if cuenta.get("currency") != "MXN" or cuenta.get("account_status") != 1:
        raise SystemExit(f"✗ La cuenta {cuenta['id']} tiene que estar activa (estado 1) y en MXN: está en {cuenta.get('currency')}, estado {cuenta.get('account_status')}.")
    if not int(cuenta.get("spend_cap") or 0):
        print("⚠ La cuenta no tiene límite de gasto. Ponlo en Facturación › Configuración de pagos antes de encender cualquier campaña.")

    # Si es página: el usuario del sistema la ve en /me/accounts (páginas asignadas), o al menos trae "category",
    # que solo tienen las páginas. (metadata=1 no siempre regresa el tipo con tokens de usuario del sistema.)
    asignadas = {p["id"]: p.get("name") for p in g("/me/accounts", fields="id,name", limit=100).get("data", [])}
    if a.pagina in asignadas:
        print(f"▸ {a.pagina} es la página «{asignadas[a.pagina]}», asignada al usuario del sistema")
    else:
        obj = g(f"/{a.pagina}", fields="id,name,category")
        if obj.get("category"):
            raise SystemExit(f"✗ {a.pagina} es la página «{obj.get('name')}», pero no está asignada a este usuario del sistema. "
                             "Asígnala en Configuración del negocio › Usuarios del sistema › Asignar activos › Páginas (permiso de anuncios).")
        vistas = ", ".join(f"{k} ({v})" for k, v in asignadas.items()) or "ninguna"
        raise SystemExit(f"✗ {a.pagina} ({obj.get('name')}) no es una página de Facebook. Páginas que ve el token: {vistas}.")
    try:
        ig = (g(f"/{a.pagina}", fields="instagram_business_account{id,username}").get("instagram_business_account") or {})
    except SystemExit as e:
        print(f"⚠ No se pudo leer el Instagram de la página ({e}). Sin Instagram, los anuncios salen con la identidad de la página.")
        ig = {}
    print(f"▸ Instagram de la página: {ig.get('username') or 'ninguno'} {ig.get('id') or ''}")
    pixeles = g(f"/{cuenta['id']}/adspixels", fields="id,name").get("data", [])
    lista = ", ".join("%s (%s)" % (p.get("name"), p.get("id")) for p in pixeles) or "ninguno"
    print(f"▸ Pixeles de la cuenta: {lista}")
    pixel = a.pixel or ""
    if pixel and pixel not in {p["id"] for p in pixeles}:
        raise SystemExit(f"✗ El Pixel {pixel} no es de la cuenta {cuenta['id']}.")
    return {"cuenta": cuenta["id"], "pagina": a.pagina, "ig": ig.get("id", ""), "pixel": pixel}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pagina", required=True, help="id de la página de Facebook")
    ap.add_argument("--cuenta", help="cuenta publicitaria (act_...) si el token ve más de una")
    ap.add_argument("--pixel", help="id del Pixel (sin él, el agente solo arma campañas de tráfico)")
    ap.add_argument("--solo-revisar", action="store_true", help="solo revisa Meta; no toca Managed Agents")
    ap.add_argument("--actualizar-agente", action="store_true", help="sube prompt y modelo a una versión nueva del agente")
    a = ap.parse_args()
    ids = revisa_meta(a)
    if a.solo_revisar:
        print("\n✓ Meta cuadra. Corre otra vez sin --solo-revisar (con ANTHROPIC_API_KEY) para crear el agente.")
        return
    need("ANTHROPIC_API_KEY")
    prompt = (AGENTES / "pauta.md").read_text(encoding="utf-8")

    from anthropic import Anthropic
    b = Anthropic().beta
    meta = {"cliente": "5cero5", "rol": "pauta", "origen": "harness/infra/crear_agente_pauta.py"}
    env_id = entorno(b)
    e = alta(b, clave="pauta", vault_nombre="5cero5 · Pauta", meta=meta, actualizar=a.actualizar_agente,
             credenciales=[{"key": "cred_meta_id", "secret_name": "META_TOKEN", "value": os.environ["META_TOKEN"].strip(),
                            "host": "graph.facebook.com", "label": "Meta · usuario del sistema · Pauta"}],
             agente={"name": "5cero5 · Pauta", "description": "Arma campañas de Meta EN PAUSA con piezas aprobadas, con meta_pauta.py. Nunca activa, edita ni borra.",
                     "model": MODELO, "system": prompt})

    print("\nVariables para el proyecto de Netlify del harness (no son secretas):")
    print(f"  MA_ENVIRONMENT_ID={env_id}")
    print(f"  MA_AGENT_PAUTA={e['agent_id']}")
    print(f"  MA_VAULT_PAUTA={e['vault_id']}")
    print(f"  META_AD_ACCOUNT_ID={ids['cuenta']}")
    print(f"  META_PAGE_ID={ids['pagina']}")
    if ids["ig"]:
        print(f"  META_IG_USER_ID={ids['ig']}")
    if ids["pixel"]:
        print(f"  META_PIXEL_ID={ids['pixel']}")
    print("  META_TOPE_DIARIO_MXN=1500   (o el tope que decidan)")
    print("\nY como variable SECRETA en Netlify: META_TOKEN, el mismo token (el harness lo usa para comprobar y pausar).")


if __name__ == "__main__":
    main()
