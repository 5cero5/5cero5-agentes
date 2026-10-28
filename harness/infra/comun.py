"""Piezas comunes de los scripts de alta de agentes (harness/infra/crear_agente_*.py).

- Un solo entorno para todo el harness ("5cero5-harness"). Su red es la unión de los hosts que necesitan
  los agentes; cada script la reaplica completa, así ninguno le quita hosts a otro.
- Un vault por agente, con credenciales environment_variable que solo se sustituyen en encabezados y solo
  hacia el host de esa credencial.
- Estado local por agente en infra/estado-<agente>.json y del entorno en infra/estado-entorno.json
  (ids de la cuenta, no secretos; no se versionan).
- Por cliente (--cliente <slug>, por defecto 5cero5): un vault por cliente y agente, con metadata
  {cliente: <slug>, rol: <agente>}, que es lo que el harness exige con RUTEO_CLIENTES=1. El agente es uno para todos
  los clientes: solo se crea o actualiza con el cliente 5cero5. El estado de otro cliente va en estado-<slug>-<agente>.json.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
AGENTES = AQUI.parent / "agentes"

# Red del entorno: agregar aquí el host de cada agente nuevo.
HOSTS = [
    "services.leadconnectorhq.com",   # CRM: API de HighLevel
    "firebasestorage.googleapis.com", # CRM: HTML guardado de las plantillas (correo.py comprobar)
    "api.notion.com",                 # CMO: leer campañas y proponer filas
    "api.github.com",                 # Landing y Creativo: PRs en 5cero5-landings y 5cero5-piezas (nunca fusionan)
    "graph.facebook.com",             # Pauta: Marketing API (crea en pausa; el token solo va en su vault)
    "api.higgsfield.ai",              # Creativo: fotos con Higgsfield (solo si el brief las pide; llave solo en su vault)
    "cdn.playwright.dev",             # Landing y Creativo: navegador para render y Verificador (playwright install chromium)
    "playwright.download.prss.microsoft.com",
    "playwright.azureedge.net",
]
# Hosts que se conocen al correr un script (por ejemplo, el que sirve las imágenes de Higgsfield): se guardan en
# estado-entorno.json ("hosts_extra") para que ningún otro script los quite al reaplicar la red.
def red(extra: list[str] | None = None) -> dict:
    hosts = list(dict.fromkeys(HOSTS + list(extra or [])))
    return {"type": "limited", "allowed_hosts": hosts, "allow_mcp_servers": False, "allow_package_managers": True}


RED = red()
PAQUETES = {"pip": ["httpx", "playwright", "pillow"]}  # playwright: render y Verificador (el navegador se baja en la sesión); pillow: Verificador de piezas
HERRAMIENTAS = [{
    "type": "agent_toolset_20260401",
    "default_config": {"enabled": True, "permission_policy": {"type": "always_allow"}},
    "configs": [{"name": "web_fetch", "enabled": False}, {"name": "web_search", "enabled": False}],
}]


def need(v: str) -> str:
    x = os.environ.get(v, "").strip()
    if not x:
        sys.exit(f"✗ Falta la variable de entorno {v}.")
    return x


CLIENTE_BASE = "5cero5"  # el cliente 0: su estado y su vault son los de siempre (estado-<agente>.json)
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def arg_cliente(ap) -> None:
    ap.add_argument("--cliente", default=CLIENTE_BASE,
                    help="slug del cliente (el de su ficha en Notion). Crea su vault con metadata cliente/rol; el agente es común")


def cliente(a) -> str:
    """Slug validado. Con otro cliente no se toca el agente común: --actualizar-agente solo va con el cliente base."""
    if not SLUG.match(a.cliente or ""):
        sys.exit(f"✗ --cliente inválido: {a.cliente!r} (minúsculas, números y guiones, como el Slug de la ficha).")
    if a.cliente != CLIENTE_BASE and getattr(a, "actualizar_agente", False):
        sys.exit(f"✗ El agente es común a todos los clientes: actualízalo sin --cliente (o con --cliente {CLIENTE_BASE}).")
    return a.cliente


def clave_de(slug: str, rol: str) -> str:
    return rol if slug == CLIENTE_BASE else f"{slug}-{rol}"


def meta_de(slug: str, rol: str, script: str) -> dict:
    return {"cliente": slug, "rol": rol, "origen": f"harness/infra/{script}"}


def agente_comun(slug: str, rol: str, agente: dict) -> dict | None:
    """El agente solo se crea o actualiza con el cliente base; con otro cliente, None (solo vault y credenciales)."""
    return agente if slug == CLIENTE_BASE else None


def imprime_ficha(slug: str, campos: dict) -> None:
    """Lo que va en la ficha del cliente en Notion (base Clientes). Son ids, no secretos."""
    print(f"\nPara la ficha de {slug} en Notion (base Clientes; no son secretos):")
    for k, v in campos.items():
        if v:
            print(f"  {k}: {v}")


def carga(nombre: str) -> dict:
    f = AQUI / f"estado-{nombre}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def guarda(nombre: str, estado: dict) -> None:
    (AQUI / f"estado-{nombre}.json").write_text(json.dumps(estado, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def entorno(b, hosts_extra: list[str] | None = None) -> str:
    """Crea el entorno común o le reaplica la red y los paquetes completos. Adopta el id que haya creado una versión anterior.
    hosts_extra se suma a los que ya estaban guardados en estado-entorno.json."""
    e = carga("entorno")
    if hosts_extra:
        e["hosts_extra"] = list(dict.fromkeys(e.get("hosts_extra", []) + hosts_extra))
        guarda("entorno", e)
    RED = red(e.get("hosts_extra"))
    if "environment_id" not in e and "environment_id" in carga("crm"):
        e["environment_id"] = carga("crm")["environment_id"]
        guarda("entorno", e)
    if "environment_id" not in e:
        env = b.environments.create(
            name="5cero5-harness",
            description="Entorno común del harness de 5cero5. Red: la lista HOSTS de harness/infra/comun.py.",
            metadata={"cliente": "5cero5", "origen": "harness/infra/comun.py"},
            config={"type": "cloud", "networking": RED, "packages": PAQUETES},
        )
        e["environment_id"] = env.id
        guarda("entorno", e)
        print(f"▸ Entorno creado: {env.id}")
    else:
        b.environments.update(e["environment_id"], config={"type": "cloud", "networking": RED, "packages": PAQUETES})
        print(f"▸ Entorno {e['environment_id']}: red = {', '.join(RED['allowed_hosts'])} · pip = {', '.join(PAQUETES['pip'])}")
    return e["environment_id"]


def alta(b, *, clave: str, vault_nombre: str, credenciales: list[dict], agente: dict | None, actualizar: bool, meta: dict) -> dict:
    """Vault + credenciales + agente, idempotente. credenciales: [{key, secret_name, value, host, label}].
    agente=None: solo vault y credenciales (otro cliente; el agente común no se toca)."""
    estado = carga(clave)
    if "vault_id" not in estado:
        estado["vault_id"] = b.vaults.create(display_name=vault_nombre, metadata=meta).id
        guarda(clave, estado)
        print(f"▸ Vault creado: {estado['vault_id']}")
    for cr in credenciales:
        if cr["key"] in estado:
            b.vaults.credentials.update(estado[cr["key"]], vault_id=estado["vault_id"],
                                        auth={"type": "environment_variable", "secret_value": cr["value"]})
            print(f"▸ Credencial {cr['secret_name']} actualizada")
            continue
        c = b.vaults.credentials.create(
            estado["vault_id"], display_name=cr["label"], metadata=meta,
            auth={"type": "environment_variable", "secret_name": cr["secret_name"], "secret_value": cr["value"],
                  "networking": {"type": "limited", "allowed_hosts": [cr["host"]]},
                  "injection_location": {"header": True, "body": False}},
        )
        estado[cr["key"]] = c.id
        guarda(clave, estado)
        print(f"▸ Credencial {cr['secret_name']} creada (solo hacia {cr['host']}, en encabezados): {c.id}")
    if agente is None:
        return estado
    if "agent_id" not in estado:
        ag = b.agents.create(name=agente["name"], description=agente["description"], model=agente["model"],
                             system=agente["system"], metadata=meta, tools=HERRAMIENTAS)
        estado["agent_id"] = ag.id
        guarda(clave, estado)
        print(f"▸ Agente creado con {agente['model']}: {ag.id}")
    elif actualizar:
        actual = b.agents.retrieve(estado["agent_id"])
        ag = b.agents.update(estado["agent_id"], version=actual.version, model=agente["model"],
                             system=agente["system"], tools=HERRAMIENTAS)
        print(f"▸ Agente actualizado a la versión {getattr(ag, 'version', '?')}")
    return estado
