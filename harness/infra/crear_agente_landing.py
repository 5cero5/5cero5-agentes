#!/usr/bin/env python3
"""Crea (o actualiza) en Claude Managed Agents lo que necesita el agente Landing del harness.

  1. Vault "5cero5 · Landing" con la credencial GITHUB_TOKEN, que solo se sustituye en encabezados hacia api.github.com.
     Aquí se crea con un valor de relleno: el harness pone un token nuevo de la GitHub App (1 hora, solo escritura en
     5cero5-landings: contents y pull_requests) justo antes de cada sesión. Si el vault tenía el token de Netlify de la
     versión anterior, se borra.
  2. Entorno común "5cero5-harness": se le reaplican la red (api.github.com y las descargas de Playwright) y los paquetes.
  3. Agente "5cero5 · Landing" con el prompt de harness/agentes/landing.md.

Imprime las variables que van en Netlify: MA_AGENT_LANDING, MA_VAULT_LANDING y MA_CRED_GITHUB_LANDING.
Se puede correr varias veces: no duplica nada. Con --actualizar-agente sube prompt y modelo a una versión nueva.

  cd harness/infra
  read -rs "ANTHROPIC_API_KEY?Llave de Anthropic: " && export ANTHROPIC_API_KEY && echo
  uv run --with "anthropic>=1.12" python crear_agente_landing.py --actualizar-agente
  uv run --with "anthropic>=1.12" python crear_agente_landing.py --cliente <slug>   vault de otro cliente (el agente es común)
"""
from __future__ import annotations

import argparse
import os

from comun import AGENTES, CLIENTE_BASE, agente_comun, alta, arg_cliente, carga, clave_de, cliente, entorno, guarda, imprime_ficha, meta_de, need

MODELO = os.environ.get("MODELO_LANDING", "claude-sonnet-5-5")
RELLENO = "se-renueva-en-cada-sesion"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--actualizar-agente", action="store_true", help="sube prompt y modelo a una versión nueva del agente")
    arg_cliente(ap)
    a = ap.parse_args()
    slug = cliente(a)
    clave = clave_de(slug, "landing")
    need("ANTHROPIC_API_KEY")
    prompt = (AGENTES / "landing.md").read_text(encoding="utf-8")

    from anthropic import Anthropic
    b = Anthropic().beta
    meta = meta_de(slug, "landing", "crear_agente_landing.py")

    # La versión anterior publicaba en Netlify por API: su credencial ya no debe existir.
    estado = carga(clave)
    if estado.get("cred_netlify_id") and estado.get("vault_id"):
        b.vaults.credentials.delete(estado["cred_netlify_id"], vault_id=estado["vault_id"])
        print(f"▸ Credencial NETLIFY_TOKEN borrada del vault ({estado.pop('cred_netlify_id')}). Revoca también ese token en Netlify.")
        guarda(clave, estado)

    env_id = entorno(b)
    ya_tenia = "cred_github_id" in estado
    e = alta(b, clave=clave, vault_nombre=f"{slug} · Landing", meta=meta, actualizar=a.actualizar_agente,
             credenciales=[] if ya_tenia else [{"key": "cred_github_id", "secret_name": "GITHUB_TOKEN", "value": RELLENO,
                                                "host": "api.github.com", "label": f"GitHub App 5cero5-agentes · landings de {slug} (1 h)"}],
             agente=agente_comun(slug, "landing", {"name": "5cero5 · Landing", "description": "Abre PRs en el repo de landings del cliente con pr_landing.py. Nunca fusiona ni publica.",
                                                   "model": MODELO, "system": prompt}))

    if slug == CLIENTE_BASE:
        print("\nVariables para el proyecto de Netlify del harness (no son secretas):")
        print(f"  MA_ENVIRONMENT_ID={env_id}")
        print(f"  MA_AGENT_LANDING={e['agent_id']}")
        print(f"  MA_VAULT_LANDING={e['vault_id']}")
        print(f"  MA_CRED_GITHUB_LANDING={e['cred_github_id']}")
    imprime_ficha(slug, {"Vault Landing": e["vault_id"], "Credencial GitHub Landing": e["cred_github_id"]})


if __name__ == "__main__":
    main()
