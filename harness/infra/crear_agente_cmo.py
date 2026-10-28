#!/usr/bin/env python3
"""Crea (o actualiza) en Claude Managed Agents lo que necesita el agente CMO del harness.

  1. Vault "5cero5 · CMO" con NOTION_TOKEN (integración "5cero5 agentes"), solo en encabezados hacia api.notion.com.
     Es un bot: lo que escribe nunca cuenta como aprobación de Al o Bonzo.
  2. Entorno común "5cero5-harness": se le reaplica la red con api.notion.com.
  3. Agente "5cero5 · CMO" con el prompt de harness/agentes/cmo.md.

Imprime las variables que van en Netlify: MA_AGENT_CMO y MA_VAULT_CMO (y MA_ENVIRONMENT_ID, que no cambia).
NOTION_TOKEN_AGENTES solo hace falta la primera vez o para cambiar el token: si el vault ya tiene la credencial,
se deja como está (por ejemplo, para subir solo el prompt con --actualizar-agente).

  cd harness/infra
  read -rs "ANTHROPIC_API_KEY?Llave de Anthropic: " && export ANTHROPIC_API_KEY && echo
  read -rs "NOTION_TOKEN_AGENTES?Token de la integración 5cero5 agentes: " && export NOTION_TOKEN_AGENTES && echo
  uv run --with "anthropic>=1.12" python crear_agente_cmo.py
  uv run --with "anthropic>=1.12" python crear_agente_cmo.py --cliente <slug>   vault de otro cliente (el agente es común)
"""
from __future__ import annotations

import argparse
import os

from comun import AGENTES, CLIENTE_BASE, agente_comun, alta, arg_cliente, carga, clave_de, cliente, entorno, imprime_ficha, meta_de, need

MODELO = os.environ.get("MODELO_CMO", "claude-sonnet-5-5")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--actualizar-agente", action="store_true", help="sube prompt y modelo a una versión nueva del agente")
    arg_cliente(ap)
    a = ap.parse_args()
    slug = cliente(a)
    clave = clave_de(slug, "cmo")
    need("ANTHROPIC_API_KEY")
    token = os.environ.get("NOTION_TOKEN_AGENTES", "").strip()
    if not token and "cred_notion_id" not in carga(clave):
        need("NOTION_TOKEN_AGENTES")  # primera vez: sin token no hay credencial
    prompt = (AGENTES / "cmo.md").read_text(encoding="utf-8")

    from anthropic import Anthropic
    b = Anthropic().beta
    meta = meta_de(slug, "cmo", "crear_agente_cmo.py")
    env_id = entorno(b)
    e = alta(b, clave=clave, vault_nombre=f"{slug} · CMO", meta=meta, actualizar=a.actualizar_agente,
             credenciales=[{"key": "cred_notion_id", "secret_name": "NOTION_TOKEN", "value": token,
                            "host": "api.notion.com", "label": "Notion · integración 5cero5 agentes"}] if token else [],
             agente=agente_comun(slug, "cmo", {"name": "5cero5 · CMO", "description": "Desglosa campañas aprobadas en filas Propuesta. Nunca aprueba.",
                                                "model": MODELO, "system": prompt}))

    if slug == CLIENTE_BASE:
        print("\nVariables para el proyecto de Netlify del harness (no son secretas):")
        print(f"  MA_ENVIRONMENT_ID={env_id}")
        print(f"  MA_AGENT_CMO={e['agent_id']}")
        print(f"  MA_VAULT_CMO={e['vault_id']}")
    imprime_ficha(slug, {"Vault CMO": e["vault_id"]})


if __name__ == "__main__":
    main()
