"""Núcleo Higgsfield del agente Creativo: API controlada (llave del vault, saldo API en USD). No es el MCP ni otra ruta.

Lo usa pr_pieza.py (foto y revisar-pr). No sabe de HTML ni de Canva: recibe la intención (generar o editar), la
proporción ya resuelta (del marco real) y, si hay, la imagen de entrada; devuelve los bytes validados y lo que va en
pieza.json → higgsfield. Quien compone (plantilla HTML o Canva) pone el archivo; aquí no se aplana texto ni logo.

Una operación NUEVA, en este orden (cada paso falla cerrado y antes de gastar):
  1. Política del cliente: higgsfield.json del repo de marca montado (tope USD agregado, cota por operación, si permite
     generar, editar y referencias, y cuánta retención de uploads acepta). Sin política no hay Higgsfield.
  2. Identidad: la fila de Notion (--fila, la pone el harness). Sin ella no hay Higgsfield: no se podría retomar.
  3. Red y modelo: API fija (api.higgsfield.ai, sin seguir redirecciones con la llave), endpoint de una lista cerrada y
     cuerpo con exactamente sus campos; proporción de la lista de Soul v2. Nunca se cambia de modelo ni de proporción.
  4. Reserva atómica y duradera de la cota en el REGISTRO del cliente (antes de subir nada ni estimar): rama
     agente/higgsfield del repo de piezas del cliente, higgsfield/registro.json; se escribe con un commit encima de la
     punta y PATCH de la ref sin forzar (CAS): si otra sesión escribió antes, se relee y se vuelve a comprobar el tope.
     El registro lo crea una persona una vez (iniciar); si falta o lo borran, no hay Higgsfield (no vuelve a cero).
     Una pieza y etapa (original o ronda) tiene UNA operación; de otra fila de Notion, se detiene.
  5. Con imagen de entrada (Editar o referencia:): la marca tiene que aceptar que los uploads vivan hasta 7 días
     (Higgsfield los guarda aparte del request y no hay borrado por API); se sube SIN la llave a la URL firmada.
  6. Estimate autenticado con el cuerpo EXACTO. Tiene que caber en la cota por operación y en el tope agregado.
  7. Se congelan en el registro, ANTES del POST: Idempotency-Key, endpoint, cuerpo, webhook (ninguno) y Hf-Expires-After.
  8. POST con esa clave. Red, timeout, 3xx, 408, 429 o 5xx: el MISMO POST con la MISMA clave (HF_REINTENTOS_ENVIO, máx. 3).
     4xx de la primera respuesta: rechazada, sin cobro. 4xx después de un intento sin respuesta: incierto (cuenta).
     422 por huella distinta: conflicto. Nunca se crea otra clave sola.
  9. request_id y status_url al registro; polling acotado (HF_INTENTOS × HF_ESPERA_S). Si no termina, queda reanudable.
 10. Descarga SIN la llave, validación (firma, decodificación con Pillow, tamaño, dimensiones), sha256/sha1/blob y copia
     propia en el registro (higgsfield/archivos/<sha256>.<ext>) ANTES del DELETE /requests/{id}. Un DELETE fallido queda
     como limpieza pendiente; el archivo propio no se pierde.
Reanudar: la misma pieza y etapa con la MISMA fila (el reintento de esa fila de Notion) retoma su entrada: con el archivo
ya guardado lo baja del registro (cero llamadas a Higgsfield); enviada, consulta su status_url; congelada y sin respuesta
(menos de HF_VENTANA_REPLAY_H horas), repite el MISMO POST con la MISMA clave. failed/nsfw/canceled/conflicto: no se pide
otra. Liberar o cerrar a mano: `python3 higgsfield.py estado|liberar` (solo personas; queda en el historial).
Costos: estimate autenticado previo al envío (no es factura). failed/nsfw/canceled no se cobran según la documentación
de Higgsfield; se registran así, con esa calidad de evidencia, nunca como cero inventado.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import io
import json
import math
import os
import random
import re
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gh_pr import blob_sha, die, gh, repo_exclusivo  # noqa: E402

API_OFICIAL = "https://api.higgsfield.ai"
API = os.environ.get("HIGGSFIELD_API_BASE", API_OFICIAL).rstrip("/")
SOUL = "/higgsfield-ai/soul/v2/standard"
# Edición con instrucción e imagen de entrada (Editar en una ronda, y --referencia): image_urls (URLs públicas), sin máscara.
QWEN = "/alibaba/qwen-image-3/edit"
MODELOS = {SOUL: {"tipo": "generar", "campos": ("prompt", "aspect_ratio")},
           QWEN: {"tipo": "editar", "campos": ("prompt", "image_urls")}}
# Proporciones que acepta Soul v2 (otra responde 400; pasó con 21:9 el 3 nov 2026).
ASPECTOS = ("9:16", "16:9", "4:3", "3:4", "1:1", "2:3", "3:2")
RETENCION_S = "3600"           # Hf-Expires-After mínimo que acepta la API (menos es 422)
UPLOAD_RETENCION_S = 7 * 24 * 3600  # uploads y copias reutilizables: se borran "within seven days", aparte del request
MIN_BYTES, MAX_BYTES = 10_000, 15 * 1024 * 1024
MIN_LADO, MAX_LADO = 256, 10_000
FIRMAS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
TERMINALES = ("completed", "failed", "nsfw", "canceled")
SIN_CARGO = ("failed", "nsfw", "canceled", "rechazada", "descartada")  # no cuentan contra el tope
RAMA = "agente/higgsfield"
RUTA = "higgsfield/registro.json"
ARCHIVOS = "higgsfield/archivos/"
POLITICA = "higgsfield.json"
UA = "5cero5-creativo"
USD = re.compile(r"^\d{1,4}(\.\d{1,6})?$")
FILA = re.compile(r"^[0-9a-f]{32}$")


def _num_env(k: str, defecto: int, maximo: int) -> int:
    v = os.environ.get(k, "").strip()
    return max(0, min(maximo, int(v))) if v.isdigit() else defecto


def _prueba_local(url: str = API) -> bool:
    """Solo los servidores de prueba en http://127.0.0.1:<puerto> (sin usuario ni otro host escondido)."""
    u = urlparse(url)
    return u.scheme == "http" and u.hostname == "127.0.0.1" and "@" not in u.netloc


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ HTTP con la llave (único cliente de la API)
class ErrorHF(Exception):
    """La API respondió con un código HTTP de error (la solicitud llegó)."""
    def __init__(self, code: int, detalle: str):
        super().__init__(f"{code}: {detalle}")
        self.code, self.detalle = code, detalle


class RedHF(Exception):
    """No hubo respuesta utilizable (red, timeout, conexión cortada, redirección): resultado incierto."""


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    """Con la llave no se sigue ninguna redirección: urllib copiaría Authorization al otro host."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RedHF(f"redirección {code} a {urlparse(newurl).netloc} rechazada (la llave no sigue redirecciones)")


_CON_LLAVE = urllib.request.build_opener(_SinRedireccion)


def llama(method: str, url: str, body: dict | None = None, extra: dict | None = None, timeout: float = 60) -> dict:
    key = os.environ.get("HIGGSFIELD_API_KEY", "").strip()
    if not key:
        die("Falta HIGGSFIELD_API_KEY.")
    if urlparse(url).netloc != urlparse(API).netloc or urlparse(url).scheme != urlparse(API).scheme:
        die(f"La API de Higgsfield pidió consultar otro host ({urlparse(url).netloc}): no se manda la llave ahí.")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Key {key}", "Accept": "application/json", "User-Agent": UA,
                                          **({"Content-Type": "application/json"} if body is not None else {}), **(extra or {})})
    try:
        with _CON_LLAVE.open(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise ErrorHF(e.code, e.read()[:300].decode("utf-8", "ignore")) from None
    except RedHF:
        raise
    except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, http.client.HTTPException, ValueError) as e:
        raise RedHF(f"{type(e).__name__}: {e}"[:200]) from None


def hf(method: str, url: str, body: dict | None = None, extra: dict | None = None) -> dict:
    """La llamada de siempre de pr_pieza.py: cualquier error termina el proceso con el motivo."""
    try:
        return llama(method, url, body, extra)
    except ErrorHF as e:
        die(f"Higgsfield respondió {e.code} a {method} {urlparse(url).path}: {e.detalle}")
    except RedHF as e:
        die(f"No hubo respuesta de Higgsfield a {method} {urlparse(url).path} ({e}).")


# ------------------------------------------------------------------ política del cliente (repo de marca)
CLAVES_POLITICA = {"version", "permitido", "tope_usd", "max_usd_por_operacion", "generar", "editar", "referencias_ia",
                   "acepta_retencion_uploads_s", "notas"}


def usd(v, que: str) -> Decimal:
    """USD decimal desde texto ("0.094"); un número de punto flotante, negativo o raro no se acepta."""
    if not isinstance(v, str) or not USD.match(v.strip()):
        raise ValueError(f"{que}: {v!r} no es un importe en USD como texto (por ejemplo \"0.094\")")
    try:
        return Decimal(v.strip())
    except InvalidOperation:
        raise ValueError(f"{que}: {v!r} no es un importe") from None


def politica(marca: Path) -> dict:
    """higgsfield.json del repo de marca del cliente. Contrato cerrado: claves de más, tipos raros o importes como número
    detienen todo. Lo que la marca prohíbe prevalece sobre lo que el modelo puede hacer."""
    p = marca / POLITICA
    if not p.is_file():
        die(f"El repo de marca de este cliente no trae {POLITICA}: sin política declarada (tope en USD y permisos) no se usa "
            "Higgsfield. La pieza puede ir sin foto o con una foto del repo (repo:<id>).")
    try:
        d = json.loads(p.read_text(encoding="utf-8"), parse_float=lambda s: (_ for _ in ()).throw(ValueError("float")))
    except (ValueError, json.JSONDecodeError) as e:
        die(f"{POLITICA} del repo de marca no es válido ({e}); los importes van como texto.")
    if not isinstance(d, dict) or set(d) - CLAVES_POLITICA:
        die(f"{POLITICA}: claves no permitidas {sorted(set(d) - CLAVES_POLITICA) if isinstance(d, dict) else d!r}.")
    faltan = [k for k in ("version", "permitido", "tope_usd", "max_usd_por_operacion") if k not in d]
    if faltan or d.get("version") != 1:
        die(f"{POLITICA}: faltan {faltan or '-'} o la versión no es 1.")
    for k in ("permitido", "generar", "editar", "referencias_ia"):
        if k in d and type(d[k]) is not bool:
            die(f"{POLITICA}: {k} tiene que ser true o false.")
    try:
        tope, maximo = usd(d["tope_usd"], "tope_usd"), usd(d["max_usd_por_operacion"], "max_usd_por_operacion")
    except ValueError as e:
        die(f"{POLITICA}: {e}.")
    if not (Decimal(0) < maximo <= tope):
        die(f"{POLITICA}: max_usd_por_operacion tiene que ser mayor que 0 y no pasar de tope_usd.")
    ret = d.get("acepta_retencion_uploads_s", 0)
    if type(ret) is not int or ret < 0:
        die(f"{POLITICA}: acepta_retencion_uploads_s tiene que ser un entero de segundos.")
    if d["permitido"] is not True:
        die(f"{POLITICA}: la marca no permite Higgsfield (permitido = false). No se pide foto.")
    return {"tope": tope, "maximo": maximo, "generar": d.get("generar", True), "editar": d.get("editar", False),
            "referencias_ia": d.get("referencias_ia", False), "retencion_uploads": ret,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


# ------------------------------------------------------------------ proporción desde el marco real
def aspecto_para(ancho: int, alto: int, permitidos: tuple = ASPECTOS) -> str | None:
    """La proporción permitida más cercana a un marco de ancho×alto (px del hueco de la imagen en el diseño o en la
    plantilla). None si no hay ninguna permitida o el marco no es válido: entonces no se llama a Higgsfield."""
    if not permitidos or not (isinstance(ancho, int) and isinstance(alto, int)) or ancho <= 0 or alto <= 0:
        return None
    r = math.log(ancho / alto)
    return min(permitidos, key=lambda x: abs(math.log(int(x.split(':')[0]) / int(x.split(':')[1])) - r))


# ------------------------------------------------------------------ registro duradero (GitHub, CAS)
def _g(method: str, path: str, body: dict | None = None, ok: tuple = ()) -> dict:
    return gh(method, path, body, UA, permitidos=ok)


def _contenido(repo: str, head: str, ruta: str) -> bytes | None:
    tree = _g("GET", f"/repos/{repo}/git/commits/{head}")["tree"]["sha"]
    ent = next((e for e in _g("GET", f"/repos/{repo}/git/trees/{tree}?recursive=1").get("tree", [])
                if e.get("path") == ruta and e.get("type") == "blob"), None)
    return base64.b64decode(_g("GET", f"/repos/{repo}/git/blobs/{ent['sha']}").get("content", "")) if ent else None


def lee_registro(repo: str) -> tuple[str, dict]:
    """(punta de la rama agente/higgsfield, registro). Sin registro o ilegible, se detiene: nunca vuelve a cero."""
    r = _g("GET", f"/repos/{repo}/git/ref/heads/{RAMA}", ok=(404,))
    if r.get("_status") == 404:
        die(f"{repo} no tiene el registro de Higgsfield (rama {RAMA}). Lo crea una persona una vez con "
            f"`python3 higgsfield.py iniciar --repo {repo}`; si existía y lo borraron, hay que restaurarlo, no recrearlo. "
            "No se llama a Higgsfield.")
    head = r["object"]["sha"]
    datos = _contenido(repo, head, RUTA)
    if datos is None:
        die(f"La rama {RAMA} de {repo} no trae {RUTA}. No se toca a mano: revisarla antes de pedir fotos.")
    try:
        reg = json.loads(datos)
    except (ValueError, json.JSONDecodeError):
        die(f"{RUTA} en {RAMA} no es JSON válido. No se llama a Higgsfield.")
    if not isinstance(reg, dict) or reg.get("version") != 1 or str(reg.get("repo", "")).lower() != repo.lower() \
            or not isinstance(reg.get("entradas"), list):
        die(f"{RUTA} en {RAMA} no es un registro de {repo}. No se llama a Higgsfield.")
    return head, reg


def lee_archivo(repo: str, ruta: str, sha256: str) -> bytes:
    """El archivo propio guardado en el registro, comprobado por sha256."""
    head, _ = lee_registro(repo)
    datos = _contenido(repo, head, ruta)
    if datos is None:
        die(f"El registro dice que la foto está en {ruta}, pero no está en {RAMA}. No se pide otra.")
    if hashlib.sha256(datos).hexdigest() != sha256:
        die(f"La copia guardada en {ruta} no coincide con su sha256. No se pide otra.")
    return datos


def escribe_registro(repo: str, cambia, mensaje: str, archivos: dict[str, bytes] | None = None) -> dict:
    """cambia(registro) → registro nuevo, None (nada que escribir) o die(). Un commit encima de la punta y la ref sin
    forzar: si otra sesión escribió antes (no es fast-forward), se relee y se vuelve a aplicar cambia, que vuelve a
    comprobar el tope y el estado. Devuelve el registro que quedó escrito (o el leído, si no hubo nada que escribir)."""
    for i in range(_num_env("HF_REGISTRO_INTENTOS", 6, 12)):
        head, reg = lee_registro(repo)
        nuevo = cambia(json.loads(json.dumps(reg)))
        if nuevo is None:
            return reg
        datos = (json.dumps(nuevo, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
        entradas = []
        for ruta, b in {RUTA: datos, **(archivos or {})}.items():
            sha = _g("POST", f"/repos/{repo}/git/blobs", {"content": base64.b64encode(b).decode(), "encoding": "base64"})["sha"]
            entradas.append({"path": ruta, "mode": "100644", "type": "blob", "sha": sha})
        base_tree = _g("GET", f"/repos/{repo}/git/commits/{head}")["tree"]["sha"]
        arbol = _g("POST", f"/repos/{repo}/git/trees", {"base_tree": base_tree, "tree": entradas})["sha"]
        commit = _g("POST", f"/repos/{repo}/git/commits", {"message": mensaje, "tree": arbol, "parents": [head]})["sha"]
        r = _g("PATCH", f"/repos/{repo}/git/refs/heads/{RAMA}", {"sha": commit, "force": False}, ok=(409, 422))
        if "_status" not in r:
            return nuevo
        time.sleep(random.uniform(0.05, 0.3) * (i + 1))
    die(f"No se pudo escribir el registro de Higgsfield en {repo} (otra sesión escribe al mismo tiempo). Se detiene aquí.")


def expuesto(reg: dict) -> Decimal:
    """USD reservados o consumidos (estimado previo) en todo el registro del cliente."""
    total = Decimal(0)
    for e in reg.get("entradas", []):
        if e.get("estado") not in SIN_CARGO:
            total += Decimal(e.get("estimado_usd") or e.get("cota_usd") or "0")
    return total


def entrada(reg: dict, op_id: str) -> dict | None:
    return next((e for e in reg.get("entradas", []) if e.get("id") == op_id), None)


def _actualiza(repo: str, op_id: str, mensaje: str, archivos: dict[str, bytes] | None = None, *,
               solo_si: tuple = (), evento: str | None = None, **campos) -> dict:
    """Cambia campos de UNA entrada. solo_si: estados desde los que vale el cambio; si la entrada ya está en otro (otra
    sesión de la misma operación avanzó), no se escribe nada y se devuelve la entrada como está."""
    def cambia(reg):
        e = entrada(reg, op_id)
        if e is None:
            die(f"El registro ya no tiene la operación {op_id}. Se detiene aquí.")
        if solo_si and e.get("estado") not in solo_si:
            return None
        e.update(json.loads(json.dumps(campos)))
        if evento:
            e.setdefault("historial", []).append({"en": ahora(), "evento": evento})
        return reg
    return entrada(escribe_registro(repo, cambia, mensaje, archivos), op_id)


# ------------------------------------------------------------------ imagen: descarga y validación
def valida_imagen(datos: bytes, tipo_http: str | None) -> dict:
    """Firma real, decodificación completa con Pillow, tamaño y dimensiones. No basta el Content-Type ni la URL."""
    if not MIN_BYTES <= len(datos) <= MAX_BYTES:
        raise ValueError(f"tamaño {len(datos)} bytes fuera de {MIN_BYTES}..{MAX_BYTES}")
    mime = ("image/jpeg" if datos[:3] == b"\xff\xd8\xff" else "image/png" if datos[:8] == b"\x89PNG\r\n\x1a\n"
            else "image/webp" if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP" else None)
    if not mime:
        raise ValueError("no es JPEG, PNG ni WebP por su firma")
    if tipo_http and tipo_http not in (mime, "application/octet-stream", "binary/octet-stream") and not (
            mime == "image/jpeg" and tipo_http == "image/jpg"):
        raise ValueError(f"el servidor dice {tipo_http} y el archivo es {mime}")
    try:
        from PIL import Image
    except ImportError:
        raise ValueError("falta Pillow para decodificar la imagen (pip install pillow)") from None
    try:
        with Image.open(io.BytesIO(datos)) as im:
            im.verify()
        with Image.open(io.BytesIO(datos)) as im:
            im.load()
            ancho, alto, fmt = im.size[0], im.size[1], im.format
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"no se puede decodificar ({type(e).__name__})") from None
    if {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(fmt) != mime:
        raise ValueError(f"Pillow la lee como {fmt}, no como {mime}")
    if not (MIN_LADO <= ancho <= MAX_LADO and MIN_LADO <= alto <= MAX_LADO):
        raise ValueError(f"dimensiones {ancho}x{alto} fuera de {MIN_LADO}..{MAX_LADO}")
    return {"mime": mime, "ext": FIRMAS[mime], "ancho": ancho, "alto": alto}


def baja(url: str) -> tuple[bytes, str | None, str]:
    """Descarga SIN la llave (otro host). Solo https, también tras redirecciones (las pruebas sirven en 127.0.0.1).
    Devuelve (bytes, Content-Type, host final)."""
    if urlparse(url).scheme != "https" and not _prueba_local(url):
        raise ValueError(f"URL de imagen no https: {urlparse(url).scheme}://{urlparse(url).netloc}")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
        final = r.geturl()
        if urlparse(final).scheme != "https" and not _prueba_local(final):
            raise ValueError(f"la descarga terminó en una URL no https ({urlparse(final).netloc})")
        return r.read(MAX_BYTES + 1), r.headers.get_content_type(), urlparse(final).netloc


def sube(datos: bytes, mime: str) -> dict:
    """URL firmada de Higgsfield y PUT del archivo SIN la llave (otro host). Devuelve public_url y su host."""
    r = hf("POST", API + "/files/generate-upload-url", {"content_type": mime})
    subir, publica = r.get("upload_url"), r.get("public_url")
    if not subir or not publica or (urlparse(subir).scheme != "https" and not _prueba_local(subir)) \
            or (urlparse(publica).scheme != "https"):
        die(f"Higgsfield no regresó upload_url y public_url https: {json.dumps(r)[:200]}")
    enc = {k: v for k, v in (r.get("upload_headers") or {}).items() if k.lower() not in ("authorization", "cookie")}
    try:
        with urllib.request.urlopen(urllib.request.Request(subir, data=datos, method="PUT", headers={"User-Agent": UA, **enc}), timeout=120):
            pass
    except Exception as e:  # noqa: BLE001
        die(f"No pude subir la imagen a {urlparse(subir).netloc} ({type(e).__name__}). Si es un host nuevo, hay que "
            "agregarlo a la red del entorno.")
    return {"public_url": publica, "host": urlparse(publica).netloc}


def borra(rid: str) -> dict:
    """DELETE /requests/{id}: borra entrada, salida, prompt y parámetros del request (no los uploads ni el cobro)."""
    try:
        r = llama("DELETE", f"{API}/requests/{rid}")
        return {"ok": True, "estado": r.get("status") or "deleted", "en": ahora()}
    except ErrorHF as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.detalle[:150]}", "en": ahora()}
    except RedHF as e:
        return {"ok": False, "error": str(e)[:150], "en": ahora()}


# ------------------------------------------------------------------ la operación
@dataclass
class Operacion:
    id: str                      # pieza + etapa (original o ronda): UNA operación por id en todo el registro
    fila: str | None             # fila de Notion dueña (normalizada); sin ella no hay Higgsfield
    campana: str
    pieza: str
    tipo: str                    # generar | editar
    prompt: str
    aspecto: str | None = None   # solo generar
    entrada: bytes | None = None  # solo editar: la imagen de entrada
    entrada_mime: str | None = None
    meta_extra: dict = field(default_factory=dict)  # referencia, edita, aspect_ratio… (van a pieza.json)


@dataclass
class Resultado:
    datos: bytes
    ext: str
    prompt: str                  # el registrado (si se retomó otra sesión, el de esa intención)
    meta: dict                   # lo que va en pieza.json → higgsfield
    reanudada: bool


def id_operacion(*, fila: str | None, campana: str, pieza: str, etapa: str) -> tuple[str, str | None]:
    """(id de la operación, fila normalizada). El id es la pieza y la etapa; la fila es su dueña."""
    f = re.sub("-", "", fila or "").lower() or None
    if f is not None and not FILA.match(f):
        die(f"--fila no es un id de página de Notion: {fila!r}.")
    return f"{campana}/{pieza}:{etapa}", f


def _cuerpo(op: Operacion, image_urls: list[str] | None) -> tuple[str, dict]:
    if op.tipo == "generar":
        endpoint = os.environ.get("HF_ENDPOINT", "").strip() or SOUL
        cuerpo = {"prompt": op.prompt, "aspect_ratio": op.aspecto}
    elif op.tipo == "editar":
        endpoint = os.environ.get("HF_EDICION_ENDPOINT", "").strip() or QWEN
        cuerpo = {"prompt": op.prompt, "image_urls": image_urls or []}
    else:
        die(f"Tipo de operación desconocido: {op.tipo!r}.")
    m = MODELOS.get(endpoint)
    if not m or m["tipo"] != op.tipo:
        die(f"El modelo {endpoint} no está en la lista cerrada para {op.tipo} ({', '.join(MODELOS)}). No se cambia de modelo.")
    if tuple(cuerpo) != m["campos"] or not isinstance(op.prompt, str) or not op.prompt.strip():
        die("El cuerpo de la solicitud no tiene exactamente los campos del modelo.")
    if op.tipo == "generar" and op.aspecto not in ASPECTOS:
        die(f"Proporción {op.aspecto!r} fuera de las que acepta Soul v2 ({', '.join(ASPECTOS)}). No se pidió la foto.")
    if op.tipo == "editar" and (len(cuerpo["image_urls"]) != 1 or urlparse(cuerpo["image_urls"][0]).scheme != "https"):
        die("La edición lleva exactamente una URL https de entrada.")
    return endpoint, cuerpo


def _sha_cuerpo(endpoint: str, cuerpo: dict, encabezados: dict) -> str:
    return hashlib.sha256(json.dumps({"endpoint": endpoint, "cuerpo": cuerpo, "encabezados": encabezados, "webhook": None},
                                     sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def preflight(pol: dict, op: Operacion) -> None:
    if API != API_OFICIAL and not _prueba_local():
        die(f"HIGGSFIELD_API_BASE apunta a {urlparse(API).netloc}: la llave solo va a {urlparse(API_OFICIAL).netloc}.")
    if not op.fila:
        die("Sin --fila (el id de la fila de Notion, que pone el harness) no se usa Higgsfield: no se podría retomar la "
            "foto en otra sesión sin pagar otra. No se pidió la foto.")
    if not os.environ.get("HIGGSFIELD_API_KEY", "").strip():
        die("Falta HIGGSFIELD_API_KEY (no está en el vault de este cliente). No se pidió la foto.")
    if op.tipo == "generar" and not pol["generar"]:
        die(f"{POLITICA}: la marca no permite generar fotos con Higgsfield.")
    if op.tipo == "editar":
        if not pol["editar"]:
            die(f"{POLITICA}: la marca no permite editar fotos con Higgsfield.")
        if op.meta_extra.get("referencia") and not pol["referencias_ia"]:
            die(f"{POLITICA}: la marca no permite mandar sus fotos como referencia a la IA, aunque fotos.json lo diga.")
        if pol["retencion_uploads"] < UPLOAD_RETENCION_S:
            die(f"{POLITICA}: la marca acepta {pol['retencion_uploads']} s de retención para uploads y Higgsfield los guarda "
                f"hasta {UPLOAD_RETENCION_S} s (7 días) sin borrado por API. No se sube nada.")
        if not op.entrada or op.entrada_mime not in FIRMAS:
            die("La edición necesita la imagen de entrada (jpg, png o webp).")
    _cuerpo(op, ["https://x.invalid/entrada"] if op.tipo == "editar" else None)  # modelo, campos y proporción


def opera(*, repo: str, exclusivo: bool, marca: Path, op: Operacion, al_reservar=None) -> Resultado:
    """Hace (o retoma) UNA operación. al_reservar() se llama una vez, al reservar una intención nueva (tope por sesión)."""
    pol = politica(marca)
    preflight(pol, op)
    if exclusivo:
        repo_exclusivo(repo, UA)
    _, reg = lee_registro(repo)
    previa = entrada(reg, op.id)
    if previa is not None:
        if previa.get("fila") != op.fila:
            die(f"{op.campana}/{op.pieza} ya tiene una operación de Higgsfield para esta etapa ({previa.get('estado')}, request "
                f"{previa.get('request_id') or 'sin aceptar'}) de otra fila de Notion. No se pide otra foto: termina sin PR y "
                "explícalo.")
        if previa.get("tipo") != op.tipo:
            die(f"La operación registrada {op.id} es de otro tipo ({previa.get('tipo')}). No se pide otra foto.")
        print(f"· Se retoma la operación registrada {op.id} (estado {previa.get('estado')}): misma intención, misma clave.")
        return _continua(repo, pol, op, previa, True)
    # Intención nueva: cota máxima reservada antes de subir nada ni estimar.
    clave = str(uuid.uuid4())

    def reserva(reg):
        if entrada(reg, op.id):
            die(f"Otra sesión registró {op.id} al mismo tiempo. No se pide otra foto: corre de nuevo para retomarla.")
        if expuesto(reg) + pol["maximo"] > pol["tope"]:
            die(f"Tope de Higgsfield del cliente: {expuesto(reg)} USD reservados o consumidos de {pol['tope']}; una operación "
                f"puede costar hasta {pol['maximo']}. No se pidió la foto.")
        reg["entradas"].append({
            "id": op.id, "fila": op.fila, "campana": op.campana, "pieza": op.pieza, "tipo": op.tipo, "estado": "reservado",
            "idempotency_key": clave, "cota_usd": str(pol["maximo"]), "politica_sha256": pol["sha256"],
            "entrada_sha256": hashlib.sha256(op.entrada).hexdigest() if op.entrada else None,
            "subida": {"estado": "pendiente"} if op.entrada else None, "meta_extra": op.meta_extra,
            "reservado_en": ahora(), "historial": [{"en": ahora(), "evento": "reservado"}]})
        return reg
    escrito = escribe_registro(repo, reserva, f"Higgsfield: reserva {op.id}")
    if al_reservar:
        al_reservar()
    return _continua(repo, pol, op, entrada(escrito, op.id), False)


def _congela(repo: str, pol: dict, op: Operacion, e: dict, reanudada: bool) -> dict:
    """Sube la entrada (si hay), estima con el cuerpo exacto y congela intención, clave y cuerpo ANTES del POST."""
    image_urls, subida = None, None
    if op.tipo == "editar":
        if not op.entrada:
            die(f"La operación {op.id} quedó sin congelar y esta corrida no trae la imagen de entrada. No se pide otra foto.")
        if hashlib.sha256(op.entrada).hexdigest() != e.get("entrada_sha256"):
            die(f"La imagen de entrada no es la que se reservó para {op.id}. No se sube ni se pide nada.")
        s = sube(op.entrada, op.entrada_mime)
        image_urls = [s["public_url"]]
        subida = {"estado": "subida", "host": s["host"], "sha256": e["entrada_sha256"], "en": ahora(),
                  "retencion": "hasta 7 días en Higgsfield, aparte del request; sin borrado por API", "limpieza": "pendiente"}
        previa = e.get("subida") or {}
        if reanudada and previa.get("estado") == "pendiente":
            subida["anterior"] = "una corrida anterior pudo subir la misma imagen sin registrarla (hasta 7 días en Higgsfield)"
        elif previa.get("estado") == "subida":  # se conserva el rastro del upload anterior: también queda hasta 7 días
            subida["anterior"] = {k: previa[k] for k in ("host", "sha256", "en", "retencion", "limpieza") if k in previa}
    endpoint, cuerpo = _cuerpo(op, image_urls)
    try:
        est = llama("POST", f"{API}/estimate{endpoint}", cuerpo)
        v = est.get("usd")
        estimado = usd(str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v, "estimate")
    except (ErrorHF, RedHF, ValueError) as err:
        _actualiza(repo, op.id, f"Higgsfield: estimate fallido {op.id}", solo_si=("reservado",),
                   evento=f"estimate fallido: {str(err)[:120]}", subida=subida or e.get("subida"))
        die(f"No hay estimate utilizable para {endpoint} ({str(err)[:160]}). No se pidió la foto; la reserva queda para "
            "retomarla con la misma clave.")
    if estimado > pol["maximo"]:
        _actualiza(repo, op.id, f"Higgsfield: descartada {op.id}", solo_si=("reservado",), estado="descartada",
                   estimado_usd=str(estimado), subida=subida or e.get("subida"),
                   evento=f"estimate {estimado} > máximo {pol['maximo']}")
        die(f"El estimate ({estimado} USD) pasa el máximo por operación de la marca ({pol['maximo']}). No se pidió la foto.")
    encabezados = {"Hf-Expires-After": RETENCION_S}

    def congela(reg):
        x = entrada(reg, op.id)
        if x is None or x.get("estado") != "reservado":
            die(f"La operación {op.id} cambió de estado mientras se preparaba ({x and x.get('estado')}). Se detiene aquí.")
        otros = expuesto(reg) - Decimal(x.get("cota_usd") or "0")
        if otros + estimado > pol["tope"]:
            x.update(estado="descartada", estimado_usd=str(estimado))
            x.setdefault("historial", []).append({"en": ahora(), "evento": "tope agregado"})
            return reg
        x.update(estado="listo", endpoint=endpoint, cuerpo=cuerpo, encabezados=encabezados, webhook=None,
                 cuerpo_sha256=_sha_cuerpo(endpoint, cuerpo, encabezados), estimado_usd=str(estimado),
                 estimado_en=ahora(), congelado_en=ahora(), subida=subida or x.get("subida"))
        x.setdefault("historial", []).append({"en": ahora(), "evento": f"congelado; estimate {estimado} USD"})
        return reg
    e = entrada(escribe_registro(repo, congela, f"Higgsfield: intención congelada {op.id}"), op.id)
    if e["estado"] == "descartada":
        die(f"Con este estimate ({estimado} USD) se pasa el tope de Higgsfield del cliente ({pol['tope']}). No se pidió la foto.")
    return e


def _envia(repo: str, e: dict, ambiguo: bool) -> dict:
    """POST con la clave y el cuerpo congelados. Red/timeout/3xx/408/429/5xx: mismo POST, misma clave. Nunca una clave
    nueva. ambiguo: ya hubo un envío cuyo resultado no se sabe (otra corrida o un intento de esta): un 4xx posterior no
    prueba que no se aceptara, así que queda incierto y sigue contando contra el tope."""
    extra = {**e["encabezados"], "Idempotency-Key": e["idempotency_key"]}
    if _sha_cuerpo(e["endpoint"], e["cuerpo"], e["encabezados"]) != e.get("cuerpo_sha256"):
        die(f"El cuerpo registrado de {e['id']} no coincide con su huella. No se envía.")
    desde = ("listo", "incierto")
    ultimo = ""
    for i in range(1 + _num_env("HF_REINTENTOS_ENVIO", 2, 3)):
        try:
            r = llama("POST", API + e["endpoint"], e["cuerpo"], extra)
        except ErrorHF as err:
            if err.code >= 500 or err.code in (408, 429):  # no se sabe o no se aceptó todavía: mismo POST, misma clave
                ultimo, ambiguo = f"HTTP {err.code}", True
                time.sleep(float(os.environ.get("HF_ESPERA_S", "5")) * (i + 1))
                continue
            if err.code == 422 and "idempotency" in err.detalle.lower():
                _actualiza(repo, e["id"], f"Higgsfield: conflicto {e['id']}", solo_si=desde, estado="conflicto",
                           evento=f"422 Idempotency-Key con otros parámetros: {err.detalle[:120]}")
                die(f"Higgsfield dice que la clave de {e['id']} ya se usó con otros parámetros (422). No se crea otra clave: "
                    "revisar a mano si fue un error o una generación nueva deliberada.")
            if ambiguo:
                _actualiza(repo, e["id"], f"Higgsfield: incierto {e['id']}", solo_si=desde, estado="incierto",
                           evento=f"HTTP {err.code} después de un envío sin respuesta: {err.detalle[:100]}")
                die(f"Higgsfield respondió HTTP {err.code} después de un envío sin respuesta: no se sabe si el primero se aceptó. "
                    "Queda incierto (cuenta contra el tope); revisar a mano. No se pide otra foto.")
            _actualiza(repo, e["id"], f"Higgsfield: rechazada {e['id']}", solo_si=desde, estado="rechazada",
                       evento=f"HTTP {err.code} antes de aceptar: {err.detalle[:120]}")
            die(f"Higgsfield rechazó la solicitud antes de aceptarla (HTTP {err.code}: {err.detalle[:200]}). No se cobra; "
                "no se reintenta con otra clave.")
        except RedHF as err:
            ultimo, ambiguo = str(err), True
            time.sleep(float(os.environ.get("HF_ESPERA_S", "5")) * (i + 1))
            continue
        rid, status_url = r.get("request_id"), r.get("status_url")
        su = urlparse(str(status_url or ""))
        if not rid or su.scheme != urlparse(API).scheme or su.netloc != urlparse(API).netloc or su.path != f"/requests/{rid}/status":
            _actualiza(repo, e["id"], f"Higgsfield: respuesta rara {e['id']}", solo_si=desde, estado="incierto",
                       evento=f"aceptación sin request_id/status_url válidos: {json.dumps(r)[:120]}")
            die(f"Higgsfield no regresó request_id y status_url válidos ({json.dumps(r)[:200]}). Queda incierto; se retoma con "
                "la misma clave.")
        return _actualiza(repo, e["id"], f"Higgsfield: aceptada {e['id']}", solo_si=desde, estado="enviado", request_id=rid,
                          status_url=status_url, aceptado_en=ahora(), evento=f"aceptada: {rid}")
    _actualiza(repo, e["id"], f"Higgsfield: incierto {e['id']}", solo_si=desde, estado="incierto",
               evento=f"sin respuesta: {ultimo[:120]}")
    die(f"Sin respuesta de Higgsfield al enviar {e['id']} ({ultimo[:120]}). Resultado incierto: se retoma con la MISMA "
        "clave y el MISMO cuerpo en la próxima corrida; no se pide otra foto.")


def _continua(repo: str, pol: dict, op: Operacion, e: dict, reanudada: bool) -> Resultado:
    estado = e.get("estado")
    if estado in ("failed", "nsfw", "canceled", "conflicto", "rechazada", "descartada"):
        die(f"La operación {op.id} ya terminó en '{estado}' (request {e.get('request_id') or 'sin aceptar'}). No se pide otra "
            "foto: para una nueva hace falta una ronda Nueva aprobada.")
    if estado == "completed" and e.get("archivo"):
        return _resultado(repo, e, lee_archivo(repo, e["archivo"]["ruta"], e["archivo"]["sha256"]), True)
    if estado == "reservado":
        e = _congela(repo, pol, op, e, reanudada)
    if e.get("estado") in ("listo", "incierto") and not e.get("request_id"):
        if reanudada:  # otra corrida pudo enviar ya: solo se repite el MISMO POST dentro de la ventana
            ventana = _num_env("HF_VENTANA_REPLAY_H", 24, 168)
            desde = e.get("congelado_en") or e.get("estimado_en") or ""
            try:
                viejo = datetime.now(timezone.utc) - datetime.fromisoformat(desde) > timedelta(hours=ventana)
            except ValueError:
                viejo = True
            if viejo:
                die(f"La operación {op.id} quedó '{e.get('estado')}' hace más de {ventana} h sin request_id. No se repite el POST "
                    "(no se sabe cuánto dura la Idempotency-Key): confirmar a mano en Higgsfield y cerrar con "
                    "`higgsfield.py liberar`. No se pide otra foto.")
        e = _envia(repo, e, ambiguo=reanudada or e.get("estado") == "incierto")
    return _espera_y_guarda(repo, e, reanudada)


def _espera_y_guarda(repo: str, e: dict, reanudada: bool) -> Resultado:
    rid, status_url = e["request_id"], e["status_url"]
    vivos = ("enviado", "incierto")
    estado: dict = {}
    for _ in range(max(1, _num_env("HF_INTENTOS", 40, 400))):
        try:
            estado = llama("GET", status_url)
        except (ErrorHF, RedHF) as err:
            estado = {"status": None, "_error": str(err)[:120]}
        if estado.get("status") in TERMINALES:
            break
        time.sleep(float(os.environ.get("HF_ESPERA_S", "5")))
    st = estado.get("status")
    if st not in TERMINALES:
        _actualiza(repo, e["id"], f"Higgsfield: sigue en proceso {e['id']}", solo_si=vivos,
                   evento=f"sin terminar: {st or estado.get('_error')}")
        die(f"La foto (request {rid}) sigue en '{st or 'sin respuesta'}'. No se pide otra: se retoma ese mismo request en la "
            "próxima corrida.")
    if st != "completed":
        b = borra(rid)  # terminada: no hay por qué dejar sus datos
        _actualiza(repo, e["id"], f"Higgsfield: {st} {e['id']}", solo_si=vivos, estado=st, borrado=b,
                   limpieza="hecha" if b["ok"] else "pendiente",
                   cargo={"usd": "0", "calidad": "sin cobro según la documentación de Higgsfield (failed/nsfw/canceled)"},
                   evento=f"terminó en {st}: {str(estado.get('error') or '')[:100]}")
        die(f"La foto terminó en '{st}' (request {rid}). No se pide otra: termina y explícalo.")
    url = ((estado.get("images") or [{}])[0] or {}).get("url")
    try:
        if not url:
            raise ValueError("el estado completed no trae images[0].url")
        datos, tipo, host_final = baja(url)
        info = valida_imagen(datos, tipo)
    except Exception as err:  # noqa: BLE001
        _actualiza(repo, e["id"], f"Higgsfield: descarga fallida {e['id']}", solo_si=vivos, estado="enviado",
                   expires_at=estado.get("expires_at"), evento=f"completed; descarga o validación fallida: {str(err)[:120]}")
        die(f"La foto del request {rid} terminó, pero no se pudo bajar o no es una imagen válida ({str(err)[:160]}). No se pide "
            "otra: se retoma ese mismo request (antes de su expires_at) o se revisa a mano.")
    sha256 = hashlib.sha256(datos).hexdigest()
    ruta = f"{ARCHIVOS}{sha256}.{info['ext']}"
    archivo = {"ruta": ruta, "sha256": sha256, "sha1": hashlib.sha1(datos).hexdigest(), "blob_sha": blob_sha(datos),
               "bytes": len(datos), "mime": info["mime"], "ancho": info["ancho"], "alto": info["alto"],
               "imagen_host": urlparse(url).netloc, "imagen_host_final": host_final}
    # Copia propia ANTES del DELETE: si después se cae algo, la foto ya está en el registro del cliente.
    e = _actualiza(repo, e["id"], f"Higgsfield: foto guardada {e['id']}", {ruta: datos}, solo_si=vivos, estado="completed",
                   archivo=archivo, expires_at=estado.get("expires_at"),
                   cargo={"usd": e["estimado_usd"], "calidad": "estimate autenticado previo al envío; no es factura"},
                   evento=f"completed; copia propia {sha256[:12]}")
    if e.get("estado") != "completed" or not e.get("archivo"):
        die(f"El registro de {e['id']} cambió a '{e.get('estado')}' mientras se guardaba la foto. Se detiene aquí.")
    if e["archivo"]["sha256"] != sha256:  # otra corrida de la misma operación guardó antes: manda la suya
        datos = lee_archivo(repo, e["archivo"]["ruta"], e["archivo"]["sha256"])
    return _resultado(repo, e, datos, reanudada)


def _resultado(repo: str, e: dict, datos: bytes, reanudada: bool) -> Resultado:
    if not (e.get("borrado") or {}).get("ok"):
        b = borra(e["request_id"])
        e = _actualiza(repo, e["id"], f"Higgsfield: limpieza {e['id']}", solo_si=("completed",), borrado=b,
                       limpieza="hecha" if b["ok"] else "pendiente", evento=f"DELETE {'ok' if b['ok'] else 'fallido'}")
        if not b["ok"]:
            print(f"⚠ No se pudo borrar el request {e['request_id']} en Higgsfield ({b['error']}). Queda como limpieza pendiente "
                  f"en el registro; Higgsfield lo borra solo al vencer su retención ({e.get('expires_at') or '1 h tras terminar'}).")
    a = e["archivo"]
    meta = {"request_id": e["request_id"], "endpoint": e["endpoint"], **(e.get("meta_extra") or {}), "estado": "completed",
            "imagen_host": a["imagen_host"], "imagen_host_final": a.get("imagen_host_final"), "sha1": a["sha1"],
            "bytes": a["bytes"], "blob_sha": a["blob_sha"], "sha256": a["sha256"], "mime": a["mime"], "ancho": a["ancho"],
            "alto": a["alto"], "idempotency_key": e["idempotency_key"], "estimado_usd": e["estimado_usd"],
            "retencion_s": int(RETENCION_S), "expires_at": e.get("expires_at"), "borrado": e.get("borrado"),
            "registro": {"rama": RAMA, "entrada": e["id"], "fila": e.get("fila"), "archivo": a["ruta"]}}
    if e.get("subida"):
        meta["subida"] = {k: e["subida"][k] for k in ("host", "sha256", "retencion", "limpieza") if k in e["subida"]}
    if e.get("tipo") == "editar":
        meta["input_sha256"] = e.get("entrada_sha256")
    pedida = (e.get("cuerpo") or {}).get("aspect_ratio")
    if pedida:  # aviso, no bloqueo: la foto ya se pagó; el encuadre lo resuelve object-fit o el marco de Canva
        w, h = (int(x) for x in pedida.split(":"))
        if abs((a["ancho"] / a["alto"]) / (w / h) - 1) > 0.05:
            meta["aviso_encuadre"] = f"pedida {pedida}, llegó {a['ancho']}x{a['alto']}"
    return Resultado(datos=datos, ext=FIRMAS[a["mime"]], prompt=e["cuerpo"]["prompt"], meta=meta, reanudada=reanudada)


# ------------------------------------------------------------------ uso humano (no lo corre el agente)
def cli() -> None:
    """Para personas (Al, Bonzo) con un GITHUB_TOKEN con escritura en el repo de piezas del cliente. Nunca llama a Higgsfield.
      iniciar: crea el registro vacío del cliente (una vez). No lo recrea si existe.
      estado:  imprime las operaciones y lo reservado/consumido contra el tope.
      liberar: cierra a mano una operación que no se envió (reservado) o, con --confirmo-sin-aceptar y el motivo, una
               listo/incierto sin request_id después de comprobar en Higgsfield que no se aceptó. Queda en el historial."""
    ap = argparse.ArgumentParser(description=cli.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("accion", choices=("iniciar", "estado", "liberar"))
    ap.add_argument("--repo", required=True)
    ap.add_argument("--operacion")
    ap.add_argument("--motivo")
    ap.add_argument("--confirmo-sin-aceptar", action="store_true")
    a = ap.parse_args()
    if a.accion == "iniciar":
        r = _g("GET", f"/repos/{a.repo}/git/ref/heads/{RAMA}", ok=(404,))
        if r.get("_status") != 404:
            die(f"{a.repo} ya tiene la rama {RAMA}: no se recrea.")
        datos = (json.dumps({"version": 1, "repo": a.repo, "entradas": [], "creado_en": ahora()}, indent=1, sort_keys=True) + "\n").encode()
        blob = _g("POST", f"/repos/{a.repo}/git/blobs", {"content": base64.b64encode(datos).decode(), "encoding": "base64"})["sha"]
        arbol = _g("POST", f"/repos/{a.repo}/git/trees", {"tree": [{"path": RUTA, "mode": "100644", "type": "blob", "sha": blob}]})["sha"]
        commit = _g("POST", f"/repos/{a.repo}/git/commits", {"message": "Higgsfield: registro del cliente", "tree": arbol, "parents": []})["sha"]
        r = _g("POST", f"/repos/{a.repo}/git/refs", {"ref": f"refs/heads/{RAMA}", "sha": commit}, ok=(422,))
        if "_status" in r:
            die(f"{a.repo} ya tiene la rama {RAMA}: no se recrea.")
        print(json.dumps({"repo": a.repo, "rama": RAMA, "commit": commit}))
        return
    if a.accion == "estado":
        head, reg = lee_registro(a.repo)
        filas = [{k: x.get(k) for k in ("id", "fila", "estado", "estimado_usd", "cota_usd", "request_id", "limpieza")}
                 for x in reg["entradas"]]
        print(json.dumps({"repo": a.repo, "punta": head, "expuesto_usd": str(expuesto(reg)), "operaciones": filas},
                         ensure_ascii=False, indent=1))
        return
    if not a.operacion or not (a.motivo or "").strip():
        die("liberar necesita --operacion y --motivo.")
    permitidos = ("reservado", "listo", "incierto") if a.confirmo_sin_aceptar else ("reservado",)

    def libera(reg):
        x = entrada(reg, a.operacion)
        if x is None:
            die(f"No existe la operación {a.operacion}.")
        if x.get("estado") not in permitidos or x.get("request_id"):
            die(f"{a.operacion} está '{x.get('estado')}'{' con request ' + x['request_id'] if x.get('request_id') else ''}: no se "
                "libera así (listo o incierto solo con --confirmo-sin-aceptar; con request_id, nunca).")
        x["estado"] = "descartada"
        x.setdefault("historial", []).append({"en": ahora(), "evento": f"liberada a mano: {a.motivo.strip()[:200]}"})
        return reg
    escribe_registro(a.repo, libera, f"Higgsfield: liberada a mano {a.operacion}")
    print(f"✓ {a.operacion} liberada (descartada) en {a.repo}.")


if __name__ == "__main__":
    cli()
