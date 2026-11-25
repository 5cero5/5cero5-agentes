#!/usr/bin/env python3
"""Autorización inicial de Canva para el agente Creativo de UN cliente: deja la credencial mcp_oauth (con refresh) en su vault.

Managed Agents renueva el token de Canva solo (refresh_token) pero no hace el primer OAuth: esto lo hace UNA vez por cliente,
con la identidad interna de Canva aprobada para ese cliente (no la del cliente final y nunca por pieza o proyecto). Después,
todas las sesiones del Creativo de ese cliente la reutilizan por su vault. Lo corre una persona de 5cero5 en su Terminal:

  cd harness/infra
  read -rs "ANTHROPIC_API_KEY?Llave de Anthropic: " && export ANTHROPIC_API_KEY && echo
  uv run --with "anthropic>=1.12" python canva_oauth.py --cliente 5cero5 --cuenta "<etiqueta de la cuenta de Canva aprobada>"
  uv run --with "anthropic>=1.12" python canva_oauth.py --cliente 5cero5 --solo-validar      sondea la credencial guardada
  uv run --with "anthropic>=1.12" python canva_oauth.py --cliente 5cero5 --renovar ...       nuevo consentimiento (solo si hace falta)

Qué hace, en orden, y se detiene al primer problema:
  1. Lee el Vault Creativo del cliente (estado-<cliente>-creativo.json, o --vault) y exige metadata {cliente, rol: creativo}.
  2. Si ya hay credencial de Canva y no pides --renovar: solo la valida. No repite consentimientos.
  3. Lee los metadatos OAuth públicos de mcp.canva.com y exige que coincidan con agentes/canva.json (emisor, endpoints, PKCE S256,
     cliente público y los scopes que pide el Creativo).
  4. Registra un cliente OAuth público (registro dinámico, sin secreto) con redirección a 127.0.0.1, abre el navegador con PKCE
     y state, y espera la vuelta en 127.0.0.1 (10 minutos). Quien consiente debe estar en Canva con la cuenta interna aprobada.
  5. Cambia el código por tokens y los escribe directo en el vault (credencial mcp_oauth con refresh y token_endpoint_auth none).
     Los tokens nunca se imprimen, no se guardan en disco ni pasan por Notion, el prompt o los logs.
  6. Valida con mcp_oauth_validate (sondeo initialize contra el MCP de Canva) e imprime solo estado, método y código HTTP.

Guarda en estado-<…>creativo.json solo ids (credencial y client_id público). Prueba sin red: python3 test_canva_oauth.py.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone

from comun import CANVA, arg_cliente, carga, clave_de, cliente, guarda, need

UA = "5cero5-canva-oauth"
ESPERA_S = int(os.environ.get("CANVA_OAUTH_ESPERA_S", "600"))


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    """Ninguna redirección: el registro y el cambio de código van solo al host fijado en agentes/canva.json."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirección no permitida", headers, fp)


_HTTP = urllib.request.build_opener(_SinRedirecciones())


def base_oauth() -> str:
    """https://mcp.canva.com, o un servidor de prueba en 127.0.0.1 (solo pruebas; nunca otro host)."""
    b = os.environ.get("CANVA_OAUTH_BASE", "").rstrip("/")
    if not b:
        return CANVA["oauth"]["issuer"]
    if not re.fullmatch(r"http://127\.0\.0\.1:\d+", b):
        sys.exit("✗ CANVA_OAUTH_BASE solo acepta http://127.0.0.1:<puerto> (pruebas).")
    return b


def esperado() -> dict:
    """Metadatos que se exigen: los de agentes/canva.json, con el host de prueba si lo hay."""
    o = CANVA["oauth"]
    b = base_oauth()
    cambia = (lambda u: u.replace(o["issuer"], b, 1)) if b != o["issuer"] else (lambda u: u)
    return {"issuer": cambia(o["issuer"]), "authorization_endpoint": cambia(o["authorization_endpoint"]), "token_endpoint": cambia(o["token_endpoint"]),
            "registration_endpoint": cambia(o["registration_endpoint"]), "resource": cambia(o["resource"]), "scopes": list(o["scopes"])}


def pide(metodo: str, url: str, datos: dict | None = None, form: bool = False) -> dict:
    cuerpo, cab = None, {"User-Agent": UA, "Accept": "application/json"}
    if datos is not None:
        if form:
            cuerpo = urllib.parse.urlencode(datos).encode()
            cab["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            cuerpo = json.dumps(datos).encode()
            cab["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=cuerpo, method=metodo, headers=cab)
    try:
        with _HTTP.open(req, timeout=30) as r:
            return json.loads(r.read(1_000_000) or b"{}")
    except urllib.error.HTTPError as e:
        # Solo el código y el tipo de error OAuth: nunca el cuerpo completo (podría traer datos de la cuenta).
        try:
            err = json.loads(e.read(4000) or b"{}").get("error", "")
        except Exception:  # noqa: BLE001
            err = ""
        sys.exit(f"✗ {metodo} {urllib.parse.urlsplit(url).path}: HTTP {e.code}{f' ({err})' if err else ''}. No se escribió nada en el vault.")
    except (urllib.error.URLError, socket.timeout) as e:
        sys.exit(f"✗ {metodo} {urllib.parse.urlsplit(url).path}: {e}. No se escribió nada en el vault.")


def descubre() -> dict:
    e = esperado()
    pr = pide("GET", f"{base_oauth()}/.well-known/oauth-protected-resource/mcp")
    asm = pide("GET", f"{base_oauth()}/.well-known/oauth-authorization-server")
    malos = []
    if pr.get("resource") != e["resource"]:
        malos.append(f"resource {pr.get('resource')!r}")
    if e["issuer"] not in (pr.get("authorization_servers") or []):
        malos.append("servidor de autorización")
    for k in ("issuer", "authorization_endpoint", "token_endpoint", "registration_endpoint"):
        if asm.get(k) != e[k]:
            malos.append(f"{k} {asm.get(k)!r}")
    if "S256" not in (asm.get("code_challenge_methods_supported") or []):
        malos.append("sin PKCE S256")
    if "none" not in (asm.get("token_endpoint_auth_methods_supported") or []):
        malos.append("sin cliente público (token_endpoint_auth none)")
    if "refresh_token" not in (asm.get("grant_types_supported") or []):
        malos.append("sin refresh_token")
    faltan = [s for s in e["scopes"] if s not in (pr.get("scopes_supported") or [])]
    if faltan:
        malos.append(f"scopes que ya no ofrece: {', '.join(faltan)}")
    if malos:
        sys.exit(f"✗ Los metadatos OAuth de Canva no coinciden con agentes/canva.json: {'; '.join(malos)}. No se pidió consentimiento.")
    return e


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def espera_vuelta(estado: str) -> tuple[http.server.HTTPServer, dict, threading.Event]:
    """Servidor de un solo uso en 127.0.0.1 (puerto libre). Solo acepta /callback con el state exacto."""
    recibido: dict = {}
    listo = threading.Event()

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):  # no se registra la URL (lleva el código)
            pass

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            if u.path != "/callback" or listo.is_set():
                self.send_response(404)
                self.end_headers()
                return
            ok = secrets.compare_digest(q.get("state", ""), estado) and bool(q.get("code")) and not q.get("error")
            recibido.update(ok=ok, code=q.get("code") if ok else None, error=q.get("error", "" if ok else "state_o_codigo_invalido"))
            listo.set()
            cuerpo = ("Listo: ya puedes cerrar esta pestaña y volver a la Terminal." if ok else "No se completó la autorización. Vuelve a la Terminal.").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, recibido, listo


def credencial_existente(b, vault_id: str):
    url = CANVA["servidor"]["url"].rstrip("/").lower()
    for cr in b.vaults.credentials.list(vault_id):
        auth = getattr(cr, "auth", None)
        if getattr(cr, "archived_at", None) or getattr(auth, "type", None) != "mcp_oauth":
            continue
        if str(getattr(auth, "mcp_server_url", "")).rstrip("/").lower() == url:
            return cr
    return None


def valida(b, vault_id: str, cred_id: str) -> bool:
    v = b.vaults.credentials.mcp_oauth_validate(cred_id, vault_id=vault_id)
    probe = getattr(v, "mcp_probe", None)
    http_r = getattr(probe, "http_response", None) if probe else None
    ref = getattr(v, "refresh", None)
    print(f"▸ Validación de la credencial {cred_id}: {v.status}"
          + (f" · sondeo {getattr(probe, 'method', '?')} → HTTP {getattr(http_r, 'status_code', '?')} ({getattr(http_r, 'content_type', '?')})" if probe else "")
          + f" · refresh_token: {'sí' if getattr(v, 'has_refresh_token', False) else 'no'}"
          + (f" · refresh: {getattr(ref, 'status', '?')}" if ref else ""))
    if v.status == "valid":
        return True
    print("✗ La credencial no quedó válida. 'invalid' = el servidor la rechazó (repetir --renovar con la cuenta aprobada, una vez);"
          " 'unknown' = error transitorio de Canva (5xx/429/red): reintentar --solo-validar más tarde, sin nuevo consentimiento.")
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    arg_cliente(ap)
    ap.add_argument("--vault", help="id del Vault Creativo (si no, el de estado-<cliente>-creativo.json)")
    ap.add_argument("--cuenta", help="etiqueta de la cuenta de Canva aprobada (va en la metadata; no es secreta)")
    ap.add_argument("--renovar", action="store_true", help="nuevo consentimiento aunque ya haya credencial")
    ap.add_argument("--solo-validar", action="store_true", help="solo sondea la credencial guardada")
    a = ap.parse_args()
    slug = cliente(a)
    clave = clave_de(slug, "creativo")
    estado = carga(clave)
    vault_id = a.vault or estado.get("vault_id")
    if not vault_id:
        sys.exit(f"✗ No hay Vault Creativo de {slug}: corre crear_agente_creativo.py{'' if slug == '5cero5' else f' --cliente {slug}'} o pasa --vault.")
    need("ANTHROPIC_API_KEY")
    from anthropic import Anthropic
    b = Anthropic().beta

    v = b.vaults.retrieve(vault_id)
    md = getattr(v, "metadata", None) or {}
    if getattr(v, "archived_at", None) or md.get("cliente") != slug or md.get("rol") != "creativo":
        sys.exit(f"✗ El vault {vault_id} no es el Vault Creativo de {slug} (metadata cliente={md.get('cliente')}, rol={md.get('rol')}). No se toca.")
    actual = credencial_existente(b, vault_id)
    if a.solo_validar or (actual and not a.renovar):
        if not actual:
            sys.exit(f"✗ El vault {vault_id} no tiene credencial de Canva. Corre sin --solo-validar.")
        print(f"▸ Ya hay credencial de Canva en el vault de {slug} ({actual.id}): no se pide otro consentimiento.")
        sys.exit(0 if valida(b, vault_id, actual.id) else 1)
    if not a.cuenta or not re.fullmatch(r"[\w.@ ·+-]{3,80}", a.cuenta):
        sys.exit("✗ Falta --cuenta: una etiqueta de la cuenta interna de Canva aprobada (por ejemplo \"5cero5 · Creativo\").")

    e = descubre()
    verificador = secrets.token_urlsafe(64)
    estado_oauth = secrets.token_urlsafe(32)
    srv, recibido, listo = espera_vuelta(estado_oauth)
    redirect = f"http://127.0.0.1:{srv.server_address[1]}/callback"
    try:
        reg = pide("POST", e["registration_endpoint"], {
            "client_name": f"5cero5 · Creativo · {slug}", "redirect_uris": [redirect], "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "token_endpoint_auth_method": "none", "scope": " ".join(e["scopes"])})
        client_id = reg.get("client_id")
        if not client_id or reg.get("client_secret"):
            sys.exit("✗ El registro no devolvió un cliente público (client_id sin secreto). No se pidió consentimiento.")
        url = e["authorization_endpoint"] + "?" + urllib.parse.urlencode({
            "response_type": "code", "client_id": client_id, "redirect_uri": redirect, "scope": " ".join(e["scopes"]), "state": estado_oauth,
            "code_challenge": b64url(hashlib.sha256(verificador.encode()).digest()), "code_challenge_method": "S256", "resource": e["resource"]})
        print("▸ Abre esta dirección con la cuenta interna de Canva aprobada y acepta (no la compartas; caduca en minutos):")
        print(f"  {url}", flush=True)
        if os.environ.get("CANVA_OAUTH_NAVEGADOR", "1") != "0":
            webbrowser.open(url)
        if not listo.wait(ESPERA_S):
            sys.exit("✗ No llegó la autorización a tiempo. No se escribió nada en el vault.")
    finally:
        srv.shutdown()
    if not recibido.get("ok"):
        sys.exit(f"✗ La autorización no se completó ({recibido.get('error') or 'sin código'}). No se escribió nada en el vault.")

    tok = pide("POST", e["token_endpoint"], {"grant_type": "authorization_code", "code": recibido.pop("code"), "redirect_uri": redirect,
                                              "client_id": client_id, "code_verifier": verificador, "resource": e["resource"]}, form=True)
    acceso, renovar = tok.pop("access_token", None), tok.pop("refresh_token", None)
    if not acceso or str(tok.get("token_type", "bearer")).lower() != "bearer":
        sys.exit("✗ Canva no devolvió un token Bearer. No se escribió nada en el vault.")
    if not renovar:
        sys.exit("✗ Canva no devolvió refresh_token: sin él la credencial caduca y no se renueva sola. No se escribió nada en el vault.")
    vence = (datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in") or 3600))).strftime("%Y-%m-%dT%H:%M:%SZ")
    refresh = {"token_endpoint": e["token_endpoint"], "client_id": client_id, "scope": tok.get("scope") or " ".join(e["scopes"]),
               "refresh_token": renovar, "token_endpoint_auth": {"type": "none"}}
    meta = {"cliente": slug, "rol": "canva", "canva_cuenta": a.cuenta, "origen": "harness/infra/canva_oauth.py"}
    if actual:  # client_id y token_endpoint no se pueden cambiar: se archiva la anterior y se crea otra
        b.vaults.credentials.archive(actual.id, vault_id=vault_id)
        print(f"▸ Credencial anterior {actual.id} archivada (su secreto se purga).")
    cr = b.vaults.credentials.create(vault_id, display_name=f"Canva MCP · {slug} · Creativo", metadata=meta,
                                     auth={"type": "mcp_oauth", "mcp_server_url": CANVA["servidor"]["url"], "access_token": acceso,
                                           "expires_at": vence, "refresh": refresh})
    acceso = renovar = refresh = None  # noqa: F841 — fuera de memoria cuanto antes
    estado = carga(clave)
    estado.update(cred_canva_id=cr.id, canva_client_id=client_id, canva_autorizado_el=time.strftime("%Y-%m-%d"))
    guarda(clave, estado)
    print(f"▸ Credencial de Canva creada en el vault de {slug}: {cr.id} (metadata cliente={slug}, rol=canva, cuenta={a.cuenta}).")
    sys.exit(0 if valida(b, vault_id, cr.id) else 1)


if __name__ == "__main__":
    main()
