#!/usr/bin/env python3
"""Crea (o actualiza) en Claude Managed Agents lo que necesita el agente Creativo del harness.

  1. Vault "5cero5 · Creativo" con dos credenciales que solo se sustituyen en encabezados:
     - GITHUB_TOKEN, solo hacia api.github.com. Se crea con un valor de relleno: el harness pone un token nuevo de la
       GitHub App (1 hora, solo escritura en 5cero5-piezas: contents y pull_requests) justo antes de cada sesión.
     - HIGGSFIELD_API_KEY, solo hacia api.higgsfield.ai. Solo si exportas HF_API_KEY (formato ID:secreto). Sin ella el
       Creativo hace piezas sin foto; se puede agregar después corriendo esto otra vez con la variable.
  2. Entorno común "5cero5-harness": se le reaplican la red y los paquetes. Con --hf-files-host se agrega el host que
     sirve las imágenes de Higgsfield (sin él, la foto se genera y se cobra pero no se puede bajar).
  3. Agente "5cero5 · Creativo" con el prompt de harness/agentes/creativo.md.
  4. Con --canva: el agente declara el MCP oficial de Canva (mcp_servers + mcp_toolset de agentes/canva.json: lista cerrada, lectura
     always_allow y escritura always_ask, que aprueba el harness) y se crea o reaplica el entorno "5cero5-harness-creativo": la red
     común más los hosts de Canva, para que solo el Creativo llegue a Canva. Queda guardado: las corridas siguientes lo mantienen
     hasta --sin-canva. La credencial de Canva (OAuth inicial) la pone canva_oauth.py en el vault de cada cliente.
     Con --piloto, el agente con Canva es uno APARTE ("5cero5 · Creativo (piloto Canva)", estado-creativo-piloto.json): el agente
     común no cambia; el vault es el mismo del cliente.

Imprime las variables que van en Netlify: MA_AGENT_CREATIVO, MA_VAULT_CREATIVO y MA_CRED_GITHUB_CREATIVO.
Se puede correr varias veces: no duplica nada. Con --actualizar-agente sube prompt y modelo a una versión nueva.

  cd harness/infra
  read -rs "ANTHROPIC_API_KEY?Llave de Anthropic: " && export ANTHROPIC_API_KEY && echo
  read -rs "HF_API_KEY?Llave de Higgsfield (ID:secreto, Enter para omitir): " && export HF_API_KEY && echo
  uv run --with "anthropic>=1.12" python crear_agente_creativo.py --hf-files-host <host de las imágenes>
  uv run --with "anthropic>=1.12" python crear_agente_creativo.py --cliente <slug>   vault de otro cliente (el agente es común)
  uv run --with "anthropic>=1.12" python crear_agente_creativo.py --canva --piloto  agente aparte con Canva para el piloto
  uv run --with "anthropic>=1.12" python crear_agente_creativo.py --canva --actualizar-agente   Canva en el agente común
"""
from __future__ import annotations

import argparse
import os
import re

from comun import AGENTES, CANVA, CLIENTE_BASE, agente_comun, alta, arg_cliente, carga, clave_de, cliente, entorno, guarda, imprime_ficha, mcp_canva, meta_de, need

MODELO = os.environ.get("MODELO_CREATIVO", "claude-sonnet-5-5")
RELLENO = "se-renueva-en-cada-sesion"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--actualizar-agente", action="store_true", help="sube prompt y modelo a una versión nueva del agente")
    ap.add_argument("--hf-files-host", help="host que sirve las imágenes terminadas de Higgsfield (la prueba 3 lo imprimió)")
    ap.add_argument("--canva", action="store_true", help="el agente declara el MCP de Canva y usa el entorno propio del Creativo")
    ap.add_argument("--sin-canva", action="store_true", help="quita Canva del agente (vuelve al entorno común)")
    ap.add_argument("--piloto", action="store_true", help="con --canva: agente aparte para el piloto; el agente común no cambia")
    arg_cliente(ap)
    a = ap.parse_args()
    slug = cliente(a)
    if a.canva and a.sin_canva:
        raise SystemExit("✗ --canva y --sin-canva juntos no.")
    if a.piloto and not a.canva:
        raise SystemExit("✗ --piloto es para el agente con Canva: úsalo con --canva.")
    if (a.canva or a.sin_canva) and slug != CLIENTE_BASE:
        raise SystemExit("✗ Canva en el agente es común a todos los clientes: córrelo sin --cliente. La credencial de cada cliente la pone canva_oauth.py.")
    clave = clave_de(slug, "creativo")
    need("ANTHROPIC_API_KEY")
    if a.hf_files_host and not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", a.hf_files_host):
        raise SystemExit(f"✗ --hf-files-host debe ser solo el host (por ejemplo cdn.ejemplo.com), no {a.hf_files_host!r}")
    prompt = (AGENTES / "creativo.md").read_text(encoding="utf-8")
    hf_key = os.environ.get("HF_API_KEY", "").strip()

    from anthropic import Anthropic
    b = Anthropic().beta
    meta = meta_de(slug, "creativo", "crear_agente_creativo.py")

    env_id = entorno(b, [a.hf_files_host] if a.hf_files_host else None)
    estado = carga(clave)
    # Canva queda guardado en el estado del agente: las corridas siguientes no lo quitan sin --sin-canva.
    clave_agente = "creativo-piloto" if a.piloto else None
    ea = carga(clave_agente or clave)
    con_canva = bool(a.canva or (ea.get("canva") and not a.sin_canva))
    env_creativo = entorno(b, clave="entorno-creativo", nombre="5cero5-harness-creativo", solo=CANVA["hosts_red"]) if con_canva else None
    creds = []
    if "cred_github_id" not in estado:
        creds.append({"key": "cred_github_id", "secret_name": "GITHUB_TOKEN", "value": RELLENO, "host": "api.github.com",
                      "label": f"GitHub App 5cero5-agentes · piezas de {slug} (1 h)"})
    if hf_key:
        creds.append({"key": "cred_higgsfield_id", "secret_name": "HIGGSFIELD_API_KEY", "value": hf_key, "host": "api.higgsfield.ai",
                      "label": "Higgsfield · llave API · Creativo"})
    servidores, tools_extra = mcp_canva() if con_canva else ([], [])
    nombre = "5cero5 · Creativo (piloto Canva)" if a.piloto else "5cero5 · Creativo"
    e = alta(b, clave=clave, vault_nombre=f"{slug} · Creativo", meta=meta, actualizar=a.actualizar_agente or a.sin_canva or (a.canva and not ea.get("canva")),
             credenciales=creds, clave_agente=clave_agente,
             agente=agente_comun(slug, "creativo", {"name": nombre, "description": "Arma piezas con las plantillas de marca o en Canva (diseño base aprobado) y abre PRs en el repo de piezas del cliente con pr_pieza.py. Nunca fusiona ni publica.",
                                                    "model": MODELO, "system": prompt, "mcp_servers": servidores, "tools_extra": tools_extra}))
    if slug == CLIENTE_BASE:
        ea = carga(clave_agente or clave)
        ea["canva"] = con_canva
        guarda(clave_agente or clave, ea)
    if "cred_higgsfield_id" not in e:
        print("⚠ Sin HIGGSFIELD_API_KEY: el Creativo hará piezas sin foto. Para agregarla: export HF_API_KEY y corre esto otra vez.")
    if not carga("entorno").get("hosts_extra"):
        print("⚠ Sin --hf-files-host: si un brief pide foto, se generará y se cobrará pero no se podrá bajar.")

    if slug == CLIENTE_BASE:
        print("\nVariables para el proyecto de Netlify del harness (no son secretas):")
        print(f"  MA_ENVIRONMENT_ID={env_id}")
        print(f"  MA_AGENT_CREATIVO={e['agent_id']}" + ("   (agente del piloto con Canva)" if a.piloto else ""))
        if env_creativo:
            print(f"  MA_ENVIRONMENT_CREATIVO={env_creativo}   (entorno del Creativo con los hosts de Canva)")
            print("  CANVA_ACTIVO=1   (solo cuando el cliente tenga canva/recursos.json habilitado y su credencial: canva_oauth.py)")
        print(f"  MA_VAULT_CREATIVO={e['vault_id']}")
        print(f"  MA_CRED_GITHUB_CREATIVO={e['cred_github_id']}")
    imprime_ficha(slug, {"Vault Creativo": e["vault_id"], "Credencial GitHub Creativo": e["cred_github_id"]})


if __name__ == "__main__":
    main()
