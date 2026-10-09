#!/usr/bin/env python3
"""Crea (o actualiza) en Claude Managed Agents lo que necesita el agente CRM del harness.

  1. Vault "5cero5 · CRM" con HL_TOKEN, que solo se sustituye en encabezados hacia services.leadconnectorhq.com.
  2. Entorno común "5cero5-harness" (red y paquetes en infra/comun.py).
  3. Agente "5cero5 · CRM" con el prompt de harness/agentes/crm.md.

Imprime las variables que van en Netlify: MA_ENVIRONMENT_ID, MA_AGENT_CRM y MA_VAULT_CRM.
Se puede correr varias veces: no duplica nada y actualiza el token. Con --actualizar-agente sube prompt y modelo.

  cd harness/infra
  read -rs "ANTHROPIC_API_KEY?Llave de Anthropic: " && export ANTHROPIC_API_KEY && echo
  read -rs "HL_TOKEN_CRM?Token pit- de HighLevel (solo Email Builder): " && export HL_TOKEN_CRM && echo
  read -r  "HL_LOCATION_ID?Location ID: " && export HL_LOCATION_ID
  uv run --with "anthropic>=1.12" python crear_agente_crm.py
"""
from __future__ import annotations

import argparse
import os
import sys

from comun import AGENTES, alta, entorno, need

MODELO = os.environ.get("MODELO_CRM", "claude-sonnet-5-5")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--actualizar-agente", action="store_true", help="sube prompt y modelo a una versión nueva del agente")
    a = ap.parse_args()
    need("ANTHROPIC_API_KEY")
    hl_token, loc = need("HL_TOKEN_CRM"), need("HL_LOCATION_ID")
    if not hl_token.startswith("pit-"):
        sys.exit("✗ HL_TOKEN_CRM debe ser de integración privada (empieza con pit-).")
    prompt = (AGENTES / "crm.md").read_text(encoding="utf-8").replace("__HL_LOCATION_ID__", loc)

    from anthropic import Anthropic
    b = Anthropic().beta
    meta = {"cliente": "5cero5", "rol": "crm", "origen": "harness/infra/crear_agente_crm.py"}
    env_id = entorno(b)
    e = alta(b, clave="crm", vault_nombre="5cero5 · CRM", meta=meta, actualizar=a.actualizar_agente,
             credenciales=[{"key": "cred_hl_id", "secret_name": "HL_TOKEN", "value": hl_token,
                            "host": "services.leadconnectorhq.com", "label": "HighLevel · 5cero5 · Email Builder"}],
             agente={"name": "5cero5 · CRM", "description": "Plantillas de correo en HighLevel con correo.py. Nunca envía.",
                     "model": MODELO, "system": prompt})

    print("\nVariables para el proyecto de Netlify del harness (no son secretas):")
    print(f"  MA_ENVIRONMENT_ID={env_id}")
    print(f"  MA_AGENT_CRM={e['agent_id']}")
    print(f"  MA_VAULT_CRM={e['vault_id']}")


if __name__ == "__main__":
    main()
