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

Imprime las variables que van en Netlify: MA_AGENT_CREATIVO, MA_VAULT_CREATIVO y MA_CRED_GITHUB_CREATIVO.
Se puede correr varias veces: no duplica nada. Con --actualizar-agente sube prompt y modelo a una versión nueva.

  cd harness/infra
  read -rs "ANTHROPIC_API_KEY?Llave de Anthropic: " && export ANTHROPIC_API_KEY && echo
  read -rs "HF_API_KEY?Llave de Higgsfield (ID:secreto, Enter para omitir): " && export HF_API_KEY && echo
  uv run --with "anthropic>=1.12" python crear_agente_creativo.py --hf-files-host <host de las imágenes>
  uv run --with "anthropic>=1.12" python crear_agente_creativo.py --cliente <slug>   vault de otro cliente (el agente es común)
"""
from __future__ import annotations

import argparse
import os
import re

from comun import AGENTES, CLIENTE_BASE, agente_comun, alta, arg_cliente, carga, clave_de, cliente, entorno, imprime_ficha, meta_de, need

MODELO = os.environ.get("MODELO_CREATIVO", "claude-sonnet-5-5")
RELLENO = "se-renueva-en-cada-sesion"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--actualizar-agente", action="store_true", help="sube prompt y modelo a una versión nueva del agente")
    ap.add_argument("--hf-files-host", help="host que sirve las imágenes terminadas de Higgsfield (la prueba 3 lo imprimió)")
    arg_cliente(ap)
    a = ap.parse_args()
    slug = cliente(a)
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
    creds = []
    if "cred_github_id" not in estado:
        creds.append({"key": "cred_github_id", "secret_name": "GITHUB_TOKEN", "value": RELLENO, "host": "api.github.com",
                      "label": f"GitHub App 5cero5-agentes · piezas de {slug} (1 h)"})
    if hf_key:
        creds.append({"key": "cred_higgsfield_id", "secret_name": "HIGGSFIELD_API_KEY", "value": hf_key, "host": "api.higgsfield.ai",
                      "label": "Higgsfield · llave API · Creativo"})
    e = alta(b, clave=clave, vault_nombre=f"{slug} · Creativo", meta=meta, actualizar=a.actualizar_agente, credenciales=creds,
             agente=agente_comun(slug, "creativo", {"name": "5cero5 · Creativo", "description": "Arma piezas con las plantillas de marca y abre PRs en el repo de piezas del cliente con pr_pieza.py. Nunca fusiona ni publica.",
                                                    "model": MODELO, "system": prompt}))
    if "cred_higgsfield_id" not in e:
        print("⚠ Sin HIGGSFIELD_API_KEY: el Creativo hará piezas sin foto. Para agregarla: export HF_API_KEY y corre esto otra vez.")
    if not carga("entorno").get("hosts_extra"):
        print("⚠ Sin --hf-files-host: si un brief pide foto, se generará y se cobrará pero no se podrá bajar.")

    if slug == CLIENTE_BASE:
        print("\nVariables para el proyecto de Netlify del harness (no son secretas):")
        print(f"  MA_ENVIRONMENT_ID={env_id}")
        print(f"  MA_AGENT_CREATIVO={e['agent_id']}")
        print(f"  MA_VAULT_CREATIVO={e['vault_id']}")
        print(f"  MA_CRED_GITHUB_CREATIVO={e['cred_github_id']}")
    imprime_ficha(slug, {"Vault Creativo": e["vault_id"], "Credencial GitHub Creativo": e["cred_github_id"]})


if __name__ == "__main__":
    main()
