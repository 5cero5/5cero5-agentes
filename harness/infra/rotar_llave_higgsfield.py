#!/usr/bin/env python3
"""Reemplaza el valor de HIGGSFIELD_API_KEY en el vault Creativo de UN cliente, sin crear otra credencial.

  cd harness/infra
  read -rs "ANTHROPIC_API_KEY?Llave de Anthropic: " && export ANTHROPIC_API_KEY && echo
  uv run --with "anthropic>=1.12" python rotar_llave_higgsfield.py --cliente <slug> --vault <vlt_…>
  unset ANTHROPIC_API_KEY

Pide ocultas (getpass: no quedan en el historial, en variables ni en archivos):
  - la llave NUEVA (ID:secreto), dos veces;
  - la llave ANTERIOR, la que siguen usando los vaults de otros clientes. Los vaults nunca devuelven el valor guardado,
    así que la única forma de comprobar que la nueva es distinta es compararlas aquí: se compara su SHA-256 en memoria
    y no se imprime nada de ninguna de las dos.

Antes de cambiar comprueba, con lecturas de metadatos: que --vault es el vault Creativo del cliente en estado-<slug>-creativo.json
y que su metadata dice {cliente: <slug>, rol: creativo}; que la credencial es HIGGSFIELD_API_KEY de ese vault y no está
archivada; y que ningún otro cliente usa ese vault. Nunca toca el vault de 5cero5 ni el de otro cliente.
Cambia solo el valor y vuelve a fijar la red de la credencial en api.higgsfield.ai. Después relee los metadatos.
No llama a Higgsfield ni gasta: que la llave nueva funcione se ve en la primera foto.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import re
import sys

from comun import AQUI, CLIENTE_BASE, SLUG, carga

HOST = "api.higgsfield.ai"
SECRET_NAME = "HIGGSFIELD_API_KEY"
FORMATO = re.compile(r"^[^:\s]+:[^:\s]+$")


class Alto(SystemExit):
    pass


def alto(msg: str) -> None:
    raise Alto(f"✗ {msg} No se cambió nada.")


def huella(llave: str) -> bytes:
    return hashlib.sha256(llave.encode()).digest()


def otros_vaults(slug: str) -> dict[str, str]:
    """vault_id → dueño, de los estado-*.json locales que no son de este cliente."""
    out = {}
    for f in AQUI.glob("estado-*.json"):
        nombre = f.stem.removeprefix("estado-")
        if nombre in ("entorno", f"{slug}-creativo") or nombre.startswith(f"{slug}-"):
            continue
        v = carga(nombre).get("vault_id")
        if v:
            out[v] = nombre
    return out


def rotar(b, *, slug: str, vault: str, nueva: str, confirmacion: str, anterior: str) -> dict:
    """Valida, actualiza y relee. b = Anthropic().beta (o uno falso en las pruebas). Regresa los metadatos releídos."""
    if not SLUG.match(slug) or slug == CLIENTE_BASE:
        alto(f"--cliente debe ser el slug de un cliente distinto de {CLIENTE_BASE} (este script no toca el vault de {CLIENTE_BASE}).")
    estado = carga(f"{slug}-creativo")
    if estado.get("vault_id") != vault:
        alto(f"{vault} no es el vault Creativo de {slug} (estado-{slug}-creativo.json dice {estado.get('vault_id') or 'nada'}).")
    cred_id = estado.get("cred_higgsfield_id")
    if not cred_id:
        alto(f"estado-{slug}-creativo.json no tiene cred_higgsfield_id: no hay credencial que actualizar (no se crea otra).")
    dueno = otros_vaults(slug).get(vault)
    if dueno:
        alto(f"{vault} también aparece como vault de {dueno}.")
    for nombre, x in (("nueva", nueva), ("anterior", anterior)):
        if not FORMATO.match(x):
            alto(f"La llave {nombre} no tiene formato ID:secreto.")
    if not hmac.compare_digest(huella(nueva), huella(confirmacion)):
        alto("La llave nueva y su confirmación no coinciden.")
    if hmac.compare_digest(huella(nueva), huella(anterior)):
        alto("La llave nueva es IGUAL a la anterior (la de los otros vaults).")

    v = b.vaults.retrieve(vault)
    meta = dict(getattr(v, "metadata", None) or {})
    if meta.get("cliente") != slug or meta.get("rol") != "creativo":
        alto(f"La metadata del vault es {meta}, no {{cliente: {slug}, rol: creativo}}.")
    antes = b.vaults.credentials.retrieve(cred_id, vault_id=vault)
    if getattr(antes, "vault_id", vault) != vault or getattr(antes, "archived_at", None):
        alto("La credencial no es de ese vault o está archivada.")
    if getattr(antes.auth, "secret_name", None) != SECRET_NAME:
        alto(f"La credencial {cred_id} no es {SECRET_NAME}.")

    b.vaults.credentials.update(cred_id, vault_id=vault, auth={
        "type": "environment_variable", "secret_value": nueva,
        "networking": {"type": "limited", "allowed_hosts": [HOST]}})

    despues = b.vaults.credentials.retrieve(cred_id, vault_id=vault)
    hosts = list(getattr(getattr(despues.auth, "networking", None), "allowed_hosts", None) or [])
    return {"credencial": cred_id, "vault": vault, "secret_name": getattr(despues.auth, "secret_name", None),
            "hosts": hosts, "antes": str(antes.updated_at), "despues": str(despues.updated_at),
            "actualizada": despues.updated_at > antes.updated_at, "red_ok": hosts == [HOST]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cliente", required=True, help="slug del cliente (el de su ficha)")
    ap.add_argument("--vault", required=True, help="id del vault Creativo de ese cliente (se compara con su estado local)")
    a = ap.parse_args()
    if not sys.stdin.isatty():
        sys.exit("✗ Corre esto en una Terminal interactiva: las llaves se piden ocultas.")
    nueva = getpass.getpass("Llave NUEVA de Higgsfield (ID:secreto): ").strip()
    confirmacion = getpass.getpass("Repite la llave nueva: ").strip()
    anterior = getpass.getpass("Llave ANTERIOR (la de los otros vaults), solo para compararlas: ").strip()
    from anthropic import Anthropic
    r = rotar(Anthropic().beta, slug=a.cliente, vault=a.vault, nueva=nueva, confirmacion=confirmacion, anterior=anterior)
    del nueva, confirmacion, anterior
    print("✓ La llave nueva es distinta de la anterior (comparación por SHA-256, sin imprimir ninguna).")
    print(f"✓ {r['credencial']} ({r['secret_name']}) en {r['vault']}: updated_at {r['antes']} → {r['despues']}"
          + ("" if r["actualizada"] else "  ⚠ NO cambió"))
    print(f"{'✓' if r['red_ok'] else '✗'} Red de la credencial: {r['hosts']}")
    print("· El valor no se puede releer (los vaults no lo devuelven): que funcione se confirma con la primera foto.")
    sys.exit(0 if r["actualizada"] and r["red_ok"] else 1)


if __name__ == "__main__":
    main()
