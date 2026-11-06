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
        self.cuentas_token = [CTA]  # cuentas que ve el token (usuario del sistema del cliente)
        self.wa_pagina = "5218112345678"  # número ligado a la página: la API no lo expone, solo lo usa Meta al validar


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
        if p == "/me/adaccounts": return self.send({"data": [{"id": x} for x in S.cuentas_token]})
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
        if "validate_only" in body.get("execution_options", ""):
            # Como Meta: valida sin crear. Un conjunto de WhatsApp solo pasa con un número ligado a esa página.
            po = json.loads(body.get("promoted_object") or "{}")
            if tipo == "adsets" and "whatsapp_phone_number" in po and (po.get("page_id") != PAG or po["whatsapp_phone_number"] != S.wa_pagina):
                return self.send({"error": {"message": "The WhatsApp number is not connected to the Page", "code": 100}}, 400)
            return self.send({"success": True})
        S.n += 1; i = str(S.n)
        if tipo == "adimages": return self.send({"images": {body["name"]: {"hash": f"h{i}"}}})
        o = {"id": i, "name": body.get("name"), "status": S.forzar_status or body.get("status"), "_tipo": {"campaigns": "campaign", "adsets": "adset", "ads": "ad", "adcreatives": "creative"}[tipo]}
        if tipo == "adsets":
            o["_campana"] = body["campaign_id"]; o["daily_budget"] = body["daily_budget"]
            o["destination_type"] = body.get("destination_type")
            if body.get("promoted_object"): o["promoted_object"] = json.loads(body["promoted_object"])
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


def corre(*args, token=TOKEN, extra=(), env_extra=None):
    env = {**os.environ, "META_API_BASE": BASE, "META_TOKEN": token, **(env_extra or {})}
    env.pop("PAUTA_WHATSAPP", None) if not env_extra or "PAUTA_WHATSAPP" not in env_extra else None
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

# destino permitido: el token del cliente ve una sola cuenta; otra --cuenta o un token que ve más de una no escribe nada
OTRA = "act_7654321"
limpia(); rc, out = corre("cuenta", extra=("--cuenta", OTRA, "--cuenta-exclusiva"))
caso("cuenta: --cuenta de otro cliente se rechaza antes de leerla", rc != 0 and "no es exclusivo" in out and not any(g[0] == f"/{OTRA}" for g in S.gets), out)
limpia(); corre("plan", "--archivo", str(plan())); S.cuentas_token = [CTA, OTRA]
rc, out = corre("crear", "--nombre", "2026-10_mty_agencia-vs-505", extra=("--cuenta-exclusiva",))
caso("crear: token que ve otra cuenta además de la suya no crea nada", rc != 0 and "no es exclusivo" in out and not S.posts, out)
limpia(); S.cuentas_token = [CTA, OTRA]; rc, out = corre("cuenta")
caso("cuenta: sin --cuenta-exclusiva se comporta como antes (no pide /me/adaccounts)", rc == 0 and not any(g[0] == "/me/adaccounts" for g in S.gets), out)

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

# destino WhatsApp (Click to WhatsApp): el número sale de la ficha (--whatsapp, lo pone el harness), nunca del brief
NUM_A, NUM_B = "5218112345678", "5215598765432"  # ficha del cliente A (ligado a su página) y ficha del cliente B
WA_ON = {"PAUTA_WHATSAPP": "1"}
NOM = "2026-10_mty_agencia-vs-505"


def plan_wa(**kw):
    base = dict(destino="WhatsApp", objetivo="whatsapp", saludo="Hola, gracias por escribir a 5cero5.",
                anuncios=[{"nombre": "a01_post4x5_agencia", "pieza": "post-agencia", "mensaje": "Hola, quiero mi diagnóstico (a01)"},
                          {"nombre": "a02_historia_agencia", "pieza": "historia-agencia", "mensaje": "a02: quiero más información"}])
    base.update(kw)
    f = plan(**base); d = json.loads(f.read_text()); d.pop("boton", None)
    if "boton" in kw: d["boton"] = kw["boton"]
    f.write_text(json.dumps(d, ensure_ascii=False)); return f


def wa(*args, numero=NUM_A, env=WA_ON):
    return corre(*args, extra=(("--whatsapp", numero) if numero else ()), env_extra=env)


escrituras = lambda: [x for x, _ in S.posts]  # noqa: E731

limpia(); rc, out = wa("plan", "--archivo", str(plan_wa()))
caso("whatsapp: plan válido con el número de la ficha ligado a la página", rc == 0, out)
plan_ok = json.loads((TRABAJO / NOM / "plan.json").read_text())
caso("whatsapp: el plan guarda el número de la ficha, sin URL y con el botón de WhatsApp",
     plan_ok["whatsapp"] == NUM_A and plan_ok["destino"] == "WhatsApp" and plan_ok["boton"] == "WHATSAPP_MESSAGE" and plan_ok["objetivo"] == "whatsapp", str(plan_ok))
caso("whatsapp: plan no llama a Meta", not S.gets and not S.posts, str(S.gets))
rc, out = wa("crear", "--nombre", NOM)
caso("whatsapp: crear termina", rc == 0 and "todo en pausa" in out and "Meta validó el conjunto" in out, out)
rutas = escrituras()
caso("whatsapp: valida el conjunto en Meta y luego crea, solo en la cuenta y en el orden esperado",
     rutas == [f"/{CTA}/campaigns", f"/{CTA}/adsets", f"/{CTA}/adsets"] + [f"/{CTA}/{t}" for t in ("adimages", "adcreatives", "ads")] * 2, str(rutas))
val, conj = S.posts[1][1], S.posts[2][1]
caso("whatsapp: la validación es validate_only con el mismo conjunto, y la creación no lo lleva",
     json.loads(val["execution_options"]) == ["validate_only"] and "execution_options" not in conj
     and {k: v for k, v in val.items() if k != "execution_options"} == conj, str(val))
con_status = [b for x, b in S.posts if x.rsplit("/", 1)[-1] in ("campaigns", "adsets", "ads")]
caso("whatsapp: campaña, validación, conjunto y anuncios en PAUSED", len(con_status) == 5 and all(b["status"] == "PAUSED" for b in con_status), str(con_status))
camp, cre = S.posts[0][1], S.posts[4][1]
caso("whatsapp: campaña de clientes potenciales", camp["objective"] == "OUTCOME_LEADS", str(camp))
caso("whatsapp: conjunto a WhatsApp, optimiza a conversaciones, con página y número de la ficha",
     conj["destination_type"] == "WHATSAPP" and conj["optimization_goal"] == "CONVERSATIONS"
     and json.loads(conj["promoted_object"]) == {"page_id": PAG, "whatsapp_phone_number": NUM_A}, str(conj))
t = json.loads(conj["targeting"])
caso("whatsapp: sigue el público en México, el tope y el inicio futuro",
     "custom_locations" in t["geo_locations"] and conj["daily_budget"] == "50000" and conj["start_time"].startswith("2099-01-05"), str(conj))
spec = json.loads(cre["object_story_spec"]); ld = spec["link_data"]; pwm = json.loads(ld["page_welcome_message"])
caso("whatsapp: creativo con botón WHATSAPP_MESSAGE, sin url_tags y sin URL del brief",
     ld["call_to_action"] == {"type": "WHATSAPP_MESSAGE", "value": {"app_destination": "WHATSAPP"}} and ld["link"] == "https://api.whatsapp.com/send"
     and "url_tags" not in cre and spec["page_id"] == PAG, str(cre))
caso("whatsapp: mensaje prellenado con el código del anuncio",
     pwm["text_format"]["customer_action_type"] == "autofill_message" and "a01" in pwm["text_format"]["message"]["autofill_message"]["content"]
     and pwm["landing_screen_type"] == "welcome_message", str(pwm))
rc, out = wa("comprobar", "--nombre", NOM)
caso("whatsapp: comprobar lee el número en el conjunto y todo en pausa", rc == 0 and '"estado": "PAUSED"' in out, out)

rechazos = [
    ("número del brief distinto al de la ficha", dict(plan=lambda: plan_wa(whatsapp=NUM_B)), "no es idéntico"),
    ("cliente A con el número del cliente B en el brief (no cruce)", dict(plan=lambda: plan_wa(whatsapp=NUM_B), numero=NUM_A), "un brief no puede cambiar"),
    ("ficha sin WhatsApp pauta", dict(plan=lambda: plan_wa(), numero=""), "WhatsApp pauta"),
    ("PAUTA_WHATSAPP apagado", dict(plan=lambda: plan_wa(), env={}), "PAUTA_WHATSAPP"),
    ("mensaje sin su código a##", dict(plan=lambda: plan_wa(anuncios=[{"nombre": "a01_post4x5_agencia", "pieza": "post-agencia", "mensaje": "Hola, quiero info"}])), "código a01"),
    ("mensaje con el código de otro anuncio", dict(plan=lambda: plan_wa(anuncios=[{"nombre": "a01_post4x5_agencia", "pieza": "post-agencia", "mensaje": "Hola a02"}])), "código a01"),
    ("anuncio sin mensaje prellenado", dict(plan=lambda: plan_wa(anuncios=[{"nombre": "a01_post4x5_agencia", "pieza": "post-agencia"}])), "mensaje prellenado"),
    ("anuncio con URL de destino", dict(plan=lambda: plan_wa(anuncios=[{"nombre": "a01_post4x5_agencia", "pieza": "post-agencia", "mensaje": "a01",
                                                                "destino": "https://marketing.5cero5.com/x/"}])), "URL"),
    ("mensaje con una URL", dict(plan=lambda: plan_wa(anuncios=[{"nombre": "a01_post4x5_agencia", "pieza": "post-agencia", "mensaje": "a01 https://otro.com"}])), "URL"),
    ("plan con link suelto", dict(plan=lambda: plan_wa(link="https://marketing.5cero5.com/x/")), "URL"),
    ("texto con una URL", dict(plan=lambda: plan_wa(texto="Escríbenos o entra a www.otro.com")), "URL"),
    ("botón distinto de WhatsApp", dict(plan=lambda: plan_wa(boton="LEARN_MORE")), "WHATSAPP_MESSAGE"),
    ("objetivo de tráfico con destino WhatsApp", dict(plan=lambda: plan_wa(objetivo="trafico")), "objetivo"),
    ("objetivo whatsapp con destino URL", dict(plan=lambda: plan(objetivo="whatsapp")), "solo con destino WhatsApp"),
    ("mensaje prellenado con destino URL", dict(plan=lambda: plan(anuncios=[{"nombre": "a01_post4x5_agencia", "pieza": "post-agencia", "mensaje": "a01"}])), "no es WhatsApp"),
]
for nombre, k, espera in rechazos:
    limpia(); rc, out = wa("plan", "--archivo", str(k["plan"]()), numero=k.get("numero", NUM_A), env=k.get("env", WA_ON))
    caso(f"whatsapp: plan rechaza {nombre}", rc != 0 and espera in out and not S.posts, out)
limpia(); rc, out = wa("plan", "--archivo", str(plan_wa()), env={})
caso("whatsapp: apagado no llama a Meta", rc != 0 and not S.gets and not S.posts, str(S.gets))


def sin_conjunto_ni_anuncios():
    creados = [x for x, b in S.posts if "execution_options" not in b]
    return creados == [f"/{CTA}/campaigns"]


for nombre, numero, ligado in [("página sin el número ligado", NUM_A, ""), ("ficha de B sobre la página de A (ligada a otro número)", NUM_B, NUM_A)]:
    limpia(); S.wa_pagina = ligado; wa("plan", "--archivo", str(plan_wa(whatsapp=numero)), numero=numero)
    rc, out = wa("crear", "--nombre", NOM, numero=numero)
    caso(f"whatsapp: Meta rechaza al validar {nombre}: no crea conjunto ni anuncios, solo queda la campaña vacía en pausa",
         rc != 0 and f"Meta no acepta el WhatsApp {numero}" in out and sin_conjunto_ni_anuncios()
         and S.posts[0][1]["status"] == "PAUSED", out)
limpia(); S.wa_pagina = ""; wa("plan", "--archivo", str(plan_wa())); wa("crear", "--nombre", NOM)
cid = json.loads((TRABAJO / NOM / "resultado.json").read_text())["campana_meta_id"]
S.campanas_existentes = [{"id": cid, "name": NOM, "status": "PAUSED", "objective": "OUTCOME_LEADS"}]
(TRABAJO / NOM / "resultado.json").unlink(); S.wa_pagina = NUM_A; S.posts.clear()
rc, out = wa("crear", "--nombre", NOM)
caso("whatsapp: ya ligado el número, crear retoma la campaña vacía y termina", rc == 0 and "retomada" in out and f"/{CTA}/campaigns" not in escrituras(), out)
limpia(); wa("plan", "--archivo", str(plan_wa()))
S.objs["77"] = {"id": "77", "name": NOM, "status": "PAUSED", "_tipo": "campaign"}
S.objs["78"] = {"id": "78", "name": "mty_duenos-pyme", "status": "PAUSED", "_tipo": "adset", "_campana": "77", "daily_budget": "50000",
                "destination_type": "WHATSAPP", "promoted_object": {"page_id": PAG, "whatsapp_phone_number": NUM_B}}
S.campanas_existentes = [{"id": "77", "name": NOM, "status": "PAUSED", "objective": "OUTCOME_LEADS"}]
rc, out = wa("crear", "--nombre", NOM)
caso("whatsapp: no retoma un conjunto a medias con otro número", rc != 0 and "Ya existe" in out and not S.posts, out)

# Lo mismo, pero cuando el plan ya estaba validado: crear vuelve a revisar antes de escribir.
for nombre, prepara, k, espera in [
    ("PAUTA_WHATSAPP apagado", None, dict(env={}), "PAUTA_WHATSAPP"),
    ("ficha sin número", None, dict(numero=""), "WhatsApp pauta"),
    ("ficha con otro número (B)", None, dict(numero=NUM_B), "no es idéntico"),
]:
    limpia(); wa("plan", "--archivo", str(plan_wa()))
    if prepara: prepara()
    rc, out = wa("crear", "--nombre", NOM, numero=k.get("numero", NUM_A), env=k.get("env", WA_ON))
    caso(f"whatsapp: crear rechaza {nombre} sin escribir", rc != 0 and espera in out and not S.posts, out)

limpia(); rc, out = corre("plan", "--archivo", str(plan()), extra=("--whatsapp", NUM_A), env_extra=WA_ON)
caso("whatsapp: con destino URL y el interruptor prendido todo sigue como hoy", rc == 0 and not S.gets, out)
limpia(); rc, out = corre("cuenta", extra=("--whatsapp", "+52 81 1234"))
caso("whatsapp: --whatsapp que no es solo dígitos se rechaza", rc != 0 and "solo dígitos" in out, out)

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
caso("meta_post: execution_options no puede venir de afuera", sale(lambda: mp.meta_post(CTA, f"/{CTA}/adsets", {"status": "PAUSED", "execution_options": ["x"]})) and not S.posts)
caso("meta_post: no toca otras rutas de la cuenta", sale(lambda: mp.meta_post(CTA, f"/{CTA}/customaudiences", {"name": "x"})) and not S.posts)

shutil.rmtree(TMP, ignore_errors=True)
srv.shutdown()
print(f"\n{n - len(fallas)}/{n} casos")
if fallas:
    print("\n".join(fallas)); sys.exit(1)
