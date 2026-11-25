#!/usr/bin/env python3
"""Pruebas del núcleo Higgsfield (higgsfield.py) contra un GitHub FALSO con CAS real en la ref y un Higgsfield FALSO con
Idempotency-Key real (huella de endpoint + cuerpo + Hf-Expires-After). Cada corrida del núcleo es un PROCESO aparte (como
una sesión): así se prueban reinicios, respuestas perdidas y sesiones concurrentes. Sin llaves reales ni red externa.

  python3 test_higgsfield.py          (necesita Pillow)
"""
import base64, hashlib, io, json, os, subprocess, sys, tempfile, threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = "5cero5/5cero5-piezas"
RAMA = "refs/heads/agente/higgsfield"
LLAVE = "hfid_prueba:hfsecreto_prueba"
TOKEN = "ghs_prueba_registro"
blob_sha = lambda b: hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()
LOCK = threading.Lock()


# ------------------------------------------------------------------ GitHub falso (CAS en PATCH de la ref)
class GH:
    def reset(self):
        self.blobs, self.trees, self.commits, self.refs = {}, {}, {}, {}
        self.n, self.auth, self.conflictos = 0, [], 0
G = GH(); G.reset()


class Base(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def send(self, obj, code=200, tipo="application/json"):
        b = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", tipo); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def cuerpo(self):
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n) if n else b""


class HGit(Base):
    def ok(self):
        G.auth.append(self.headers.get("Authorization"))
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.send({"message": "Bad credentials"}, 401); return False
        return True

    def do_GET(self):
        if not self.ok(): return
        p = self.path.split("?")[0]; pre = f"/repos/{REPO}/git/"
        with LOCK:
            if p == pre + "ref/heads/agente/higgsfield":
                return self.send({"object": {"sha": G.refs[RAMA]}}) if RAMA in G.refs else self.send({"message": "Not Found"}, 404)
            if p.startswith(pre + "commits/"): return self.send({"tree": {"sha": G.commits[p.rsplit("/", 1)[1]]["tree"]}})
            if p.startswith(pre + "trees/"): return self.send({"tree": G.trees[p.rsplit("/", 1)[1]]})
            if p.startswith(pre + "blobs/"): return self.send({"content": base64.b64encode(G.blobs[p.rsplit("/", 1)[1]]).decode()})
        self.send({}, 404)

    def do_POST(self):
        if not self.ok(): return
        body = json.loads(self.cuerpo()); p = self.path; pre = f"/repos/{REPO}/git/"
        with LOCK:
            G.n += 1
            if p == pre + "blobs":
                b = base64.b64decode(body["content"]); s = blob_sha(b); G.blobs[s] = b; return self.send({"sha": s}, 201)
            if p == pre + "trees":
                base = {e["path"]: e for e in G.trees[body["base_tree"]]} if body.get("base_tree") else {}
                for e in body["tree"]: base[e["path"]] = e
                t = f"t{G.n}"; G.trees[t] = list(base.values()); return self.send({"sha": t}, 201)
            if p == pre + "commits":
                c = f"c{G.n}"; G.commits[c] = {"tree": body["tree"], "parents": body["parents"]}; return self.send({"sha": c}, 201)
            if p == pre + "refs":
                if body["ref"] in G.refs: G.conflictos += 1; return self.send({"message": "Reference already exists"}, 422)
                G.refs[body["ref"]] = body["sha"]; return self.send({"ref": body["ref"]}, 201)
        self.send({}, 404)

    def do_PATCH(self):
        if not self.ok(): return
        body = json.loads(self.cuerpo())
        with LOCK:
            if self.path != f"/repos/{REPO}/git/refs/heads/agente/higgsfield" or body.get("force") is not False:
                return self.send({}, 422)
            if G.commits[body["sha"]]["parents"] != [G.refs.get(RAMA)]:  # no es fast-forward
                G.conflictos += 1; return self.send({"message": "Update is not a fast forward"}, 422)
            G.refs[RAMA] = body["sha"]; return self.send({"object": {"sha": body["sha"]}})


# ------------------------------------------------------------------ Higgsfield falso (idempotencia real)
class HF:
    def reset(self, **kw):
        self.estimate = "0.094"; self.estimates = []; self.posts = []; self.claves = {}; self.reqs = {}
        self.caer_tras_aceptar = 0; self.caer_sin_aceptar = 0; self.e503 = 0; self.forzar_422 = False
        self.pendientes = 1; self.final = "completed"; self.delete_code = 200; self.deletes = []; self.gets = 0
        self.imagen = None; self.tipo_imagen = "image/jpeg"; self.img_500 = 0; self.img_auth = []; self.puts = []
        self.uploads = 0; self.auth_otro = []
        self.__dict__.update(kw)
H = HF(); H.reset()


class HHiggs(Base):
    def auth(self):
        if self.headers.get("Authorization") != f"Key {LLAVE}":
            self.send({"detail": "no auth"}, 401); return False
        return True

    def soltar(self):  # la conexión se corta sin respuesta: el cliente no sabe si se aceptó
        self.close_connection = True

    def do_POST(self):
        if not self.auth(): return
        raw = self.cuerpo(); body = json.loads(raw)
        with LOCK:
            if self.path.startswith("/estimate/"):
                H.estimates.append((self.path, body))
                if H.estimate is None: return self.send({"detail": "boom"}, 500)
                return self.send({"usd": H.estimate} if H.estimate != "raro" else {"precio": 1})
            if self.path == "/files/generate-upload-url":
                H.uploads += 1
                return self.send({"upload_url": f"{IMG}/subir/{H.uploads}", "public_url": f"https://cdn.prueba/in-{H.uploads}.jpg",
                                  "upload_headers": {"Content-Type": body["content_type"], "x-amz-tagging": "retention=temporary"}})
            H.posts.append((self.path, body, dict(self.headers)))
            if H.caer_sin_aceptar > 0:
                H.caer_sin_aceptar -= 1; return self.soltar()
            if H.e503 > 0:
                H.e503 -= 1; return self.send({"detail": "unavailable"}, 503)
            clave = self.headers.get("Idempotency-Key")
            huella = json.dumps([self.path, body, self.headers.get("Hf-Expires-After")], sort_keys=True)
            if H.forzar_422 or (clave in H.claves and H.claves[clave][0] != huella):
                return self.send({"detail": "Idempotency-Key was already used with different request parameters"}, 422)
            if clave in H.claves:
                rid = H.claves[clave][1]
            else:
                rid = f"req-{len(H.reqs) + 1}"; H.claves[clave] = (huella, rid); H.reqs[rid] = {"gets": 0, "clave": clave}
            if H.caer_tras_aceptar > 0:
                H.caer_tras_aceptar -= 1; return self.soltar()
        self.send({"status": "queued", "request_id": rid, "status_url": f"{API}/requests/{rid}/status", "expires_after": 3600})

    def do_GET(self):
        if not self.auth(): return
        rid = self.path.split("/")[2]
        with LOCK:
            H.gets += 1
            r = H.reqs.get(rid)
            if not r: return self.send({"detail": "not found"}, 404)
            r["gets"] += 1
            if r["gets"] <= H.pendientes: return self.send({"status": "in_progress", "request_id": rid})
        self.send({"status": H.final, "request_id": rid, "expires_at": "2026-11-26T00:00:00Z",
                   **({"images": [{"url": f"{IMG}/archivo/{rid}.jpg"}]} if H.final == "completed" else {"error": "boom"})})

    def do_DELETE(self):
        if not self.auth(): return
        with LOCK:
            H.deletes.append(self.path)
        if H.delete_code != 200: return self.send({"detail": "Deletion temporarily unavailable"}, H.delete_code)
        self.send({"request_id": self.path.rsplit("/", 1)[-1], "status": "deleted"})


class HImg(Base):
    def do_GET(self):
        with LOCK:
            H.img_auth.append(self.headers.get("Authorization"))
            if H.img_500 > 0:
                H.img_500 -= 1; return self.send(b"err", 500, "text/plain")
        self.send(H.imagen or IMAGEN, tipo=H.tipo_imagen)

    def do_PUT(self):
        n = len(self.cuerpo())
        with LOCK:
            H.puts.append((self.headers.get("Authorization"), n))
        self.send({})


def servidor(h):
    s = ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{s.server_address[1]}"


def imagen(w=1600, h=900, fmt="JPEG", semilla=1):
    from PIL import Image, ImageDraw
    import random
    random.seed(semilla)
    im = Image.new("RGB", (w, h), (50, 80, 110)); d = ImageDraw.Draw(im)
    for _ in range(400):
        x, y, r = random.randint(0, w), random.randint(0, h), random.randint(10, 80)
        d.ellipse([x, y, x + r, y + r], fill=(random.randint(30, 230), random.randint(30, 220), random.randint(30, 200)))
    b = io.BytesIO(); im.save(b, fmt, **({"quality": 90} if fmt == "JPEG" else {})); return b.getvalue()


API = IMG = GHAPI = None
IMAGEN = b""
TMP = Path(tempfile.mkdtemp())
MARCA = TMP / "marca"
POL = {"version": 1, "permitido": True, "tope_usd": "5.00", "max_usd_por_operacion": "0.25", "generar": True,
       "editar": True, "referencias_ia": True, "acepta_retencion_uploads_s": 604800}
FILA = "2b8f0c1e-0d6a-4c39-9b0e-6a1f2e3d4c5b"
PROMPT = "Fotografía editorial del mostrador de una ferretería en Monterrey, luz natural, sin personas, sin texto y sin logos"


def politica(**kw):
    MARCA.mkdir(exist_ok=True)
    p = MARCA / "higgsfield.json"
    if kw.get("_borrar"):
        p.unlink(missing_ok=True); return
    p.write_text(json.dumps({**POL, **kw}) if not kw.get("_raw") else kw["_raw"])


def corre(op: dict, env: dict | None = None, entrada: bytes | None = None):
    """Una 'sesión': un proceso que llama a higgsfield.opera y termina."""
    spec = {"op": op, "entrada": base64.b64encode(entrada).decode() if entrada else None, "marca": str(MARCA)}
    e = {**os.environ, "GITHUB_API_BASE": GHAPI, "GITHUB_TOKEN": TOKEN, "HIGGSFIELD_API_BASE": API,
         "HIGGSFIELD_API_KEY": LLAVE, "HF_ESPERA_S": "0.01", "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1",
         "HF_SPEC": json.dumps(spec), **(env or {})}
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--driver"], capture_output=True, text=True,
                       env=e, timeout=120)
    salida = r.stdout + r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else None
    return r.returncode, salida, out


def driver():
    sys.path.insert(0, str(HERE))
    import higgsfield as hfn
    spec = json.loads(os.environ["HF_SPEC"])
    op = spec["op"]
    oid, reanudable = hfn.id_operacion(fila=op.get("fila"), campana=op["campana"], pieza=op["pieza"], etapa=op.get("etapa", "original"))
    entrada = base64.b64decode(spec["entrada"]) if spec.get("entrada") else None
    r = hfn.opera(repo=REPO, exclusivo=False, marca=Path(spec["marca"]), op=hfn.Operacion(
        id=oid, campana=op["campana"], pieza=op["pieza"], tipo=op.get("tipo", "generar"), prompt=op.get("prompt", PROMPT),
        aspecto=op.get("aspecto", "16:9"), entrada=entrada, entrada_mime="image/jpeg" if entrada else None,
        meta_extra=op.get("extra", {}), reanudable=reanudable))
    print(json.dumps({"sha256": hashlib.sha256(r.datos).hexdigest(), "meta": r.meta, "reanudada": r.reanudada, "prompt": r.prompt}))


def registro():
    with LOCK:
        if RAMA not in G.refs: return {"entradas": []}, {}
        arbol = {e["path"]: e["sha"] for e in G.trees[G.commits[G.refs[RAMA]]["tree"]]}
        return json.loads(G.blobs[arbol["higgsfield/registro.json"]]), arbol


def ent(op_pieza):
    reg, _ = registro()
    return next((e for e in reg["entradas"] if f":poc/{op_pieza}:" in e["id"]), {})


res = []
def check(nombre, ok, detalle=""):
    res.append(bool(ok)); print(f"{'✓' if ok else '✗'} {nombre} {'' if ok else str(detalle)[-1200:]}")


def op(pieza, **kw):
    return {"fila": FILA, "campana": "poc", "pieza": pieza, **kw}


def main():
    global API, IMG, GHAPI, IMAGEN
    API, IMG, GHAPI = servidor(HHiggs), servidor(HImg), servidor(HGit)
    IMAGEN = imagen()
    sys.path.insert(0, str(HERE))
    import higgsfield as hfn

    # ---------------- proporción desde el marco real
    check("aspecto_para: marco 1080x800 → 4:3, 1080x1920 → 9:16, 904x330 → 16:9, marco inválido → None",
          (hfn.aspecto_para(1080, 800), hfn.aspecto_para(1080, 1920), hfn.aspecto_para(904, 330), hfn.aspecto_para(0, 10))
          == ("4:3", "9:16", "16:9", None))

    # ---------------- permisos y política: cero llamadas
    def sin_llamadas(): return not H.estimates and not H.posts and not H.uploads and RAMA not in G.refs
    politica(_borrar=True); G.reset(); H.reset()
    c, o, _ = corre(op("a"))
    check("sin higgsfield.json: se detiene sin estimate, POST ni registro", c != 0 and "higgsfield.json" in o and sin_llamadas(), o)
    for nombre, kw, txt in [("permitido=false", {"permitido": False}, "no permite Higgsfield"),
                            ("importe como número", {"tope_usd": 5}, "importe"),
                            ("clave desconocida", {"video": True}, "claves no permitidas"),
                            ("generar=false", {"generar": False}, "no permite generar")]:
        politica(**kw); G.reset(); H.reset()
        c, o, _ = corre(op("a"))
        check(f"política {nombre}: se detiene sin llamar a nadie", c != 0 and txt in o and sin_llamadas(), o)
    politica(); G.reset(); H.reset()
    c, o, _ = corre(op("a"), env={"HIGGSFIELD_API_KEY": ""})
    check("sin HIGGSFIELD_API_KEY en el vault: se detiene antes de reservar", c != 0 and "HIGGSFIELD_API_KEY" in o and sin_llamadas(), o)
    c, o, _ = corre(op("a"), env={"HIGGSFIELD_API_BASE": "https://otro-host.example"})
    check("API de Higgsfield en otro host: la llave no sale", c != 0 and "solo va a api.higgsfield.ai" in o and sin_llamadas(), o)
    c, o, _ = corre(op("a"), env={"HF_ENDPOINT": "/kling/video/v3"})
    check("modelo fuera de la lista cerrada: no se cambia de modelo ni se llama", c != 0 and "lista cerrada" in o and sin_llamadas(), o)
    c, o, _ = corre(op("a", aspecto="21:9"))
    check("proporción no soportada: se detiene sin llamar", c != 0 and "Proporción" in o and sin_llamadas(), o)
    politica(referencias_ia=False); G.reset(); H.reset()
    c, o, _ = corre(op("ref", tipo="editar", extra={"referencia": "catalogo"}), entrada=IMAGEN)
    check("la marca prohíbe referencias a IA (aunque fotos.json lo permita): no se sube nada", c != 0 and "referencia" in o
          and sin_llamadas() and not H.puts, o)
    politica(acepta_retencion_uploads_s=3600); G.reset(); H.reset()
    c, o, _ = corre(op("ref", tipo="editar"), entrada=IMAGEN)
    check("la marca no acepta que el upload viva 7 días: se bloquea ANTES de subir", c != 0 and "7 días" in o and sin_llamadas() and not H.puts, o)

    # ---------------- camino feliz, credenciales y retención
    politica(); G.reset(); H.reset()
    c, o, out = corre(op("feliz"))
    e = ent("feliz"); reg, arbol = registro()
    post = H.posts[0] if H.posts else ("", {}, {})
    check("camino feliz: estimate con el cuerpo exacto, 1 POST con Idempotency-Key y Hf-Expires-After: 3600",
          c == 0 and H.estimates == [("/estimate/higgsfield-ai/soul/v2/standard", {"prompt": PROMPT, "aspect_ratio": "16:9"})]
          and len(H.posts) == 1 and post[2].get("Idempotency-Key") == e.get("idempotency_key") and post[2].get("Hf-Expires-After") == "3600", o)
    check("registro: intención congelada (clave, endpoint, cuerpo, webhook, retención) y costo con su calidad de evidencia",
          e.get("estado") == "completed" and e.get("cuerpo") == {"prompt": PROMPT, "aspect_ratio": "16:9"} and e.get("webhook", 1) is None
          and e.get("encabezados") == {"Hf-Expires-After": "3600"} and e.get("estimado_usd") == "0.094"
          and "no es factura" in (e.get("cargo") or {}).get("calidad", ""), json.dumps(e)[:600])
    sha = hashlib.sha256(IMAGEN).hexdigest()
    check("copia propia validada en el registro y metadatos con sha256, blob, mime y dimensiones",
          out and out["sha256"] == sha and arbol.get(f"higgsfield/archivos/{sha}.jpg") == blob_sha(IMAGEN)
          and out["meta"]["blob_sha"] == blob_sha(IMAGEN) and (out["meta"]["ancho"], out["meta"]["alto"], out["meta"]["mime"]) == (1600, 900, "image/jpeg")
          and out["meta"]["registro"]["archivo"] == f"higgsfield/archivos/{sha}.jpg", out)
    check("DELETE /requests/{id} DESPUÉS de guardar la copia; limpieza hecha", H.deletes == ["/requests/req-1"]
          and e.get("limpieza") == "hecha" and (e.get("borrado") or {}).get("ok") is True, json.dumps(e)[:400])
    check("credenciales: la llave de Higgsfield nunca va al CDN, a GitHub ni a la salida; el token de GitHub nunca a Higgsfield",
          H.img_auth == [None] and all(a == f"Bearer {TOKEN}" for a in G.auth) and LLAVE not in o and "hfsecreto" not in json.dumps(registro()[0])
          and all(TOKEN not in json.dumps(h) for _, _, h in H.posts), f"{H.img_auth} {set(G.auth)}")
    n_gets = H.gets
    c, o, out2 = corre(op("feliz"))
    check("Igual/reinicio con el archivo ya guardado: lo baja del registro, CERO llamadas a Higgsfield",
          c == 0 and out2["sha256"] == sha and len(H.posts) == 1 and len(H.estimates) == 1 and H.gets == n_gets and len(H.deletes) == 1
          and out2["reanudada"] is True, o)
    c, o, _ = corre({**op("feliz"), "fila": None})
    check("sin fila de Notion y con una operación previa registrada: se detiene (no se adivina si es el mismo trabajo)",
          c != 0 and "no trae la fila" in o and len(H.posts) == 1, o)

    # ---------------- costo: estimate, máximo por operación, tope agregado y sesiones nuevas
    politica(); G.reset(); H.reset(estimate="0.30")
    c, o, _ = corre(op("cara"))
    check("estimate mayor que el máximo por operación: no hay POST y la reserva se libera (descartada)",
          c != 0 and "máximo por operación" in o and not H.posts and ent("cara").get("estado") == "descartada"
          and hfn.expuesto(registro()[0]) == 0, o)
    G.reset(); H.reset(estimate=None)
    c, o, _ = corre(op("sinest"))
    check("estimate que falla: no hay POST; la reserva queda con su clave para retomar", c != 0 and "estimate" in o and not H.posts
          and ent("sinest").get("estado") == "reservado", o)
    clave0 = ent("sinest").get("idempotency_key")
    H.estimate = "0.094"
    c, o, _ = corre(op("sinest"))
    check("reinicio tras el estimate fallido: retoma la MISMA clave y termina con 1 POST", c == 0 and len(H.posts) == 1
          and H.posts[0][2].get("Idempotency-Key") == clave0, o)
    G.reset(); H.reset(estimate="raro")
    c, o, _ = corre(op("raro"))
    check("estimate sin importe utilizable: no hay POST", c != 0 and not H.posts, o)
    politica(tope_usd="0.20", max_usd_por_operacion="0.10"); G.reset(); H.reset()
    r1 = corre(op("t1")); r2 = corre(op("t2")); r3 = corre(op("t3"))
    check("tope agregado 0.20 USD: dos fotos de 0.094 caben, la tercera se detiene SIN estimate ni POST (sesiones distintas)",
          r1[0] == 0 and r2[0] == 0 and r3[0] != 0 and "Tope de Higgsfield" in r3[1] and len(H.posts) == 2 and len(H.estimates) == 2,
          r3[1])
    check("lo reservado y consumido se suma desde el registro: 0.188 USD", str(hfn.expuesto(registro()[0])) == "0.188", registro()[0])

    # ---------------- concurrencia
    politica(tope_usd="0.10", max_usd_por_operacion="0.10"); G.reset(); H.reset()
    with ThreadPoolExecutor(4) as ex:
        rs = list(ex.map(lambda i: corre(op(f"conc-{i}")), range(4)))
    reg, _ = registro()
    vivas = [x for x in reg["entradas"] if x["estado"] not in ("descartada",)]
    check("4 sesiones concurrentes con cupo para UNA: una sola reserva y un solo POST (CAS sobre la ref)",
          sum(r[0] == 0 for r in rs) == 1 and len(H.posts) == 1 and len(vivas) == 1 and len(reg["entradas"]) == 1,
          f"{[r[0] for r in rs]} posts={len(H.posts)} conflictos={G.conflictos} {json.dumps(reg)[:500]}")
    politica(); G.reset(); H.reset(pendientes=3)
    with ThreadPoolExecutor(2) as ex:
        rs = list(ex.map(lambda i: corre(op("misma")), range(2)))
    check("2 sesiones de la MISMA operación a la vez: una sola generación (misma clave), sin foto duplicada",
          len(H.reqs) == 1 and len(set(h.get("Idempotency-Key") for _, _, h in H.posts)) <= 1 and any(r[0] == 0 for r in rs),
          f"{[r[1][-200:] for r in rs]} reqs={list(H.reqs)}")

    # ---------------- recuperación sin duplicar
    politica(); G.reset(); H.reset(caer_tras_aceptar=1)
    c, o, out = corre(op("perdida"))
    claves = {h.get("Idempotency-Key") for _, _, h in H.posts}
    check("respuesta perdida tras aceptar: se repite el MISMO POST con la MISMA clave y llega el request original",
          c == 0 and len(H.posts) == 2 and len(claves) == 1 and len(H.reqs) == 1 and out["meta"]["request_id"] == "req-1", o)
    G.reset(); H.reset(caer_tras_aceptar=9)
    c, o, _ = corre(op("incierta"), env={"HF_REINTENTOS_ENVIO": "2"})
    e = ent("incierta")
    check("sin respuesta en todos los intentos: queda incierto con su clave, sin clave nueva", c != 0 and "incierto" in o
          and e.get("estado") == "incierto" and not e.get("request_id") and len({h.get("Idempotency-Key") for _, _, h in H.posts}) == 1, o)
    H.caer_tras_aceptar = 0
    c, o, out = corre(op("incierta"))
    check("reinicio: mismo endpoint, cuerpo, retención y clave; Higgsfield devuelve el request original (1 sola generación)",
          c == 0 and len(H.reqs) == 1 and len({h.get("Idempotency-Key") for _, _, h in H.posts}) == 1
          and all(b == {"prompt": PROMPT, "aspect_ratio": "16:9"} and h.get("Hf-Expires-After") == "3600" for _, b, h in H.posts), o)
    G.reset(); H.reset(e503=1)
    c, o, _ = corre(op("e503"))
    check("503 al enviar: mismo POST con la misma clave, una sola generación", c == 0 and len(H.posts) == 2 and len(H.reqs) == 1, o)
    G.reset(); H.reset(pendientes=99)
    c, o, _ = corre(op("lenta"), env={"HF_INTENTOS": "2"})
    check("polling agotado: no pide otra; queda enviado y reanudable", c != 0 and "sigue en" in o and ent("lenta").get("estado") == "enviado", o)
    H.pendientes = 0
    c, o, _ = corre(op("lenta"))
    check("reinicio: retoma ESE request por status_url, sin POST nuevo", c == 0 and len(H.posts) == 1, o)
    G.reset(); H.reset(forzar_422=True)
    c, o, _ = corre(op("c422"))
    check("422 de Idempotency-Key con otros parámetros: conflicto explícito, sin clave nueva", c != 0 and "422" in o
          and ent("c422").get("estado") == "conflicto", o)
    H.forzar_422 = False
    c, o, _ = corre(op("c422"))
    check("reinicio tras el conflicto: no se pide otra foto", c != 0 and "conflicto" in o and len(H.posts) == 1, o)
    G.reset(); H.reset(final="nsfw")
    c, o, _ = corre(op("nsfw"))
    e = ent("nsfw")
    check("nsfw: fallo explícito, sin cobro según la documentación (no un cero inventado), DELETE y sin reintento",
          c != 0 and "nsfw" in o and e.get("estado") == "nsfw" and "documentación" in (e.get("cargo") or {}).get("calidad", "")
          and H.deletes == ["/requests/req-1"] and hfn.expuesto(registro()[0]) == 0, json.dumps(e)[:400])
    c, o, _ = corre(op("nsfw"))
    check("reinicio tras nsfw: no se pide otra", c != 0 and len(H.posts) == 1, o)

    # ---------------- descarga y validación
    G.reset(); H.reset(img_500=1)
    c, o, _ = corre(op("cdn"))
    check("CDN falla: no paga otra foto; queda reanudable", c != 0 and "No se pide otra" in o and ent("cdn").get("estado") == "enviado"
          and not ent("cdn").get("archivo"), o)
    c, o, out = corre(op("cdn"))
    check("reinicio: baja el resultado del MISMO request (1 POST en total)", c == 0 and len(H.posts) == 1 and out["sha256"] == hashlib.sha256(IMAGEN).hexdigest(), o)
    G.reset(); H.reset(imagen=b"<html>" + b"x" * 20000, tipo_imagen="image/jpeg")
    c, o, _ = corre(op("falsa"))
    check("un HTML que dice ser image/jpeg no pasa (firma real) y no se guarda", c != 0 and "firma" in o and not ent("falsa").get("archivo"), o)
    G.reset(); H.reset(imagen=b"\xff\xd8\xff" + os.urandom(30000))
    c, o, _ = corre(op("rota"))
    check("una imagen que no decodifica no pasa", c != 0 and "decodificar" in o, o)
    G.reset(); H.reset(imagen=imagen(200, 120, semilla=3))
    c, o, _ = corre(op("chica"))
    check("dimensiones inválidas no pasan", c != 0 and ("dimensiones" in o or "tamaño" in o), o)
    G.reset(); H.reset(imagen=imagen(1200, 1200, "PNG", 5), tipo_imagen="application/octet-stream")
    c, o, out = corre(op("png", aspecto="1:1"))
    check("PNG servido como octet-stream: se valida por firma y decodificación", c == 0 and out["meta"]["mime"] == "image/png", o)

    # ---------------- retención y limpieza
    G.reset(); H.reset(delete_code=503)
    c, o, out = corre(op("borr"))
    e = ent("borr")
    check("DELETE fallido: la foto queda (copia propia) y la limpieza pendiente se registra sin fingir éxito",
          c == 0 and "limpieza pendiente" in o and e.get("limpieza") == "pendiente" and (e.get("borrado") or {}).get("ok") is False
          and out["meta"]["borrado"]["ok"] is False, json.dumps(e)[:400])
    H.delete_code = 200
    c, o, _ = corre(op("borr"))
    check("al retomar se reintenta SOLO la limpieza (ninguna generación nueva)", c == 0 and len(H.posts) == 1 and ent("borr").get("limpieza") == "hecha", o)
    G.reset(); H.reset()
    entrada = imagen(1000, 800, semilla=9)
    c, o, out = corre(op("edit", tipo="editar", etapa="ronda-pr7-abc-Editar", extra={"edita": blob_sha(entrada)}), entrada=entrada)
    e = ent("edit")
    check("Editar: sube la entrada SIN la llave, estima y edita con image_urls; registra el upload con retención de 7 días pendiente",
          c == 0 and H.puts == [(None, len(entrada))] and H.posts[0][0] == "/alibaba/qwen-image-3/edit"
          and H.posts[0][1] == {"prompt": PROMPT, "image_urls": ["https://cdn.prueba/in-1.jpg"]}
          and H.estimates[0][0] == "/estimate/alibaba/qwen-image-3/edit" and (e.get("subida") or {}).get("limpieza") == "pendiente"
          and "7 días" in (e.get("subida") or {}).get("retencion", "") and out["meta"]["input_sha256"] == hashlib.sha256(entrada).hexdigest()
          and out["meta"]["edita"] == blob_sha(entrada), json.dumps(e)[:500])
    c, o, _ = corre(op("edit2", tipo="editar"), entrada=imagen(1000, 800, semilla=10), env={"HF_EDICION_ENDPOINT": "/higgsfield-ai/soul/v2/standard"})
    check("Editar con el modelo de generación: no se cambia de modelo", c != 0 and "lista cerrada" in o and not H.puts[1:], o)

    print(f"\n{sum(res)}/{len(res)} comprobaciones correctas.")
    sys.exit(0 if all(res) else 1)


if __name__ == "__main__":
    if "--driver" in sys.argv:
        driver()
    else:
        main()
