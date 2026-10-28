#!/usr/bin/env python3
"""Prueba de --cliente en los scripts de alta, con un SDK de Anthropic FALSO y una Graph API FALSA.

  python3 test_infra.py

Corre sobre una copia temporal de infra/ y agentes/ (no toca estado-*.json reales). No necesita red ni dependencias.
Comprueba: el vault de cada cliente lleva metadata {cliente, rol}; con otro cliente no se crea ni se actualiza el agente
común; el estado de otro cliente va aparte; los ids para la ficha se imprimen; un --cliente inválido no hace nada."""
import json, os, shutil, subprocess, sys, tempfile, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
tmp = Path(tempfile.mkdtemp())
shutil.copytree(HERE, tmp / "infra", ignore=shutil.ignore_patterns("estado-*.json", "__pycache__", "test_infra.py"))
shutil.copytree(HERE.parent / "agentes", tmp / "agentes")
LOG = tmp / "llamadas.jsonl"

# SDK falso: anthropic.Anthropic().beta.{environments,vaults,vaults.credentials,agents}. Registra cada llamada.
(tmp / "falso" / "anthropic").mkdir(parents=True)
(tmp / "falso" / "anthropic" / "__init__.py").write_text('''
import json, os, itertools
_n = (f"{os.getpid()}_{i}" for i in itertools.count(1))
def _log(op, **kw):
    with open(os.environ["LOG_FALSO"], "a") as f: f.write(json.dumps({"op": op, **kw}, default=str) + "\\n")
class _Obj:
    def __init__(self, **kw): self.__dict__.update(kw)
class _Creds:
    def create(self, vault_id, **kw): i = f"vcrd_{next(_n)}"; _log("cred.create", vault_id=vault_id, id=i, **kw); return _Obj(id=i)
    def update(self, cred_id, **kw): _log("cred.update", id=cred_id, **kw)
    def delete(self, cred_id, **kw): _log("cred.delete", id=cred_id, **kw)
class _Vaults:
    credentials = _Creds()
    def create(self, **kw): i = f"vlt_{next(_n)}"; _log("vault.create", id=i, **kw); return _Obj(id=i)
class _Agents:
    def create(self, **kw): i = f"agent_{next(_n)}"; _log("agent.create", id=i, name=kw.get("name")); return _Obj(id=i)
    def retrieve(self, i): return _Obj(id=i, version=1)
    def update(self, i, **kw): _log("agent.update", id=i); return _Obj(id=i, version=2)
class _Envs:
    def create(self, **kw): _log("env.create"); return _Obj(id="env_1")
    def update(self, i, **kw): _log("env.update", id=i)
class _Beta:
    vaults, agents, environments = _Vaults(), _Agents(), _Envs()
class Anthropic:
    def __init__(self, *a, **k): self.beta = _Beta()
''')

# Graph API falsa para crear_agente_pauta.py: el token de cada cliente ve una sola cuenta (o dos, para el caso malo).
CUENTAS = {"EAA_a": ["act_1111111"], "EAA_b": ["act_2222222"], "EAA_dos": ["act_1111111", "act_2222222"]}
PAGINAS = {"EAA_a": "2111111", "EAA_b": "3222222", "EAA_dos": "2111111"}


class G(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, o):
        b = json.dumps(o).encode(); self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        t = self.headers.get("Authorization", "").replace("Bearer ", ""); p = urllib.parse.urlsplit(self.path).path
        if p == "/me": return self.send({"id": "1", "name": "agente-pauta"})
        if p == "/me/permissions": return self.send({"data": [{"permission": "ads_management", "status": "granted"}, {"permission": "pages_manage_ads", "status": "granted"}]})
        if p == "/me/adaccounts": return self.send({"data": [{"id": c, "currency": "MXN", "account_status": 1, "spend_cap": "100"} for c in CUENTAS[t]]})
        if p == "/me/accounts": return self.send({"data": [{"id": PAGINAS[t], "name": "Página"}]})
        return self.send({"data": []})


srv = ThreadingHTTPServer(("127.0.0.1", 0), G); threading.Thread(target=srv.serve_forever, daemon=True).start()
ENV = {**os.environ, "PYTHONPATH": str(tmp / "falso"), "LOG_FALSO": str(LOG), "ANTHROPIC_API_KEY": "sk-falsa",
       "NOTION_TOKEN_AGENTES": "ntn_falso", "HL_TOKEN_CRM": "pit-falso", "META_API_BASE": f"http://127.0.0.1:{srv.server_port}"}
res = []


def caso(n, c, o=""):
    res.append(bool(c)); print(("✓" if c else "✗"), n, "" if c else str(o)[-800:])


def corre(script, *args, **env):
    LOG.write_text("")
    r = subprocess.run([sys.executable, script, *args], cwd=tmp / "infra", capture_output=True, text=True, env={**ENV, **env})
    return r.returncode, r.stdout + r.stderr, [json.loads(x) for x in LOG.read_text().splitlines() if x]


ROLES = {"cmo": "CMO", "crm": "CRM", "landing": "Landing", "creativo": "Creativo", "pauta": "Pauta"}
for rol, Rol in ROLES.items():
    script = f"crear_agente_{rol}.py"
    extra = ("--pagina", "2111111") if rol == "pauta" else ()
    # cliente base: vault con cliente=5cero5 y agente común creado
    rc, out, ll = corre(script, *extra, META_TOKEN="EAA_a")
    v = [x for x in ll if x["op"] == "vault.create"]
    caso(f"{rol}: sin --cliente, vault 5cero5 · {Rol} con metadata cliente=5cero5, rol={rol} y agente creado",
         rc == 0 and len(v) == 1 and v[0]["metadata"]["cliente"] == "5cero5" and v[0]["metadata"]["rol"] == rol
         and v[0]["display_name"] == f"5cero5 · {Rol}" and any(x["op"] == "agent.create" for x in ll), out)
    # cliente A: su vault, sin tocar el agente común; estado aparte
    rc, out, ll = corre(script, "--cliente", "cliente-a", *extra, META_TOKEN="EAA_a")
    v = [x for x in ll if x["op"] == "vault.create"]
    caso(f"{rol}: --cliente cliente-a crea su vault con metadata cliente=cliente-a, rol={rol}",
         rc == 0 and len(v) == 1 and v[0]["metadata"] == {"cliente": "cliente-a", "rol": rol, "origen": f"harness/infra/{script}"}
         and v[0]["display_name"] == f"cliente-a · {Rol}", out)
    caso(f"{rol}: --cliente cliente-a no crea ni actualiza el agente común",
         not any(x["op"].startswith("agent.") for x in ll), [x["op"] for x in ll])
    caso(f"{rol}: --cliente cliente-a guarda su estado aparte y no pisa el de 5cero5",
         (tmp / "infra" / f"estado-cliente-a-{rol}.json").exists() and (tmp / "infra" / f"estado-{rol}.json").exists()
         and json.loads((tmp / "infra" / f"estado-cliente-a-{rol}.json").read_text())["vault_id"] != json.loads((tmp / "infra" / f"estado-{rol}.json").read_text())["vault_id"])
    caso(f"{rol}: imprime el Vault {Rol} para la ficha de cliente-a", f"Para la ficha de cliente-a" in out and f"Vault {Rol}: {v[0]['id'] if v else '?'}" in out, out)
    # segunda corrida del mismo cliente: no duplica el vault
    rc, out, ll = corre(script, "--cliente", "cliente-a", *extra, META_TOKEN="EAA_a")
    caso(f"{rol}: correr otra vez con --cliente cliente-a no crea otro vault", rc == 0 and not any(x["op"] == "vault.create" for x in ll), out)

rc, out, ll = corre("crear_agente_landing.py", "--cliente", "cliente-a", "--actualizar-agente")
caso("--actualizar-agente con otro cliente se rechaza sin tocar nada", rc != 0 and "común" in out and not ll, out)
rc, out, ll = corre("crear_agente_landing.py", "--cliente", "Cliente_A")
caso("--cliente inválido se rechaza sin tocar nada", rc != 0 and "inválido" in out and not ll, out)
rc, out, ll = corre("crear_agente_landing.py", "--cliente", "cliente-b")
cred = [x for x in ll if x["op"] == "cred.create"]
caso("landing: la credencial de cliente-b va en el vault de cliente-b y la imprime para la ficha",
     rc == 0 and len(cred) == 1 and cred[0]["vault_id"] == [x for x in ll if x["op"] == "vault.create"][0]["id"]
     and f"Credencial GitHub Landing: {cred[0]['id']}" in out, out)
rc, out, ll = corre("crear_agente_pauta.py", "--cliente", "cliente-b", "--pagina", "3222222", META_TOKEN="EAA_b")
caso("pauta: cliente-b imprime su cuenta y página para la ficha", rc == 0 and "Meta cuenta: act_2222222" in out and "Meta página: 3222222" in out, out)
rc, out, ll = corre("crear_agente_pauta.py", "--cliente", "cliente-b", "--pagina", "2111111", "--cuenta", "act_1111111", META_TOKEN="EAA_dos")
caso("pauta: un token que ve dos cuentas se rechaza antes de tocar Managed Agents", rc != 0 and "ve 2 cuentas" in out and not ll, out)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{sum(res)}/{len(res)} casos")
sys.exit(0 if all(res) else 1)
