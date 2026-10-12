#!/usr/bin/env python3
"""Prueba de meta_pauta.py contra una Graph API FALSA (servidor local) y un repo de piezas falso.

  python3 test_meta_pauta.py

No necesita red ni dependencias."""
import hashlib, importlib.util, json, os, shutil, subprocess, sys, tempfile, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
HERR = HERE / "meta_pauta.py"
CTA, PAG, TOKEN = "act_1234567", "1127307763190247", "EAAprueba"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + (1080).to_bytes(4, "big") + (1350).to_bytes(4, "big") + b"resto"


class M:
    def reset(self, **kw):
        self.cuenta = {"name": "5cero5", "currency": "MXN", "timezone_name": "America/Mexico_City", "account_status": 1,
                       "spend_cap": "4500000", "amount_spent": "0", **kw}
        self.posts, self.gets, self.auth = [], [], set()
        self.objs, self.n, self.campanas_existentes = {}, 100, []
        self.forzar_status = None


S = M()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def ok(self):
        S.auth.add(self.headers.get("Authorization"))
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.send({"error": {"message": "Invalid OAuth access token", "code": 190}}, 401); return False
        if "access_token" in self.path:
            self.send({"error": {"message": "token en la URL", "code": 1}}, 400); return False
        return True

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path); q = dict(urllib.parse.parse_qsl(u.query)); S.gets.append((u.path, q))
        if not self.ok(): return
        p = u.path
        if p == f"/{CTA}": return self.send(S.cuenta)
        if p == f"/{PAG}": return self.send({"id": PAG, "name": "5cero5"})
        if p == f"/{CTA}/campaigns": return self.send({"data": S.campanas_existentes})
        partes = p.strip("/").split("/")
        if len(partes) == 2 and partes[0] in S.objs and partes[1] in ("adsets", "ads"):
            tipo = {"adsets": "adset", "ads": "ad"}[partes[1]]
            return self.send({"data": [o for o in S.objs.values() if o["_tipo"] == tipo and o.get("_campana") == partes[0]]})
        if len(partes) == 1 and partes[0] in S.objs:
            o = S.objs[partes[0]]; return self.send({k: v for k, v in o.items() if not k.startswith("_")} | {"account_id": CTA[4:]})
        self.send({"error": {"message": "no existe"}}, 404)

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        if not self.ok(): return
        body = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()))
        S.posts.append((u.path, body))
        tipo = u.path.rsplit("/", 1)[-1]
        S.n += 1; i = str(S.n)
        if tipo == "adimages": return self.send({"images": {body["name"]: {"hash": f"h{i}"}}})
        o = {"id": i, "name": body.get("name"), "status": S.forzar_status or body.get("status"), "_tipo": {"campaigns": "campaign", "adsets": "adset", "ads": "ad", "adcreatives": "creative"}[tipo]}
        if tipo == "adsets":
            o["_campana"] = body["campaign_id"]; o["daily_budget"] = body["daily_budget"]
        if tipo == "ads":
            o["_campana"] = next(x["_campana"] for x in S.objs.values() if x["id"] == body["adset_id"])
        S.objs[i] = o
        self.send({"id": i})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
TMP = Path(tempfile.mkdtemp())
PIEZAS, TRABAJO = TMP / "piezas", TMP / "trabajo"


def pieza(carpeta, nombre, aprobada=True, otro_png=False, formato="post-4x5"):
    d = PIEZAS / "piezas" / carpeta / nombre
    d.mkdir(parents=True, exist_ok=True)
    (d / "pieza.png").write_bytes(PNG + nombre.encode())
    sha = hashlib.sha1(PNG + nombre.encode() + (b"x" if otro_png else b"")).hexdigest()
    (d / "informe.json").write_text(json.dumps({"aprobada": aprobada, "png_sha1": sha, "formato": formato}))
    (d / "pieza.json").write_text(json.dumps({"campana": carpeta, "pieza": nombre, "formato": formato, "foto": False}))


def plan(**kw):
    p = {"nombre": "2026-10_mty_agencia-vs-505", "carpeta_piezas": "poc-diagnostico", "objetivo": "trafico",
         "presupuesto_diario_mxn": 500, "inicio": "2099-01-05", "fin": "2099-02-05",
         "publico": {"nombre": "mty_duenos-pyme", "ubicacion": {"tipo": "radio", "lat": 25.6866, "lng": -100.3161, "radio_km": 40}, "edad_min": 28, "edad_max": 60},
         "destino": "https://marketing.5cero5.com/diagnostico/", "texto": "Tu marketing completo en una sola mensualidad.",
         "titulo": "Diagnóstico sin costo", "boton": "LEARN_MORE",
         "anuncios": [{"nombre": "a01_post4x5_agencia", "pieza": "post-agencia"}, {"nombre": "a02_historia_agencia", "pieza": "historia-agencia"}]}
    p.update(kw)
    f = TMP / "plan-entrada.json"; f.write_text(json.dumps(p, ensure_ascii=False)); return f


def corre(*args, token=TOKEN, extra=()):
    env = {**os.environ, "META_API_BASE": BASE, "META_TOKEN": token}
    cmd = [sys.executable, str(HERR), "--trabajo", str(TRABAJO), "--piezas", str(PIEZAS), "--cuenta", CTA, "--pagina", PAG,
           "--tope-mxn", "1500", *extra, *args]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


fallas, n = [], 0


def caso(nombre, cond, detalle=""):
    global n
    n += 1
    print(("✓ " if cond else "✗ ") + nombre)
    if not cond: fallas.append(f"{nombre}: {detalle[-600:]}")


def limpia():
    shutil.rmtree(TRABAJO, ignore_errors=True); S.reset()


S.reset()
pieza("poc-diagnostico", "post-agencia"); pieza("poc-diagnostico", "historia-agencia", formato="historia-9x16")
pieza("poc-diagnostico", "sin-aprobar", aprobada=False); pieza("poc-diagnostico", "png-cambiado", otro_png=True)

# cuenta
rc, out = corre("cuenta"); caso("cuenta: activa en MXN pasa", rc == 0 and '"pagina_nombre": "5cero5"' in out, out)
caso("cuenta: el token va en el encabezado", S.auth == {f"Bearer {TOKEN}"}, str(S.auth))
S.reset(currency="USD"); rc, out = corre("cuenta"); caso("cuenta: en USD no pasa", rc != 0 and "MXN" in out, out)
S.reset(account_status=2); rc, out = corre("cuenta"); caso("cuenta: desactivada no pasa", rc != 0, out)
S.reset(spend_cap="0"); rc, out = corre("cuenta"); caso("cuenta: sin límite de gasto avisa", rc == 0 and "límite de gasto" in out, out)
S.reset(); rc, out = corre("cuenta", token="malo"); caso("cuenta: token malo falla con el error de Meta", rc != 0 and "Invalid OAuth" in out, out)

# plan
limpia(); rc, out = corre("plan", "--archivo", str(plan())); caso("plan: válido", rc == 0 and (TRABAJO / "2026-10_mty_agencia-vs-505" / "plan.json").exists(), out)
malos = [
    ("presupuesto arriba del tope", dict(presupuesto_diario_mxn=2000), "tope"),
    ("presupuesto no numérico", dict(presupuesto_diario_mxn="mucho"), "número"),
    ("destino de otro dominio", dict(destino="https://mkt.5cero5.com/x/"), "https"),
    ("destino con parámetros", dict(destino="https://marketing.5cero5.com/diagnostico/?utm_source=x"), "UTM"),
    ("destino http", dict(destino="http://marketing.5cero5.com/diagnostico/"), "https"),
    ("nombre fuera de convención", dict(nombre="Campaña Octubre"), "AAAA-MM"),
    ("leads sin pixel", dict(objetivo="clientes_potenciales"), "Pixel"),
    ("objetivo desconocido", dict(objetivo="alcance"), "objetivo"),
    ("inicio en el pasado", dict(inicio="2020-01-01"), "pasó"),
    ("fin antes de inicio", dict(fin="2099-01-01"), "después"),
    ("fuera de México", dict(publico={"nombre": "nyc_todos", "ubicacion": {"tipo": "radio", "lat": 40.7, "lng": -74, "radio_km": 10}}), "México"),
    ("país distinto", dict(publico={"nombre": "mx_todos", "ubicacion": {"tipo": "pais", "pais": "US"}}), "México"),
    ("edad menor de 18", dict(publico={"nombre": "mx_todos", "ubicacion": {"tipo": "pais", "pais": "MX"}, "edad_min": 16}), "edades"),
    ("signos de exclamación", dict(texto="¡Ya llegó!"), "exclamación"),
    ("titular largo", dict(titulo="x" * 61), "máximo"),
    ("pieza sin aprobar", dict(anuncios=[{"nombre": "a01_post4x5_xx", "pieza": "sin-aprobar"}]), "no está aprobado"),
    ("pieza con otro PNG", dict(anuncios=[{"nombre": "a01_post4x5_xx", "pieza": "png-cambiado"}]), "otro PNG"),
    ("pieza que no existe", dict(anuncios=[{"nombre": "a01_post4x5_xx", "pieza": "no-existe"}]), "fusionó"),
    ("anuncio repetido", dict(anuncios=[{"nombre": "a01_post4x5_xx", "pieza": "post-agencia"}] * 2), "repetido"),
    ("sin anuncios", dict(anuncios=[]), "anuncios"),
    ("botón raro", dict(boton="SHOP_NOW"), "boton"),
]
for nombre, cambio, espera in malos:
    limpia(); rc, out = corre("plan", "--archivo", str(plan(**cambio)))
    caso(f"plan: rechaza {nombre}", rc != 0 and espera in out, out)
limpia(); rc, out = corre("plan", "--archivo", str(plan(objetivo="clientes_potenciales")), extra=("--pixel", "998877"))
caso("plan: leads con pixel pasa", rc == 0, out)
caso("plan: no llama a Meta", not S.posts and not S.gets, str(S.gets))

# crear
limpia(); corre("plan", "--archivo", str(plan()))
rc, out = corre("crear", "--nombre", "2026-10_mty_agencia-vs-505")
caso("crear: termina", rc == 0 and "todo en pausa" in out, out)
rutas = [p for p, _ in S.posts]
caso("crear: solo escribe en la cuenta y en el orden esperado",
     rutas == [f"/{CTA}/campaigns", f"/{CTA}/adsets"] + [f"/{CTA}/{t}" for t in ("adimages", "adcreatives", "ads")] * 2, str(rutas))
con_status = [b for p, b in S.posts if p.rsplit("/", 1)[-1] in ("campaigns", "adsets", "ads")]
caso("crear: campaña, conjunto y anuncios con status PAUSED", len(con_status) == 4 and all(b["status"] == "PAUSED" for b in con_status), str(con_status))
camp = S.posts[0][1]; conj = S.posts[1][1]; cre = S.posts[3][1]
caso("crear: campaña de tráfico sin categoría especial", camp["objective"] == "OUTCOME_TRAFFIC" and json.loads(camp["special_ad_categories"]) == [], str(camp))
caso("crear: presupuesto en centavos de MXN", conj["daily_budget"] == "50000", str(conj))
t = json.loads(conj["targeting"])
caso("crear: público con radio dentro de geo_locations y edades", t["geo_locations"]["custom_locations"][0]["radius"] == 40 and t["age_min"] == 28 and t["age_max"] == 60, str(t))
caso("crear: fechas en hora de México", conj["start_time"].startswith("2099-01-05T00:00:00-06:00") and conj["end_time"].startswith("2099-02-05T23:59:00-06:00"), str(conj))
spec = json.loads(cre["object_story_spec"])
caso("crear: creativo con página, destino, imagen y UTMs por url_tags",
     spec["page_id"] == PAG and spec["link_data"]["link"] == "https://marketing.5cero5.com/diagnostico/" and spec["link_data"]["image_hash"].startswith("h")
     and "utm_source=meta" in cre["url_tags"] and "{{ad.name}}" in cre["url_tags"], str(cre))
res = json.loads((TRABAJO / "2026-10_mty_agencia-vs-505" / "resultado.json").read_text())
caso("crear: resultado.json con ids", res.get("completa") and len(res["anuncios"]) == 2 and res["campana_meta_id"], str(res))
antes = len(S.posts); rc, out = corre("crear", "--nombre", "2026-10_mty_agencia-vs-505")
caso("crear: no crea dos veces", rc != 0 and "No se crea otra vez" in out and len(S.posts) == antes, out)
rc, out = corre("comprobar", "--nombre", "2026-10_mty_agencia-vs-505")
caso("comprobar: todo en pausa", rc == 0 and '"estado": "PAUSED"' in out, out)
cid = res["campana_meta_id"]; S.objs[res["anuncios"][0]["id"]]["status"] = "ACTIVE"
rc, out = corre("comprobar", "--nombre", "2026-10_mty_agencia-vs-505")
caso("comprobar: detecta un anuncio activo", rc != 0 and "ACTIVE" in out, out)

limpia(); corre("plan", "--archivo", str(plan())); S.campanas_existentes = [{"id": "77", "name": "2026-10_mty_agencia-vs-505", "status": "ACTIVE", "objective": "OUTCOME_TRAFFIC"}]
rc, out = corre("crear", "--nombre", "2026-10_mty_agencia-vs-505")
caso("crear: no duplica un nombre que ya existe en Meta (no vacía o no en pausa)", rc != 0 and "Ya existe" in out and not S.posts, out)

limpia(); corre("plan", "--archivo", str(plan()))
S.objs["77"] = {"id": "77", "name": "2026-10_mty_agencia-vs-505", "status": "PAUSED", "_tipo": "campaign"}
S.campanas_existentes = [{"id": "77", "name": "2026-10_mty_agencia-vs-505", "status": "PAUSED", "objective": "OUTCOME_TRAFFIC"}]
rc, out = corre("crear", "--nombre", "2026-10_mty_agencia-vs-505")
rutas = [p for p, _ in S.posts]
caso("crear: retoma la campaña vacía y en pausa de un intento a medias, sin crear otra",
     rc == 0 and "retomada" in out and f"/{CTA}/campaigns" not in rutas and S.posts[0][1].get("campaign_id") == "77", out)
rc, out = corre("comprobar", "--nombre", "2026-10_mty_agencia-vs-505")
caso("comprobar: la campaña retomada queda completa y en pausa", rc == 0 and '"estado": "PAUSED"' in out, out)

limpia(); corre("plan", "--archivo", str(plan()))
S.objs["77"] = {"id": "77", "name": "x", "status": "PAUSED", "_tipo": "campaign"}
S.objs["78"] = {"id": "78", "name": "conj", "status": "PAUSED", "_tipo": "adset", "_campana": "77", "daily_budget": "1"}
S.campanas_existentes = [{"id": "77", "name": "2026-10_mty_agencia-vs-505", "status": "PAUSED", "objective": "OUTCOME_TRAFFIC"}]
rc, out = corre("crear", "--nombre", "2026-10_mty_agencia-vs-505")
caso("crear: no retoma un conjunto con otro nombre o presupuesto", rc != 0 and "Ya existe" in out and not S.posts, out)

limpia(); corre("plan", "--archivo", str(plan()))
S.objs["77"] = {"id": "77", "name": "2026-10_mty_agencia-vs-505", "status": "PAUSED", "_tipo": "campaign"}
S.objs["78"] = {"id": "78", "name": "mty_duenos-pyme", "status": "PAUSED", "_tipo": "adset", "_campana": "77", "daily_budget": "50000"}
S.campanas_existentes = [{"id": "77", "name": "2026-10_mty_agencia-vs-505", "status": "PAUSED", "objective": "OUTCOME_TRAFFIC"}]
rc, out = corre("crear", "--nombre", "2026-10_mty_agencia-vs-505")
rutas = [p for p, _ in S.posts]
caso("crear: retoma campaña y conjunto del intento a medias y solo agrega los anuncios",
     rc == 0 and f"/{CTA}/campaigns" not in rutas and f"/{CTA}/adsets" not in rutas and rutas.count(f"/{CTA}/ads") == 2
     and all(b.get("adset_id") == "78" for p_, b in S.posts if p_.endswith("/ads")), out)

limpia(); corre("plan", "--archivo", str(plan()))
S.objs["77"] = {"id": "77", "name": "2026-10_mty_agencia-vs-505", "status": "PAUSED", "_tipo": "campaign"}
S.objs["78"] = {"id": "78", "name": "mty_duenos-pyme", "status": "PAUSED", "_tipo": "adset", "_campana": "77", "daily_budget": "50000"}
S.objs["79"] = {"id": "79", "name": "a01", "status": "PAUSED", "_tipo": "ad", "_campana": "77"}
S.campanas_existentes = [{"id": "77", "name": "2026-10_mty_agencia-vs-505", "status": "PAUSED", "objective": "OUTCOME_TRAFFIC"}]
rc, out = corre("crear", "--nombre", "2026-10_mty_agencia-vs-505")
caso("crear: no retoma una campaña que ya tiene anuncios", rc != 0 and "Ya existe" in out and not S.posts, out)

limpia(); corre("plan", "--archivo", str(plan()))
pj = TRABAJO / "2026-10_mty_agencia-vs-505" / "plan.json"; d = json.loads(pj.read_text()); d["presupuesto_diario_mxn"] = 9000; pj.write_text(json.dumps(d))
rc, out = corre("crear", "--nombre", "2026-10_mty_agencia-vs-505")
caso("crear: plan editado a mano después de validar no se usa", rc != 0 and "cambió" in out and not S.posts, out)

limpia(); corre("plan", "--archivo", str(plan(objetivo="clientes_potenciales")), extra=("--pixel", "998877"))
corre("crear", "--nombre", "2026-10_mty_agencia-vs-505", extra=("--pixel", "998877"))
conj = S.posts[1][1] if len(S.posts) > 1 else {}
caso("crear: leads optimiza a LEAD del Pixel", S.posts and S.posts[0][1].get("objective") == "OUTCOME_LEADS"
     and json.loads(conj.get("promoted_object", "{}")) == {"pixel_id": "998877", "custom_event_type": "LEAD"}, str(conj))

# la única salida de escritura
spec_ = importlib.util.spec_from_file_location("mp", HERR); mp = importlib.util.module_from_spec(spec_); spec_.loader.exec_module(mp)
os.environ.update(META_API_BASE=BASE, META_TOKEN=TOKEN)


def sale(f):
    try: f(); return False
    except SystemExit: return True


S.reset()
caso("meta_post: no escribe con status ACTIVE", sale(lambda: mp.meta_post(CTA, f"/{CTA}/campaigns", {"name": "x", "status": "ACTIVE"})) and not S.posts)
caso("meta_post: no escribe sin status", sale(lambda: mp.meta_post(CTA, f"/{CTA}/ads", {"name": "x"})) and not S.posts)
caso("meta_post: no escribe en otra cuenta", sale(lambda: mp.meta_post(CTA, "/act_999/campaigns", {"status": "PAUSED"})) and not S.posts)
caso("meta_post: no edita objetos existentes", sale(lambda: mp.meta_post(CTA, "/12345", {"status": "PAUSED"})) and not S.posts)
caso("meta_post: no toca otras rutas de la cuenta", sale(lambda: mp.meta_post(CTA, f"/{CTA}/customaudiences", {"name": "x"})) and not S.posts)

shutil.rmtree(TMP, ignore_errors=True)
srv.shutdown()
print(f"\n{n - len(fallas)}/{n} casos")
if fallas:
    print("\n".join(fallas)); sys.exit(1)
