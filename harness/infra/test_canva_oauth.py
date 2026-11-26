#!/usr/bin/env python3
"""Prueba de canva_oauth.py y de crear_agente_creativo.py --canva con un Canva OAuth FALSO (127.0.0.1) y un SDK de Anthropic FALSO.

  python3 test_canva_oauth.py

Comprueba: metadatos que no coinciden → no pide consentimiento; registro público con PKCE S256, state y resource; los tokens van al
vault y nunca a la salida ni a disco; con credencial ya guardada no repite consentimiento; vault de otro cliente no se toca;
state alterado no escribe nada; sin refresh_token no escribe nada; --canva declara el MCP con lista cerrada y entorno propio."""
import json, os, re, shutil, subprocess, sys, tempfile, threading, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
tmp = Path(tempfile.mkdtemp())
shutil.copytree(HERE, tmp / "infra", ignore=shutil.ignore_patterns("estado-*.json", "__pycache__", "test_*.py"))
shutil.copytree(HERE.parent / "agentes", tmp / "agentes")
LOG = tmp / "llamadas.jsonl"
CANVA = json.loads((HERE.parent / "agentes" / "canva.json").read_text())
ACCESO, RENOVAR = "tok-acceso-SECRETO-123", "tok-renovar-SECRETO-456"

(tmp / "falso" / "anthropic").mkdir(parents=True)
(tmp / "falso" / "anthropic" / "__init__.py").write_text('''
import json, os, itertools
_n = (f"{os.getpid()}_{i}" for i in itertools.count(1))
def _log(op, **kw):
    with open(os.environ["LOG_FALSO"], "a") as f: f.write(json.dumps({"op": op, **kw}, default=str) + "\\n")
class _Obj:
    def __init__(self, **kw): self.__dict__.update(kw)
def _creds():
    p = os.environ.get("CREDS_FALSAS")
    return json.loads(open(p).read()) if p and os.path.exists(p) else []
class _Creds:
    def create(self, vault_id, **kw): i = f"vcrd_{next(_n)}"; _log("cred.create", vault_id=vault_id, id=i, **kw); return _Obj(id=i)
    def update(self, cred_id, **kw): _log("cred.update", id=cred_id, **kw)
    def archive(self, cred_id, **kw): _log("cred.archive", id=cred_id, **kw)
    def list(self, vault_id): return [_Obj(id=c["id"], archived_at=None, auth=_Obj(**c["auth"]), metadata=c.get("metadata", {})) for c in _creds()]
    def mcp_oauth_validate(self, cred_id, **kw):
        _log("cred.validate", id=cred_id, **kw)
        return _Obj(status=os.environ.get("VALIDA_FALSA", "valid"), has_refresh_token=True,
                    mcp_probe=_Obj(method="initialize", http_response=_Obj(status_code=200, content_type="application/json")), refresh=None)
class _Vaults:
    credentials = _Creds()
    def create(self, **kw): i = f"vlt_{next(_n)}"; _log("vault.create", id=i, **kw); return _Obj(id=i)
    def retrieve(self, i): return _Obj(id=i, archived_at=None, metadata=json.loads(os.environ.get("VAULT_META", '{"cliente": "5cero5", "rol": "creativo"}')))
class _Agents:
    def create(self, **kw): i = f"agent_{next(_n)}"; _log("agent.create", id=i, **kw); return _Obj(id=i)
    def retrieve(self, i): return _Obj(id=i, version=1)
    def update(self, i, **kw): _log("agent.update", id=i, **kw); return _Obj(id=i, version=2)
class _Envs:
    def retrieve(self, i):
        _log("env.retrieve", id=i)
        return _Obj(id=i, config={"type": "cloud", "networking": {"type": "limited", "allowed_hosts": ["api.github.com", "api.higgsfield.ai", "cdn.base.test"],
                                                                   "allow_package_managers": True, "allow_mcp_servers": False},
                                  "packages": {"pip": ["httpx", "playwright", "pillow"], "npm": []}})
    def create(self, **kw): _log("env.create", **kw); return _Obj(id=f"env_{next(_n)}")
    def update(self, i, **kw): _log("env.update", id=i, **kw)
class _Beta:
    vaults, agents, environments = _Vaults(), _Agents(), _Envs()
class Anthropic:
    def __init__(self, *a, **k): self.beta = _Beta()
''')

# Canva OAuth falso: metadatos, registro, autorización (responde la redirección con code y state) y token.
EST = {"registros": [], "autoriza": [], "tokens": [], "modo": {}}


class C(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, o, code=200):
        b = json.dumps(o).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        base = f"http://127.0.0.1:{self.server.server_port}"
        p = urllib.parse.urlsplit(self.path)
        if p.path == "/.well-known/oauth-protected-resource/mcp":
            return self.send({"resource": f"{base}/mcp", "authorization_servers": [base], "scopes_supported": CANVA["oauth"]["scopes"] + ["profile:read"]})
        if p.path == "/.well-known/oauth-authorization-server":
            d = {"issuer": base, "authorization_endpoint": f"{base}/authorize", "token_endpoint": f"{base}/token", "registration_endpoint": f"{base}/register",
                 "code_challenge_methods_supported": ["S256"], "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
                 "grant_types_supported": ["authorization_code", "refresh_token"]}
            if EST["modo"].get("token_raro"):
                d["token_endpoint"] = "https://evil.example/token"
            return self.send(d)
        self.send({"error": "no"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); cuerpo = self.rfile.read(n).decode()
        if self.path == "/register":
            EST["registros"].append(json.loads(cuerpo)); return self.send({"client_id": "cli_publico_1"})
        if self.path == "/token":
            q = dict(urllib.parse.parse_qsl(cuerpo)); EST["tokens"].append(q)
            r = {"access_token": ACCESO, "token_type": "Bearer", "expires_in": 3600, "scope": " ".join(CANVA["oauth"]["scopes"])}
            if not EST["modo"].get("sin_refresh"):
                r["refresh_token"] = RENOVAR
            return self.send(r)
        self.send({"error": "no"}, 404)


srv = ThreadingHTTPServer(("127.0.0.1", 0), C); threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_port}"
import socket as _s
_l = _s.socket(); _l.bind(("127.0.0.1", 0)); PUERTO = _l.getsockname()[1]; _l.close()  # puerto libre fijo para la vuelta
ENV = {**os.environ, "PYTHONPATH": str(tmp / "falso"), "LOG_FALSO": str(LOG), "ANTHROPIC_API_KEY": "sk-falsa", "CANVA_OAUTH_BASE": BASE,
       "CANVA_OAUTH_NAVEGADOR": "0", "CANVA_OAUTH_ESPERA_S": "20", "CANVA_OAUTH_PUERTO": str(PUERTO), "CREDS_FALSAS": str(tmp / "creds.json")}
res = []


def caso(n, c, o=""):
    res.append(bool(c)); print(("✓" if c else "✗"), n, "" if c else str(o)[-900:])


def corre(*args, consiente=True, altera_state=False, **env):
    """Corre canva_oauth.py; hace de navegador: abre la URL que imprime y sigue la vuelta a 127.0.0.1 con code y state."""
    LOG.write_text("")
    p = subprocess.Popen([sys.executable, "canva_oauth.py", *args], cwd=tmp / "infra", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env={**ENV, **env})
    salida = []
    for linea in p.stdout:
        salida.append(linea)
        m = re.search(r"(http://127\.0\.0\.1:\d+/authorize\?\S+)", linea)
        if m and consiente:
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(m.group(1)).query)); EST["autoriza"].append(q)
            state = "otro" if altera_state else q["state"]
            urllib.request.urlopen(f"{q['redirect_uri']}?code=codigo-1&state={state}", timeout=10).read()
    p.wait(30)
    return p.returncode, "".join(salida), [json.loads(x) for x in LOG.read_text().splitlines() if x]


(tmp / "infra" / "estado-creativo.json").write_text(json.dumps({"vault_id": "vlt_5cero5", "cred_github_id": "vcrd_gh"}))

# 1. Camino bueno.
rc, out, ll = corre("--cuenta", "5cero5 · Creativo")
cr = [x for x in ll if x["op"] == "cred.create"]
caso("oauth: crea UNA credencial mcp_oauth en el Vault Creativo de 5cero5 y la valida", rc == 0 and len(cr) == 1 and cr[0]["vault_id"] == "vlt_5cero5"
     and any(x["op"] == "cred.validate" for x in ll) and "valid" in out, out)
auth = cr[0]["auth"] if cr else {}
caso("oauth: la credencial trae URL del MCP, access token, refresh con token_endpoint, client_id público y auth none",
     auth.get("type") == "mcp_oauth" and auth.get("mcp_server_url") == CANVA["servidor"]["url"] and auth.get("access_token") == ACCESO
     and auth.get("refresh", {}).get("refresh_token") == RENOVAR and auth["refresh"].get("token_endpoint") == f"{BASE}/token"
     and auth["refresh"].get("client_id") == "cli_publico_1" and auth["refresh"].get("token_endpoint_auth") == {"type": "none"} and auth.get("expires_at"), auth)
caso("oauth: metadata de la credencial {cliente, rol: canva, cuenta}", cr and cr[0]["metadata"] == {"cliente": "5cero5", "rol": "canva", "canva_cuenta": "5cero5 · Creativo", "origen": "harness/infra/canva_oauth.py"}, cr)
reg = EST["registros"][-1] if EST["registros"] else {}
caso("oauth: registro dinámico de cliente público con redirección a 127.0.0.1 (puerto fijo) y los scopes de canva.json",
     reg.get("token_endpoint_auth_method") == "none" and reg.get("redirect_uris", [""])[0] == f"http://127.0.0.1:{PUERTO}/callback"
     and reg.get("scope") == " ".join(CANVA["oauth"]["scopes"]), reg)
az = EST["autoriza"][-1] if EST["autoriza"] else {}
caso("oauth: autoriza con PKCE S256, state, resource del MCP y sin profile:read", az.get("code_challenge_method") == "S256" and len(az.get("code_challenge", "")) >= 43
     and len(az.get("state", "")) >= 32 and az.get("resource") == f"{BASE}/mcp" and "profile:read" not in az.get("scope", ""), az)
tk = EST["tokens"][-1] if EST["tokens"] else {}
caso("oauth: el cambio de código manda code_verifier, client_id y resource", tk.get("code_verifier") and tk.get("client_id") == "cli_publico_1" and tk.get("resource") == f"{BASE}/mcp", tk)
estado = json.loads((tmp / "infra" / "estado-creativo.json").read_text())
caso("oauth: nada secreto en la salida ni en estado-creativo.json (solo ids)", ACCESO not in out and RENOVAR not in out and "codigo-1" not in out
     and ACCESO not in json.dumps(estado) and RENOVAR not in json.dumps(estado) and estado.get("cred_canva_id") == (cr[0]["id"] if cr else None), (out, estado))

# 2. Ya hay credencial: no se repite el consentimiento.
CRED_ID = json.loads((tmp / "infra" / "estado-creativo.json").read_text()).get("cred_canva_id", "vcrd_x")
(tmp / "creds.json").write_text(json.dumps([{"id": CRED_ID, "auth": {"type": "mcp_oauth", "mcp_server_url": CANVA["servidor"]["url"] + "/"}, "metadata": {"cliente": "5cero5", "rol": "canva"}}]))
n_reg = len(EST["registros"])
rc, out, ll = corre("--cuenta", "5cero5 · Creativo")
caso("oauth: con credencial guardada solo valida; no registra ni pide consentimiento", rc == 0 and len(EST["registros"]) == n_reg
     and [x["op"] for x in ll] == ["cred.validate"] and "no se pide otro consentimiento" in out, out)
rc, out, ll = corre("--solo-validar", VALIDA_FALSA="unknown")
caso("oauth: --solo-validar con estado unknown sale con error y explica que es transitorio, sin nuevo consentimiento", rc != 0 and "transitorio" in out
     and [x["op"] for x in ll] == ["cred.validate"], out)
n_reg = len(EST["registros"])
rc, out, ll = corre("--cuenta", "5cero5 · Creativo", "--renovar")
upd = [x for x in ll if x["op"] == "cred.update"]
caso("oauth: --renovar con el mismo cliente OAuth reutiliza el registro y actualiza la credencial en su lugar (no la archiva)",
     rc == 0 and len(EST["registros"]) == n_reg and [x["op"] for x in ll][:1] == ["cred.update"] and not any(x["op"] == "cred.archive" for x in ll)
     and upd and upd[0]["auth"]["refresh"] == {"refresh_token": RENOVAR} and upd[0]["id"] == CRED_ID and ACCESO not in out, out)
(tmp / "creds.json").write_text(json.dumps([{"id": "vcrd_ajena", "auth": {"type": "mcp_oauth", "mcp_server_url": CANVA["servidor"]["url"]}, "metadata": {"cliente": "5cero5", "rol": "canva"}}]))
rc, out, ll = corre("--cuenta", "5cero5 · Creativo", "--renovar")
caso("oauth: --renovar sobre una credencial de otro cliente OAuth la archiva y crea otra enseguida, avisando", rc == 0 and [x["op"] for x in ll][:2] == ["cred.archive", "cred.create"] and "corre esto otra vez" in out, out)
(tmp / "creds.json").unlink()

# 3. Fallas cerradas: nada en el vault.
rc, out, ll = corre("--cuenta", "cuenta-x", VAULT_META='{"cliente": "opticas", "rol": "creativo"}')
caso("oauth: vault de otro cliente → no registra ni escribe", rc != 0 and "no es el Vault Creativo de 5cero5" in out and not ll, out)
EST["modo"] = {"token_raro": True}; n_reg = len(EST["registros"])
rc, out, ll = corre("--cuenta", "5cero5 · Creativo")
caso("oauth: metadatos que no coinciden con canva.json → no pide consentimiento", rc != 0 and "no coinciden" in out and len(EST["registros"]) == n_reg and not ll, out)
EST["modo"] = {}
rc, out, ll = corre("--cuenta", "5cero5 · Creativo", altera_state=True)
caso("oauth: state alterado → no cambia el código ni escribe", rc != 0 and "state_o_codigo_invalido" in out and not any(x["op"].startswith("cred.") for x in ll), out)
EST["modo"] = {"sin_refresh": True}
rc, out, ll = corre("--cuenta", "5cero5 · Creativo")
caso("oauth: sin refresh_token no escribe (caducaría sin renovarse)", rc != 0 and "refresh_token" in out and not any(x["op"].startswith("cred.") for x in ll), out)
EST["modo"] = {}
rc, out, ll = corre("--cuenta", "cuenta-x", CANVA_OAUTH_BASE="https://evil.example")
caso("oauth: CANVA_OAUTH_BASE fuera de 127.0.0.1 se rechaza", rc != 0 and "solo acepta" in out, out)

# 4. crear_agente_creativo.py --canva: MCP con lista cerrada y entorno propio del Creativo; --piloto no toca el agente común.
def alta(*args):
    LOG.write_text("")
    r = subprocess.run([sys.executable, "crear_agente_creativo.py", *args], cwd=tmp / "infra", capture_output=True, text=True, env=ENV)
    return r.returncode, r.stdout + r.stderr, [json.loads(x) for x in LOG.read_text().splitlines() if x]


rc, out, ll = alta("--canva")
agentes = [x for x in ll if x["op"] == "agent.create"]
ag = [x for x in agentes if x["name"] == "5cero5 · Creativo · Canva"]
comun = [x for x in agentes if x["name"] == "5cero5 · Creativo"]
envs = [x for x in ll if x["op"] == "env.create"]
ts = [t for t in (ag[0]["tools"] if ag else []) if t.get("type") == "mcp_toolset"]
cfgs = {c["name"]: c["permission_policy"]["type"] for c in (ts[0]["configs"] if ts else [])}
caso("alta --canva: agente de Canva APARTE con el servidor de Canva y su toolset; el común sin MCP", rc == 0 and len(ag) == 1
     and ag[0]["mcp_servers"] == [CANVA["servidor"]] and len(ts) == 1 and len(comun) == 1 and comun[0]["mcp_servers"] == []
     and not any(t.get("type") == "mcp_toolset" for t in comun[0]["tools"]), out)
caso("alta --canva: lista cerrada (default apagado), lectura always_allow, escritura always_ask",
     ts and ts[0]["default_config"]["enabled"] is False and all(cfgs[n] == "always_allow" for n in CANVA["herramientas"]["lectura"])
     and all(cfgs[n] == "always_ask" for n in CANVA["herramientas"]["con_permiso"]) and len(cfgs) == len(CANVA["herramientas"]["lectura"]) + len(CANVA["herramientas"]["con_permiso"]), cfgs)
red_ = envs[-1]["config"]["networking"] if envs else {}
caso("alta --canva: entorno de Canva con SOLO los hosts de canva.json (sin mcp.canva.com), allow_mcp_servers y gestores de paquetes",
     envs and envs[-1]["name"] == "5cero5-harness-canva" and red_["allowed_hosts"] == CANVA["hosts_red"] and red_["allow_mcp_servers"] is True
     and "mcp.canva.com" not in red_["allowed_hosts"] and red_["allow_package_managers"] is True, envs)
caso("alta --canva: el entorno común no recibe hosts de Canva",
     not any(x["op"] in ("env.update", "env.create") and x.get("name") != "5cero5-harness-canva" and "mcp.canva.com" in json.dumps(x) for x in ll), ll)
caso("alta --canva: imprime MA_AGENT_CREATIVO_CANVA y MA_ENVIRONMENT_CANVA", f"MA_AGENT_CREATIVO_CANVA={ag[0]['id'] if ag else '?'}" in out and "MA_ENVIRONMENT_CANVA=" in out, out)
caso("alta --canva: el agente de Canva guarda su estado aparte", (tmp / "infra" / "estado-creativo-canva.json").exists()
     and json.loads((tmp / "infra" / "estado-creativo.json").read_text())["agent_id"] != json.loads((tmp / "infra" / "estado-creativo-canva.json").read_text())["agent_id"], out)
rc, out, ll = alta("--actualizar-agente")
caso("alta sin --canva: solo el agente común, sin MCP; el de Canva no se toca", rc == 0 and [x["op"] for x in ll if x["op"].startswith("agent.")] == ["agent.update"]
     and [x for x in ll if x["op"] == "agent.update"][0]["mcp_servers"] == [], out)
for f in ("estado-entorno-canva.json", "estado-creativo-canva.json"):
    (tmp / "infra" / f).unlink(missing_ok=True)
rc, out, ll = alta("--solo-canva", "env_comun1")
ops = [x["op"] for x in ll]
envc = [x for x in ll if x["op"] == "env.create"]
agc = [x for x in ll if x["op"] == "agent.create"]
caso("alta --solo-canva: lee el entorno común y solo crea el entorno y el agente de Canva (nada común, ningún vault)",
     rc == 0 and ops.count("env.retrieve") == 1 and not any(o in ("env.update", "vault.create", "agent.update") or o.startswith("cred.") for o in ops)
     and len(envc) == 1 and len(agc) == 1 and agc[0]["name"] == "5cero5 · Creativo · Canva" and agc[0]["mcp_servers"] == [CANVA["servidor"]], out)
red_c = envc[0]["config"]["networking"] if envc else {}
caso("alta --solo-canva: red mínima de canva.json (no la común), allow_mcp_servers encendido y los paquetes del común",
     red_c.get("allowed_hosts") == CANVA["hosts_red"] and red_c.get("allow_mcp_servers") is True
     and red_c.get("allow_package_managers") is True and envc[0]["config"]["packages"] == {"pip": ["httpx", "playwright", "pillow"]}
     and "MA_AGENT_CREATIVO_CANVA=" in out and "MA_ENVIRONMENT_CANVA=" in out, envc)
rc, out, ll = alta("--solo-canva", "no-es-env")
caso("alta --solo-canva con un id que no es de entorno se rechaza sin tocar nada", rc != 0 and not ll, out)
rc, out, ll = alta("--canva", "--cliente", "opticas")
caso("alta --canva con otro cliente se rechaza (la credencial de cada cliente la pone canva_oauth.py)", rc != 0 and "canva_oauth.py" in out and not ll, out)

LOG.write_text("")
r = subprocess.run([sys.executable, "crear_agente_creativo.py", "--imprimir-canva"], cwd=tmp / "infra", capture_output=True, text=True,
                   env={k: v for k, v in ENV.items() if k != "ANTHROPIC_API_KEY"})
try:
    impreso = json.loads(r.stdout)
except json.JSONDecodeError:
    impreso = {}
ia, ie = impreso.get("agente", {}), impreso.get("entorno", {})
its = [t for t in ia.get("tools", []) if t.get("type") == "mcp_toolset"]
caso("--imprimir-canva: sin llave ni API, el mismo agente (servidor, lista cerrada, prompt) y la misma red que crea --canva",
     r.returncode == 0 and not LOG.read_text() and ia.get("mcp_servers") == [CANVA["servidor"]] and len(its) == 1 and ts and its[0] == ts[0]
     and ia.get("system") == (tmp / "agentes" / "creativo.md").read_text(encoding="utf-8") and ie.get("config", {}).get("networking") == red_, r.stdout[-300:] + r.stderr)

srv.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{sum(res)}/{len(res)} casos")
sys.exit(0 if all(res) else 1)
