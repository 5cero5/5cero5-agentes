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
  4. Con --canva: un agente APARTE, "5cero5 · Creativo · Canva" (mismo prompt; estado-creativo-canva.json), que declara el MCP
     oficial de Canva (mcp_servers + mcp_toolset de agentes/canva.json: lista cerrada, lectura always_allow y escritura always_ask,
     que aprueba el harness), y el entorno "5cero5-harness-canva", con su propia red mínima (canva.json: solo GitHub y la
     descarga de la exportación; el MCP lo conecta Anthropic con allow_mcp_servers). Solo las filas con
     "Canva: sí" usan ese agente y ese entorno (MA_AGENT_CREATIVO_CANVA, MA_ENVIRONMENT_CANVA); el agente común y el entorno común
     no cambian. La credencial de Canva se conecta desde la Console (vault del cliente → Add credential → MCP OAuth →
     https://mcp.canva.com/mcp → Connect); canva_oauth.py hace lo mismo con la llave de Anthropic.
  5. Con --imprimir-canva (sin llave ni API): imprime el entorno y el agente de Canva tal como los crea este script, para
     crearlos desde la Console (Environments → Create; Agents → Create, vista YAML).

Imprime las variables que van en Netlify: MA_AGENT_CREATIVO, MA_VAULT_CREATIVO y MA_CRED_GITHUB_CREATIVO.
Se puede correr varias veces: no duplica nada. Con --actualizar-agente sube prompt y modelo a una versión nueva.

  cd harness/infra
  read -rs "ANTHROPIC_API_KEY?Llave de Anthropic: " && export ANTHROPIC_API_KEY && echo
  read -rs "HF_API_KEY?Llave de Higgsfield (ID:secreto, Enter para omitir): " && export HF_API_KEY && echo
  uv run --with "anthropic>=1.12" python crear_agente_creativo.py --hf-files-host <host de las imágenes>
  uv run --with "anthropic>=1.12" python crear_agente_creativo.py --cliente <slug>   vault de otro cliente (el agente es común)
  uv run --with "anthropic>=1.12" python crear_agente_creativo.py --canva          agente y entorno de Canva (aparte del común)
  uv run --with "anthropic>=1.12" python crear_agente_creativo.py --canva --actualizar-agente   sube prompt y lista a los dos agentes
  python3 crear_agente_creativo.py --imprimir-canva   entorno y agente de Canva para pegar en la Console (no usa la API)
"""
from __future__ import annotations

import argparse
import json
import os
import re

from comun import (AGENTES, CLIENTE_BASE, HERRAMIENTAS, PAQUETES, agente_comun, alta, arg_cliente, carga, clave_de, cliente, entorno,
                   entorno_desde, imprime_ficha, mcp_canva, meta_de, need, red_canva)

MODELO = os.environ.get("MODELO_CREATIVO", "claude-sonnet-5-5")
RELLENO = "se-renueva-en-cada-sesion"
DESCRIPCION = "Arma piezas con las plantillas de marca o en Canva (diseño base aprobado) y abre PRs en el repo de piezas del cliente con pr_pieza.py. Nunca fusiona ni publica."


def config_canva(prompt: str) -> dict:
    """El entorno y el agente de Canva exactamente como los crea --canva (para crearlos desde la Console sin llave)."""
    servidores, tools_extra = mcp_canva()
    return {
        "entorno": {"name": "5cero5-harness-canva", "config": {"type": "cloud", "networking": red_canva(), "packages": PAQUETES},
                    "metadata": {"cliente": CLIENTE_BASE, "origen": "harness/infra/crear_agente_creativo.py --imprimir-canva"}},
        "agente": {"name": "5cero5 · Creativo · Canva", "description": DESCRIPCION, "model": MODELO, "system": prompt,
                   "tools": HERRAMIENTAS + tools_extra, "mcp_servers": servidores,
                   "metadata": {"cliente": CLIENTE_BASE, "rol": "creativo", "origen": "harness/infra/crear_agente_creativo.py --imprimir-canva"}},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--actualizar-agente", action="store_true", help="sube prompt y modelo a una versión nueva del agente")
    ap.add_argument("--hf-files-host", help="host que sirve las imágenes terminadas de Higgsfield (la prueba 3 lo imprimió)")
    ap.add_argument("--canva", action="store_true", help="crea o actualiza el agente de Canva (aparte del común) y su entorno")
    ap.add_argument("--solo-canva", metavar="ENTORNO_COMUN", help="solo el agente y el entorno de Canva: copia los paquetes del entorno común "
                    "<env_…> leídos de la API y no toca el entorno común, el agente común ni el vault (para cuando no tienes los estado-*.json)")
    ap.add_argument("--imprimir-canva", action="store_true", help="imprime el entorno y el agente de Canva en JSON para la Console; no usa la API")
    arg_cliente(ap)
    a = ap.parse_args()
    if a.imprimir_canva:
        print(json.dumps(config_canva((AGENTES / "creativo.md").read_text(encoding="utf-8")), ensure_ascii=False, indent=2))
        return
    slug = cliente(a)
    if a.canva and slug != CLIENTE_BASE:
        raise SystemExit("✗ El agente de Canva es común a todos los clientes: córrelo sin --cliente. La credencial de cada cliente la pone canva_oauth.py.")
    if a.solo_canva:
        a.canva = True
        if slug != CLIENTE_BASE or a.hf_files_host or not re.fullmatch(r"env_[A-Za-z0-9]+", a.solo_canva):
            raise SystemExit("✗ --solo-canva <env_…> va sin --cliente ni --hf-files-host, con el id del entorno común.")
    clave = clave_de(slug, "creativo")
    need("ANTHROPIC_API_KEY")
    if a.hf_files_host and not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", a.hf_files_host):
        raise SystemExit(f"✗ --hf-files-host debe ser solo el host (por ejemplo cdn.ejemplo.com), no {a.hf_files_host!r}")
    prompt = (AGENTES / "creativo.md").read_text(encoding="utf-8")
    hf_key = os.environ.get("HF_API_KEY", "").strip()

    from anthropic import Anthropic
    b = Anthropic().beta
    meta = meta_de(slug, "creativo", "crear_agente_creativo.py")

    descripcion = DESCRIPCION
    if a.solo_canva:  # solo lo nuevo de Canva; nada común se toca
        env_canva = entorno_desde(b, a.solo_canva, clave="entorno-canva", nombre="5cero5-harness-canva")
        servidores, tools_extra = mcp_canva()
        ec = alta(b, clave="creativo-canva", vault_nombre="", meta=meta, actualizar=a.actualizar_agente, credenciales=[], sin_vault=True,
                  agente={"name": "5cero5 · Creativo · Canva", "description": descripcion, "model": MODELO, "system": prompt,
                          "mcp_servers": servidores, "tools_extra": tools_extra})
        print("\nVariables para el proyecto de Netlify del harness (no son secretas):")
        print(f"  MA_AGENT_CREATIVO_CANVA={ec['agent_id']}   (solo filas con 'Canva: sí')")
        print(f"  MA_ENVIRONMENT_CANVA={env_canva}   (paquetes de {a.solo_canva}; red mínima de canva.json)")
        print("  CANVA_ACTIVO=1   (cuando el cliente tenga canva/recursos.json habilitado y su credencial: canva_oauth.py)")
        return
    env_id = entorno(b, [a.hf_files_host] if a.hf_files_host else None)
    estado = carga(clave)
    creds = []
    if "cred_github_id" not in estado:
        creds.append({"key": "cred_github_id", "secret_name": "GITHUB_TOKEN", "value": RELLENO, "host": "api.github.com",
                      "label": f"GitHub App 5cero5-agentes · piezas de {slug} (1 h)"})
    if hf_key:
        creds.append({"key": "cred_higgsfield_id", "secret_name": "HIGGSFIELD_API_KEY", "value": hf_key, "host": "api.higgsfield.ai",
                      "label": "Higgsfield · llave API · Creativo"})
    e = alta(b, clave=clave, vault_nombre=f"{slug} · Creativo", meta=meta, actualizar=a.actualizar_agente, credenciales=creds,
             agente=agente_comun(slug, "creativo", {"name": "5cero5 · Creativo", "description": descripcion, "model": MODELO, "system": prompt}))
    env_canva = agente_canva = None
    if a.canva:  # agente y entorno aparte: el común no cambia
        env_canva = entorno(b, clave="entorno-canva", nombre="5cero5-harness-canva")
        servidores, tools_extra = mcp_canva()
        agente_canva = alta(b, clave=clave, vault_nombre=f"{slug} · Creativo", meta=meta, actualizar=a.actualizar_agente, credenciales=[],
                            clave_agente="creativo-canva",
                            agente={"name": "5cero5 · Creativo · Canva", "description": descripcion, "model": MODELO, "system": prompt,
                                    "mcp_servers": servidores, "tools_extra": tools_extra})["agent_id"]
    if "cred_higgsfield_id" not in e:
        print("⚠ Sin HIGGSFIELD_API_KEY: el Creativo hará piezas sin foto. Para agregarla: export HF_API_KEY y corre esto otra vez.")
    if not carga("entorno").get("hosts_extra"):
        print("⚠ Sin --hf-files-host: si un brief pide foto, se generará y se cobrará pero no se podrá bajar.")

    if slug == CLIENTE_BASE:
        print("\nVariables para el proyecto de Netlify del harness (no son secretas):")
        print(f"  MA_ENVIRONMENT_ID={env_id}")
        print(f"  MA_AGENT_CREATIVO={e['agent_id']}")
        if agente_canva:
            print(f"  MA_AGENT_CREATIVO_CANVA={agente_canva}   (solo filas con 'Canva: sí')")
            print(f"  MA_ENVIRONMENT_CANVA={env_canva}   (red mínima de canva.json)")
            print("  CANVA_ACTIVO=1   (cuando el cliente tenga canva/recursos.json habilitado y su credencial: canva_oauth.py)")
        print(f"  MA_VAULT_CREATIVO={e['vault_id']}")
        print(f"  MA_CRED_GITHUB_CREATIVO={e['cred_github_id']}")
    imprime_ficha(slug, {"Vault Creativo": e["vault_id"], "Credencial GitHub Creativo": e["cred_github_id"]})


if __name__ == "__main__":
    main()
