#!/usr/bin/env python3
"""Crea (o actualiza) en Claude Managed Agents lo que necesita el agente CRM del harness.

  1. Vault "5cero5 · CRM" con la credencial HL_TOKEN, que solo se sustituye en encabezados
     hacia services.leadconnectorhq.com.
  2. Entorno "5cero5-harness": red limitada a HighLevel, con pip para instalar httpx.
  3. Agente "5cero5 · CRM" con el prompt de harness/agentes/crm.md.

Al final imprime las variables que van en el proyecto de Netlify del harness:
MA_ENVIRONMENT_ID, MA_AGENT_CRM y MA_VAULT_CRM.

Se puede correr varias veces: lo que ya existe (guardado en infra/estado-crm.json, que no se versiona)
no se duplica. Si cambias el token de HighLevel, vuelve a correrlo y se actualiza en el vault.
Con --actualizar-agente también sube el prompt y el modelo actuales a una versión nueva del agente.

Uso, desde la Terminal de Al (los secretos nunca van al chat ni al repo):

  cd harness/infra
  export ANTHROPIC_API_KEY=...        # llave del workspace de 5cero5
  export HL_TOKEN_CRM=pit-...         # integración privada SOLO con Email Builder (leer y escribir)
  export HL_LOCATION_ID=...           # id de la subcuenta 5cero5 en HighLevel
  uv run --with "anthropic>=1.12" python crear_agente_crm.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ESTADO = AQUI / "estado-crm.json"
PROMPT = AQUI.parent / "agentes" / "crm.md"
HL_HOST = "services.leadconnectorhq.com"
MODELO = os.environ.get("MODELO_CRM", "claude-sonnet-5-5")


def need(v: str) -> str:
    x = os.environ.get(v, "").strip()
    if not x:
        sys.exit(f"✗ Falta la variable de entorno {v}.")
    return x


def guarda(estado: dict) -> None:
    ESTADO.write_text(json.dumps(estado, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--actualizar-agente", action="store_true", help="sube prompt y modelo a una versión nueva del agente")
    a = ap.parse_args()

    need("ANTHROPIC_API_KEY")
    hl_token = need("HL_TOKEN_CRM")
    loc = need("HL_LOCATION_ID")
    if not hl_token.startswith("pit-"):
        sys.exit("✗ HL_TOKEN_CRM debe ser de integración privada (empieza con pit-).")
    prompt = PROMPT.read_text(encoding="utf-8").replace("__HL_LOCATION_ID__", loc)

    from anthropic import Anthropic
    b = Anthropic().beta
    estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}
    meta = {"cliente": "5cero5", "rol": "crm", "origen": "harness/infra/crear_agente_crm.py"}

    # 1. Vault y credencial
    if "vault_id" not in estado:
        estado["vault_id"] = b.vaults.create(display_name="5cero5 · CRM", metadata=meta).id
        guarda(estado)
        print(f"▸ Vault creado: {estado['vault_id']}")
    if "cred_hl_id" in estado:
        b.vaults.credentials.update(estado["cred_hl_id"], vault_id=estado["vault_id"],
                                    auth={"type": "environment_variable", "secret_value": hl_token})
        print("▸ Credencial HL_TOKEN actualizada")
    else:
        cred = b.vaults.credentials.create(
            estado["vault_id"],
            display_name="HighLevel · 5cero5 · Email Builder",
            metadata=meta,
            auth={
                "type": "environment_variable",
                "secret_name": "HL_TOKEN",
                "secret_value": hl_token,
                "networking": {"type": "limited", "allowed_hosts": [HL_HOST]},
                "injection_location": {"header": True, "body": False},
            },
        )
        estado["cred_hl_id"] = cred.id
        guarda(estado)
        print(f"▸ Credencial HL_TOKEN creada (solo hacia {HL_HOST}, en encabezados): {cred.id}")

    # 2. Entorno común del harness. Al sumar agentes se agregan sus hosts aquí.
    if "environment_id" not in estado:
        env = b.environments.create(
            name="5cero5-harness",
            description="Entorno del harness de 5cero5. Hoy: agente CRM (HighLevel). Agregar hosts al sumar agentes.",
            metadata={"cliente": "5cero5", "origen": meta["origen"]},
            config={
                "type": "cloud",
                "networking": {"type": "limited", "allowed_hosts": [HL_HOST],
                               "allow_mcp_servers": False, "allow_package_managers": True},
                "packages": {"pip": ["httpx"]},
            },
        )
        estado["environment_id"] = env.id
        guarda(estado)
        print(f"▸ Entorno creado: {env.id}")

    # 3. Agente
    herramientas = [{
        "type": "agent_toolset_20260401",
        "default_config": {"enabled": True, "permission_policy": {"type": "always_allow"}},
        "configs": [{"name": "web_fetch", "enabled": False}, {"name": "web_search", "enabled": False}],
    }]
    if "agent_id" not in estado:
        ag = b.agents.create(name="5cero5 · CRM", description="Plantillas de correo en HighLevel con correo.py. Nunca envía.",
                             model=MODELO, system=prompt, metadata=meta, tools=herramientas)
        estado["agent_id"] = ag.id
        guarda(estado)
        print(f"▸ Agente creado con {MODELO}: {ag.id}")
    elif a.actualizar_agente:
        actual = b.agents.retrieve(estado["agent_id"])
        ag = b.agents.update(estado["agent_id"], version=actual.version, model=MODELO, system=prompt, tools=herramientas)
        print(f"▸ Agente actualizado a la versión {getattr(ag, 'version', '?')}")

    print("\nVariables para el proyecto de Netlify del harness (no son secretas):")
    print(f"  MA_ENVIRONMENT_ID={estado['environment_id']}")
    print(f"  MA_AGENT_CRM={estado['agent_id']}")
    print(f"  MA_VAULT_CRM={estado['vault_id']}")


if __name__ == "__main__":
    main()
