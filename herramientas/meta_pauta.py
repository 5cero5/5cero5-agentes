#!/usr/bin/env python3
"""Herramienta del agente Pauta: arma UNA campaña de Meta, siempre EN PAUSA, con piezas ya aprobadas de 5cero5-piezas.

Comandos (en orden):
  cuenta      Lee la cuenta publicitaria y la página: existe, está activa, es en MXN y tiene límite de gasto.
  plan        Valida un plan.json (nombre, presupuesto contra el tope, público, destino, textos y piezas aprobadas)
              y lo deja listo en <trabajo>/<nombre>/plan.json.
  crear       Crea campaña, conjunto, imágenes, creativos y anuncios. Todo con status PAUSED.
  comprobar   Lee de regreso en Meta lo creado y lo imprime como JSON. Falla si algo no está en pausa.

Lo que se impone aquí (no depende del prompt):
  - Solo escribe en /act_<cuenta>/{campaigns,adsets,ads,adcreatives,adimages} de la cuenta que se le da. Nada más.
  - Toda campaña, conjunto y anuncio se manda con status PAUSED. No hay forma de mandar otro status: no activa, no
    borra, no edita nada que ya exista.
  - El presupuesto diario no pasa del tope (--tope-mxn). El destino es https y de un dominio permitido.
  - Solo piezas de 5cero5-piezas (main) con informe del Verificador aprobado y del mismo PNG.
  - META_TOKEN solo viaja en el encabezado Authorization hacia la Graph API (lo sustituye el vault de la sesión).
Variables: META_TOKEN; META_API_BASE solo para pruebas.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

VERSION_API = "v25.0"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
NOMBRE = re.compile(r"^\d{4}-\d{2}_[a-z0-9][a-z0-9-]{1,20}_[a-z0-9][a-z0-9-]{1,40}$")      # utm_campaign: AAAA-MM_zona_angulo
CONJUNTO = re.compile(r"^[a-z0-9][a-z0-9-]{1,20}_[a-z0-9][a-z0-9-]{1,40}$")             # utm_term: zona_publico
ANUNCIO = re.compile(r"^a\d{2}_[a-z0-9][a-z0-9-]{1,20}_[a-z0-9][a-z0-9-]{1,40}$")       # utm_content: a##_formato_gancho
URL_TAGS = "utm_source=meta&utm_medium=paid_social&utm_campaign={{campaign.name}}&utm_content={{ad.name}}&utm_term={{adset.name}}"
BOTONES = {"LEARN_MORE", "SIGN_UP", "CONTACT_US", "GET_QUOTE", "BOOK_NOW"}
OBJETIVOS = {
    # objetivo -> (objective de campaña, optimization_goal del conjunto)
    "trafico": ("OUTCOME_TRAFFIC", "LINK_CLICKS"),
    "clientes_potenciales": ("OUTCOME_LEADS", "OFFSITE_CONVERSIONS"),
}
ESCRITURA = re.compile(r"^/(act_\d+)/(campaigns|adsets|ads|adcreatives|adimages)$")
CON_STATUS = {"campaigns", "adsets", "ads"}
MX = timezone(timedelta(hours=-6))  # México centro, sin horario de verano desde 2022
MAX_ANUNCIOS = 6


def die(m: str) -> None:
    print(f"\n✗ {m}")
    sys.exit(1)


def api() -> str:
    return os.environ.get("META_API_BASE", f"https://graph.facebook.com/{VERSION_API}").rstrip("/")


def token() -> str:
    t = os.environ.get("META_TOKEN", "").strip()
    if not t:
        die("Falta META_TOKEN.")
    return t


def _pide(req: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            t = r.read()
            return json.loads(t) if t else {}
    except urllib.error.HTTPError as e:
        cuerpo = e.read()[:600].decode("utf-8", "ignore")
        try:
            err = json.loads(cuerpo).get("error", {})
            detalle = f"{err.get('message', '')} (code {err.get('code')}, subcode {err.get('error_subcode')}) {err.get('error_user_msg', '')}".strip()
        except Exception:
            detalle = cuerpo
        die(f"Meta respondió {e.code} a {req.get_method()} {urllib.parse.urlsplit(req.full_url).path}: {detalle}")


def meta_get(path: str, params: dict | None = None) -> dict:
    q = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in (params or {}).items()})
    return _pide(urllib.request.Request(api() + path + (f"?{q}" if q else ""), method="GET",
                                        headers={"Authorization": f"Bearer {token()}", "User-Agent": "5cero5-pauta"}))


def meta_post(cuenta: str, path: str, data: dict) -> dict:
    """La ÚNICA salida de escritura. Solo crea en la cuenta dada y solo en pausa."""
    m = ESCRITURA.match(path)
    if not m or m.group(1) != cuenta:
        die(f"Escritura no permitida: {path}")
    if m.group(2) in CON_STATUS:
        if data.get("status") != "PAUSED":
            die(f"{m.group(2)} sin status PAUSED: no se manda")
    elif "status" in data:
        die(f"{m.group(2)} no lleva status")
    cuerpo = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in data.items()}).encode()
    return _pide(urllib.request.Request(api() + path, method="POST", data=cuerpo,
                                        headers={"Authorization": f"Bearer {token()}", "User-Agent": "5cero5-pauta",
                                                 "Content-Type": "application/x-www-form-urlencoded"}))


def cuenta_id(v: str) -> str:
    v = str(v or "").strip()
    v = v if v.startswith("act_") else f"act_{v}"
    if not re.fullmatch(r"act_\d{5,20}", v):
        die(f"--cuenta inválida: {v!r}")
    return v


def lee_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"No existe {p}")
    except json.JSONDecodeError as e:
        die(f"{p} no es JSON válido: {e}")


def escribe_json(p: Path, d: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def huella(d: dict) -> str:
    return hashlib.sha1(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ---------- cuenta ----------

def cmd_cuenta(a) -> None:
    cta = cuenta_id(a.cuenta)
    c = meta_get(f"/{cta}", {"fields": "name,currency,timezone_name,account_status,disable_reason,spend_cap,amount_spent"})
    p = meta_get(f"/{a.pagina}", {"fields": "name"})
    problemas = []
    if c.get("account_status") != 1:
        problemas.append(f"la cuenta no está activa (account_status {c.get('account_status')}, disable_reason {c.get('disable_reason')})")
    if c.get("currency") != "MXN":
        problemas.append(f"la cuenta es en {c.get('currency')}, no en MXN")
    avisos = []
    if not int(c.get("spend_cap") or 0):
        avisos.append("la cuenta no tiene límite de gasto (spend_cap): ponlo en Facturación antes de encender")
    out = {"cuenta": cta, "nombre": c.get("name"), "moneda": c.get("currency"), "zona": c.get("timezone_name"),
           "limite_mxn": int(c.get("spend_cap") or 0) / 100, "gastado_mxn": int(c.get("amount_spent") or 0) / 100,
           "pagina": a.pagina, "pagina_nombre": p.get("name"), "problemas": problemas, "avisos": avisos}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if problemas:
        die("La cuenta no sirve para crear campañas: " + "; ".join(problemas))


# ---------- plan ----------

def fecha(s, campo: str) -> date | None:
    if s in (None, ""):
        return None
    try:
        return date.fromisoformat(str(s))
    except ValueError:
        die(f"{campo} debe ser AAAA-MM-DD, no {s!r}")


def valida_texto(v, campo: str, maximo: int, obligatorio: bool = True) -> str:
    v = str(v or "").strip()
    if obligatorio and not v:
        die(f"Falta {campo}")
    if len(v) > maximo:
        die(f"{campo} tiene {len(v)} caracteres; el máximo es {maximo}")
    if "!" in v or "¡" in v:
        die(f"{campo} lleva signos de exclamación (reglas de marca)")
    return v


def pieza_aprobada(raiz: Path, carpeta: str, pieza: str) -> dict:
    d = raiz / "piezas" / carpeta / pieza
    png = d / "pieza.png"
    if not png.is_file():
        die(f"No existe piezas/{carpeta}/{pieza}/pieza.png en 5cero5-piezas (main). ¿Ya se fusionó su PR?")
    inf = lee_json(d / "informe.json")
    meta = lee_json(d / "pieza.json")
    b = png.read_bytes()
    if inf.get("aprobada") is not True:
        die(f"piezas/{carpeta}/{pieza}: el informe del Verificador no está aprobado")
    if inf.get("png_sha1") != hashlib.sha1(b).hexdigest():
        die(f"piezas/{carpeta}/{pieza}: el informe del Verificador es de otro PNG")
    if meta.get("campana") != carpeta or meta.get("pieza") != pieza:
        die(f"piezas/{carpeta}/{pieza}: pieza.json es de otra campaña o pieza")
    return {"pieza": pieza, "formato": meta.get("formato"), "png": str(png), "png_sha1": hashlib.sha1(b).hexdigest()}


def cmd_plan(a) -> None:
    p = lee_json(Path(a.archivo))
    dominios = {d.strip().lower() for d in a.dominios.split(",") if d.strip()}
    nombre = str(p.get("nombre", ""))
    if not NOMBRE.match(nombre):
        die(f"nombre {nombre!r} no sigue AAAA-MM_zona_angulo (minúsculas, números y guiones)")
    carpeta = str(p.get("carpeta_piezas", ""))
    if not SLUG.match(carpeta):
        die(f"carpeta_piezas {carpeta!r} inválida")
    objetivo = p.get("objetivo")
    if objetivo not in OBJETIVOS:
        die(f"objetivo debe ser uno de {sorted(OBJETIVOS)}")
    if objetivo == "clientes_potenciales" and not a.pixel:
        die("clientes_potenciales necesita el Pixel (--pixel). Sin Pixel, usa trafico.")
    try:
        ppto = float(p.get("presupuesto_diario_mxn"))
    except (TypeError, ValueError):
        die("presupuesto_diario_mxn debe ser un número")
    if not 50 <= ppto <= a.tope_mxn:
        die(f"presupuesto_diario_mxn {ppto:g} fuera de rango: de 50 a {a.tope_mxn:g} MXN (tope)")
    hoy = datetime.now(MX).date()
    ini, fin = fecha(p.get("inicio"), "inicio"), fecha(p.get("fin"), "fin")
    if ini and ini < hoy:
        die(f"inicio {ini} ya pasó")
    if fin and fin <= (ini or hoy):
        die("fin debe ser después de inicio")
    pub = p.get("publico") or {}
    if not CONJUNTO.match(str(pub.get("nombre", ""))):
        die("publico.nombre debe ser zona_publico (por ejemplo mty_duenos-pyme)")
    ub = pub.get("ubicacion") or {}
    if ub.get("tipo") == "pais":
        if ub.get("pais") != "MX":
            die("Solo México (pais MX)")
        geo = {"countries": ["MX"]}
    elif ub.get("tipo") == "radio":
        lat, lng, km = (float(ub.get(k, "nan")) for k in ("lat", "lng", "radio_km"))
        if not (14 <= lat <= 33 and -118 <= lng <= -86):
            die("La ubicación tiene que estar en México")
        if not 1 <= km <= 80:
            die("radio_km de 1 a 80")
        geo = {"custom_locations": [{"latitude": lat, "longitude": lng, "radius": km, "distance_unit": "kilometer"}]}
    else:
        die('publico.ubicacion: {"tipo":"pais","pais":"MX"} o {"tipo":"radio","lat":..,"lng":..,"radio_km":..}')
    emin, emax = int(pub.get("edad_min", 18)), int(pub.get("edad_max", 65))
    if not 18 <= emin < emax <= 65:
        die("edades de 18 a 65, edad_min menor que edad_max")
    destino = str(p.get("destino", ""))
    u = urllib.parse.urlsplit(destino)
    if u.scheme != "https" or (u.hostname or "").lower() not in dominios:
        die(f"destino debe ser https y de {sorted(dominios)}")
    if u.query or u.fragment:
        die("destino sin parámetros: las UTM las pone Meta (url_tags)")
    boton = p.get("boton", "LEARN_MORE")
    if boton not in BOTONES:
        die(f"boton debe ser uno de {sorted(BOTONES)}")
    anuncios = p.get("anuncios") or []
    if not 1 <= len(anuncios) <= MAX_ANUNCIOS:
        die(f"De 1 a {MAX_ANUNCIOS} anuncios")
    vistos, listos = set(), []
    for x in anuncios:
        n, pz = str(x.get("nombre", "")), str(x.get("pieza", ""))
        if not ANUNCIO.match(n):
            die(f"anuncio {n!r} no sigue a##_formato_gancho")
        if not SLUG.match(pz):
            die(f"pieza {pz!r} inválida")
        if n in vistos:
            die(f"anuncio repetido: {n}")
        vistos.add(n)
        listos.append({"nombre": n, **pieza_aprobada(Path(a.piezas), carpeta, pz)})
    plan = {
        "nombre": nombre, "carpeta_piezas": carpeta, "objetivo": objetivo, "presupuesto_diario_mxn": ppto,
        "inicio": ini.isoformat() if ini else None, "fin": fin.isoformat() if fin else None,
        "publico": {"nombre": pub["nombre"], "geo": geo, "edad_min": emin, "edad_max": emax},
        "destino": destino, "boton": boton,
        "texto": valida_texto(p.get("texto"), "texto", 600),
        "titulo": valida_texto(p.get("titulo"), "titulo", 60),
        "descripcion": valida_texto(p.get("descripcion"), "descripcion", 60, obligatorio=False),
        "anuncios": listos,
        "cuenta": cuenta_id(a.cuenta), "pagina": a.pagina, "ig": a.ig or None, "pixel": a.pixel or None,
    }
    plan["huella"] = huella({k: v for k, v in plan.items() if k != "huella"})
    escribe_json(Path(a.trabajo) / nombre / "plan.json", plan)
    print(json.dumps({"plan": f"{a.trabajo}/{nombre}/plan.json", "anuncios": len(listos), "presupuesto_diario_mxn": ppto,
                      "objetivo": objetivo}, ensure_ascii=False))


# ---------- crear ----------

def cuando(d: str | None, fin: bool = False) -> str | None:
    if not d:
        return None
    t = datetime.fromisoformat(d).replace(hour=23 if fin else 0, minute=59 if fin else 0, tzinfo=MX)
    return t.isoformat()


def carga_plan(a) -> tuple[Path, dict]:
    d = Path(a.trabajo) / a.nombre
    plan = lee_json(d / "plan.json")
    if plan.get("huella") != huella({k: v for k, v in plan.items() if k != "huella"}):
        die("plan.json cambió después de validarlo: corre plan otra vez")
    if plan["cuenta"] != cuenta_id(a.cuenta):
        die("El plan es de otra cuenta")
    return d, plan


def cmd_crear(a) -> None:
    d, plan = carga_plan(a)
    cta = plan["cuenta"]
    res_p = d / "resultado.json"
    if res_p.exists():
        die(f"Ya se creó algo para {a.nombre} (resultado.json). No se crea otra vez: usa comprobar.")
    ya = meta_get(f"/{cta}/campaigns", {"fields": "id,name,status",
                                         "filtering": [{"field": "name", "operator": "EQUAL", "value": plan["nombre"]}], "limit": 5})
    if ya.get("data"):
        die(f"Ya existe una campaña llamada {plan['nombre']} en la cuenta ({ya['data'][0].get('id')}). No se duplica.")
    res = {"nombre": plan["nombre"], "cuenta": cta, "anuncios": []}
    guarda = lambda: escribe_json(res_p, res)  # noqa: E731  progreso: si algo falla a medias, se sabe qué quedó creado
    objective, goal = OBJETIVOS[plan["objetivo"]]

    c = meta_post(cta, f"/{cta}/campaigns", {
        "name": plan["nombre"], "objective": objective, "status": "PAUSED", "special_ad_categories": [],
        "buying_type": "AUCTION", "is_adset_budget_sharing_enabled": "false"})
    res["campana_meta_id"] = c["id"]
    guarda()
    print(f"✓ campaña {c['id']} en pausa")

    targeting = {**plan["publico"]["geo"], "age_min": plan["publico"]["edad_min"], "age_max": plan["publico"]["edad_max"],
                 "targeting_automation": {"advantage_audience": 0}}
    conj = {"name": plan["publico"]["nombre"], "campaign_id": c["id"], "status": "PAUSED",
            "daily_budget": int(round(plan["presupuesto_diario_mxn"] * 100)), "billing_event": "IMPRESSIONS",
            "optimization_goal": goal, "bid_strategy": "LOWEST_COST_WITHOUT_CAP", "destination_type": "WEBSITE",
            "targeting": targeting}
    if plan["objetivo"] == "clientes_potenciales":
        conj["promoted_object"] = {"pixel_id": plan["pixel"], "custom_event_type": "LEAD"}
    if plan.get("inicio"):
        conj["start_time"] = cuando(plan["inicio"])
    if plan.get("fin"):
        conj["end_time"] = cuando(plan["fin"], fin=True)
    s = meta_post(cta, f"/{cta}/adsets", conj)
    res["conjunto_id"] = s["id"]
    guarda()
    print(f"✓ conjunto {s['id']} en pausa, {plan['presupuesto_diario_mxn']:g} MXN al día")

    for x in plan["anuncios"]:
        b = Path(x["png"]).read_bytes()
        if hashlib.sha1(b).hexdigest() != x["png_sha1"]:
            die(f"{x['png']} cambió después de validar el plan")
        img = meta_post(cta, f"/{cta}/adimages", {"bytes": base64.b64encode(b).decode(), "name": f"{plan['carpeta_piezas']}-{x['pieza']}.png"})
        h = next(iter((img.get("images") or {}).values()), {}).get("hash")
        if not h:
            die(f"Meta no regresó el hash de la imagen de {x['pieza']}")
        link = {"link": plan["destino"], "message": plan["texto"], "name": plan["titulo"], "image_hash": h,
                "call_to_action": {"type": plan["boton"], "value": {"link": plan["destino"]}}}
        if plan.get("descripcion"):
            link["description"] = plan["descripcion"]
        spec = {"page_id": plan["pagina"], "link_data": link}
        if plan.get("ig"):
            spec["instagram_user_id"] = plan["ig"]
        cr = meta_post(cta, f"/{cta}/adcreatives", {"name": x["nombre"], "object_story_spec": spec, "url_tags": URL_TAGS})
        ad = meta_post(cta, f"/{cta}/ads", {"name": x["nombre"], "adset_id": s["id"], "creative": {"creative_id": cr["id"]}, "status": "PAUSED"})
        res["anuncios"].append({"id": ad["id"], "nombre": x["nombre"], "pieza": x["pieza"], "creativo_id": cr["id"], "imagen_hash": h})
        guarda()
        print(f"✓ anuncio {x['nombre']} ({ad['id']}) en pausa")
    res["completa"] = True
    guarda()
    print(f"\nListo: {len(res['anuncios'])} anuncio(s), todo en pausa. Sigue: comprobar --nombre {plan['nombre']}")


# ---------- comprobar ----------

def cmd_comprobar(a) -> None:
    d, plan = carga_plan(a)
    res = lee_json(d / "resultado.json")
    if not res.get("campana_meta_id"):
        die("resultado.json no tiene campaña")
    cid = res["campana_meta_id"]
    c = meta_get(f"/{cid}", {"fields": "id,name,status,effective_status,objective,account_id"})
    conj = meta_get(f"/{cid}/adsets", {"fields": "id,name,status,effective_status,daily_budget,lifetime_budget", "limit": 50}).get("data", [])
    ads = meta_get(f"/{cid}/ads", {"fields": "id,name,status,effective_status", "limit": 50}).get("data", [])
    problemas = []
    if f"act_{c.get('account_id')}" != plan["cuenta"]:
        problemas.append("la campaña es de otra cuenta")
    if c.get("name") != plan["nombre"]:
        problemas.append(f"la campaña se llama {c.get('name')}")
    for tipo, lista in (("campaña", [c]), ("conjunto", conj), ("anuncio", ads)):
        for e in lista:
            if e.get("status") != "PAUSED":
                problemas.append(f"{tipo} {e.get('id')} con status {e.get('status')}")
    if len(conj) != 1:
        problemas.append(f"{len(conj)} conjuntos (se esperaba 1)")
    for s in conj:
        if int(s.get("daily_budget") or 0) > round(plan["presupuesto_diario_mxn"] * 100) or int(s.get("lifetime_budget") or 0):
            problemas.append(f"presupuesto del conjunto {s.get('id')} distinto del plan")
    if sorted(x["id"] for x in ads) != sorted(x["id"] for x in res["anuncios"]):
        problemas.append("los anuncios en Meta no son los creados")
    if not res.get("completa"):
        problemas.append("la creación quedó a medias")
    out = {"campana_meta_id": cid, "nombre": plan["nombre"], "cuenta": plan["cuenta"], "conjunto_id": res.get("conjunto_id"),
           "anuncios": [{k: x[k] for k in ("id", "nombre", "pieza")} for x in res["anuncios"]],
           "presupuesto_diario_mxn": plan["presupuesto_diario_mxn"], "objetivo": plan["objetivo"],
           "estado": "PAUSED" if not problemas else "REVISAR", "problemas": problemas}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if problemas:
        die("La comprobación encontró problemas: " + "; ".join(problemas))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trabajo", default="/tmp/pauta")
    ap.add_argument("--piezas", default="/workspace/piezas", help="repo 5cero5-piezas montado (main)")
    ap.add_argument("--cuenta", required=True, help="cuenta publicitaria (act_...)")
    ap.add_argument("--pagina", required=True, help="id de la página de Facebook")
    ap.add_argument("--ig", default="", help="id de la cuenta de Instagram (opcional)")
    ap.add_argument("--pixel", default="", help="id del Pixel (opcional; sin él solo trafico)")
    ap.add_argument("--tope-mxn", type=float, required=True, help="presupuesto diario máximo por campaña")
    ap.add_argument("--dominios", default="marketing.5cero5.com", help="dominios permitidos para el destino, separados por coma")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("cuenta")
    p = sub.add_parser("plan")
    p.add_argument("--archivo", required=True)
    for n in ("crear", "comprobar"):
        sub.add_parser(n).add_argument("--nombre", required=True)
    a = ap.parse_args()
    if not str(a.pagina).isdigit():
        die("--pagina debe ser el id numérico de la página")
    if a.ig and not str(a.ig).isdigit():
        die("--ig debe ser numérico")
    if a.pixel and not str(a.pixel).isdigit():
        die("--pixel debe ser numérico")
    if getattr(a, "nombre", None) and not NOMBRE.match(a.nombre):
        die("--nombre inválido")
    {"cuenta": cmd_cuenta, "plan": cmd_plan, "crear": cmd_crear, "comprobar": cmd_comprobar}[a.cmd](a)


if __name__ == "__main__":
    main()
