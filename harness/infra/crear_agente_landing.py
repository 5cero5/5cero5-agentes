#!/usr/bin/env python3
"""Crea (o actualiza) en Claude Managed Agents lo que necesita el agente Landing del harness.

  1. Vault "5cero5 · Landing" con NETLIFY_TOKEN, que solo se sustituye en encabezados hacia api.netlify.com.
     Es un token personal de Netlify (cuenta ops@): Netlify no permite limitarlo a borradores, así que el límite
     lo ponen landing.py (solo construir y borrador), el prompt y `landing.py promover --desde-notion`, que revisa
     el borrador contra Netlify antes de publicar.
  2. Entorno común "5cero5-harness": se le reaplican la red (api.netlify.com y las descargas de Playwright) y los paquetes.
  3. Agente "5cero5 · Landing" con el prompt de harness/agentes/landing.md.

Imprime las variables que van en Netlify: MA_AGENT_LANDING y MA_VAULT_LANDING (y MA_ENVIRONMENT_ID, que no cambia).
Se puede correr varias veces: no duplica nada y actualiza el token. Con --actualizar-agente sube prompt y modelo.

  cd harness/infra
  read -rs "ANTHROPIC_API_KEY?Llave de Anthropic: " && export ANTHROPIC_API_KEY && echo
  read -rs "NETLIFY_TOKEN_LANDING?Token personal de Netlify (ops@): " && export NETLIFY_TOKEN_LANDING && echo
  uv run --with "anthropic>=1.12" python crear_agente_landing.py
"""
from __future__ import annotations

import argparse
import os
import re
import sys

from comun import AGENTES, alta, entorno, need

MODELO = os.environ.get("MODELO_LANDING", "claude-sonnet-5-5")
SITIO = os.environ.get("NETLIFY_SITE_ID", "6bc5730f-2e8d-46fa-8bdc-eb7f51559001")   # poc505 = mkt.5cero5.com
BASE = os.environ.get("BASE_DEPLOY", "6ab9e4bf33abe600082e4939")                    # raíz original (5cero5-marca/landing/base)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--actualizar-agente", action="store_true", help="sube prompt y modelo a una versión nueva del agente")
    a = ap.parse_args()
    need("ANTHROPIC_API_KEY")
    token = need("NETLIFY_TOKEN_LANDING")
    if not re.fullmatch(r"[0-9a-f-]{36}", SITIO) or not re.fullmatch(r"[0-9a-f]{24}", BASE):
        sys.exit("✗ NETLIFY_SITE_ID o BASE_DEPLOY no tienen forma de id de Netlify.")
    prompt = (AGENTES / "landing.md").read_text(encoding="utf-8")
    prompt = prompt.replace("__NETLIFY_SITE_ID__", SITIO).replace("__BASE_DEPLOY__", BASE)
    if re.search(r"__[A-Z_]+__", prompt):
        sys.exit("✗ El prompt todavía tiene marcadores sin llenar.")

    from anthropic import Anthropic
    b = Anthropic().beta
    meta = {"cliente": "5cero5", "rol": "landing", "origen": "harness/infra/crear_agente_landing.py"}
    env_id = entorno(b)
    e = alta(b, clave="landing", vault_nombre="5cero5 · Landing", meta=meta, actualizar=a.actualizar_agente,
             credenciales=[{"key": "cred_netlify_id", "secret_name": "NETLIFY_TOKEN", "value": token,
                            "host": "api.netlify.com", "label": "Netlify · ops@ · borradores de mkt.5cero5.com"}],
             agente={"name": "5cero5 · Landing", "description": "Borradores de mkt.5cero5.com/landingtest con landing.py. Nunca publica.",
                     "model": MODELO, "system": prompt})

    print("\nVariables para el proyecto de Netlify del harness (no son secretas):")
    print(f"  MA_ENVIRONMENT_ID={env_id}")
    print(f"  MA_AGENT_LANDING={e['agent_id']}")
    print(f"  MA_VAULT_LANDING={e['vault_id']}")


if __name__ == "__main__":
    main()
