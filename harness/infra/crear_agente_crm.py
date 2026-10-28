#!/usr/bin/env python3
"""Crea (o actualiza) en Claude Managed Agents lo que necesita el agente CRM del harness.

  1. Vault "<cliente> · CRM" con HL_TOKEN (integración privada de la subcuenta de ese cliente), que solo se sustituye
     en encabezados hacia services.leadconnectorhq.com. El Location ID ya no va en el prompt: va en la ficha del cliente.
  2. Entorno común "5cero5-harness" (red y paquetes en infra/comun.py).
  3. Agente "5cero5 · CRM" con el prompt de harness/agentes/crm.md.

Imprime las variables que van en Netlify: MA_ENVIRONMENT_ID, MA_AGENT_CRM y MA_VAULT_CRM.
Se puede correr varias veces: no duplica nada. HL_TOKEN_CRM solo hace falta la primera vez o para cambiar el token:
si no lo exportas y el vault ya tiene la credencial, se deja como está (por ejemplo, para subir solo el prompt con
--actualizar-agente). Si lo exportas, reemplaza el token del vault.

  cd harness/infra
  read -rs "ANTHROPIC_API_KEY?Llave de Anthropic: " && export ANTHROPIC_API_KEY && echo
  read -rs "HL_TOKEN_CRM?Token pit- de HighLevel (Email Builder; leer Locations si usas el ruteo por cliente): " && export HL_TOKEN_CRM && echo
  uv run --with "anthropic>=1.12" python crear_agente_crm.py [--cliente <slug>]
"""
from __future__ import annotations

import argparse
import os
import sys

from comun import AGENTES, CLIENTE_BASE, agente_comun, alta, arg_cliente, carga, clave_de, cliente, entorno, imprime_ficha, meta_de, need

MODELO = os.environ.get("MODELO_CRM", "claude-sonnet-5-5")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--actualizar-agente", action="store_true", help="sube prompt y modelo a una versión nueva del agente")
    arg_cliente(ap)
    a = ap.parse_args()
    slug = cliente(a)
    need("ANTHROPIC_API_KEY")
    hl_token = os.environ.get("HL_TOKEN_CRM", "").strip()
    if not hl_token and "cred_hl_id" not in carga(clave_de(slug, "crm")):
        need("HL_TOKEN_CRM")  # primera vez: sin token no hay credencial
    if hl_token and not hl_token.startswith("pit-"):
        sys.exit("✗ HL_TOKEN_CRM debe ser de integración privada (empieza con pit-).")
    prompt = (AGENTES / "crm.md").read_text(encoding="utf-8")

    from anthropic import Anthropic
    b = Anthropic().beta
    meta = meta_de(slug, "crm", "crear_agente_crm.py")
    env_id = entorno(b)
    e = alta(b, clave=clave_de(slug, "crm"), vault_nombre=f"{slug} · CRM", meta=meta, actualizar=a.actualizar_agente,
             credenciales=[{"key": "cred_hl_id", "secret_name": "HL_TOKEN", "value": hl_token,
                            "host": "services.leadconnectorhq.com", "label": f"HighLevel · {slug} · Email Builder"}] if hl_token else [],
             agente=agente_comun(slug, "crm", {"name": "5cero5 · CRM", "description": "Plantillas de correo en HighLevel con correo.py. Nunca envía.",
                                               "model": MODELO, "system": prompt}))

    if slug == CLIENTE_BASE:
        print("\nVariables para el proyecto de Netlify del harness (no son secretas):")
        print(f"  MA_ENVIRONMENT_ID={env_id}")
        print(f"  MA_AGENT_CRM={e['agent_id']}")
        print(f"  MA_VAULT_CRM={e['vault_id']}")
    imprime_ficha(slug, {"Vault CRM": e["vault_id"], "HighLevel Location ID": "(el de su subcuenta; lo escribes tú)"})


if __name__ == "__main__":
    main()
