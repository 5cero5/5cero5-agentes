"""Piezas del Creativo hechas en Canva (las usa pr_pieza.py; el agente no llama a este módulo directo).

El diseño lo hace el agente con el MCP oficial de Canva (copia de un diseño base aprobado del cliente, cambia SOLO los textos,
guarda, relee y exporta en PNG). Esta herramienta pone lo que pasa a GitHub y lo revisa; nunca habla con Canva con credenciales:

  pp nueva --campana c --pieza p --formato post-4x5 --canva    pieza.json con la base aprobada de canva/recursos.json
  pp canva-importar --campana c --pieza p --design DAG… --edit-url https://www.canva.com/design/DAG…/edit
                    --export-url <URL de export-design> --lectura lectura.json --elementos '{"kicker":"PB…-LB…", …}'
  pp revisar --campana c --pieza p     Verificador de marca para Canva (verificar_canva.py del repo de marca), sin HTML
  pp abrir ...                         igual que siempre (sube pieza.png, canva.json, copia.json, pieza.json, informe.json)
  pp revisar-pr ... --foto-ronda Igual --cambios cambios.json     ronda: mismo diseño y mismo PR, en dos pasos

Lo que se impone:
  - Solo bases de canva/recursos.json del repo de marca montado, con habilitado=true. Una pieza = un diseño.
  - pieza.png es la exportación ORIGINAL de Canva, byte a byte (el harness la vuelve a bajar y la coteja al cerrar).
  - La descarga va sin credenciales, solo https a los hosts de exportación de Canva (harness/agentes/canva.json o
    CANVA_EXPORT_HOSTS), sin redirecciones y con tope de 15 MB. No se fabrica pieza.html.
  - Canva con foto todavía no: la pieza va sin foto y una ronda solo con Foto en la ronda = Igual.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gh_pr import blob_sha, commit_en_rama, die, lee_carpeta  # noqa: E402

DISENO = re.compile(r"^D[A-Za-z0-9_-]{10}$")
LOCATOR = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
ROLES = ("kicker", "titular", "subtitulo", "nota")
SUBE = ("pieza.png", "canva.json", "copia.json", "pieza.json", "informe.json")
MAX = 15 * 1024 * 1024
UA = "5cero5-agente-creativo"
_CFG = Path(__file__).resolve().parent.parent / "harness" / "agentes" / "canva.json"


def hosts_export() -> list[str]:
    extra = [h.strip().lower() for h in os.environ.get("CANVA_EXPORT_HOSTS", "").split(",") if h.strip()]
    if extra:
        return extra
    try:
        return [h.lower() for h in json.loads(_CFG.read_text(encoding="utf-8"))["hosts_export"]]
    except (OSError, KeyError, json.JSONDecodeError):
        return ["export-download.canva.com"]


def _lee(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"Falta {p.name} en {p.parent}.")
    except json.JSONDecodeError as e:
        die(f"{p.name} no es JSON válido: {e}")


def _escribe(p: Path, d) -> None:
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def es_canva(d: Path) -> bool:
    try:
        return json.loads((d / "pieza.json").read_text(encoding="utf-8")).get("fuente") == "canva"
    except (OSError, json.JSONDecodeError):
        return False


def recursos(marca: Path, formato: str) -> dict:
    """La base aprobada del formato en canva/recursos.json del repo de marca montado (el de ESTE cliente)."""
    p = marca / "canva" / "recursos.json"
    if not p.exists():
        die("El repo de marca no tiene canva/recursos.json: este cliente no tiene recursos de Canva aprobados. Termina sin PR y explícalo.")
    r = _lee(p)
    if r.get("habilitado") is not True:
        die("canva/recursos.json no está habilitado (faltan recursos aprobados). Termina sin PR y explícalo.")
    f = (r.get("formatos") or {}).get(formato) or {}
    base = f.get("base") or {}
    if base.get("tipo") not in ("design", "brand_template") or not base.get("id") or (base["tipo"] == "design" and not DISENO.match(base["id"])):
        die(f"canva/recursos.json no tiene base aprobada para {formato}. Termina sin PR y explícalo.")
    return {"base": {"tipo": base["tipo"], "id": base["id"]}, "textos": f.get("textos") or {}, "carpeta": r.get("carpeta_id"),
            "logo": r.get("logo_asset_id"), "brand_kit": r.get("brand_kit_id") or None}


def nueva(a, d: Path) -> None:
    if a.foto:
        die("Canva con foto todavía no está habilitado: la pieza va sin foto. Termina sin PR y explícalo si el brief la exige.")
    marca = Path(a.marca)
    rec = recursos(marca, a.formato)
    d.mkdir(parents=True)
    _escribe(d / "copia.json", {"kicker": "", "titular": ["", "", ""], "subtitulo": "", "nota": ""})
    version = (marca / "VERSION").read_text().strip() if (marca / "VERSION").exists() else "?"
    _escribe(d / "pieza.json", {"campana": a.campana, "pieza": a.pieza, "formato": a.formato, "foto": False, "fuente": "canva",
                                "marca_version": version, "canva": {"base": rec["base"], "design_id": None}, "higgsfield": None})
    b = rec["base"]
    print(f"✓ {a.campana}/{a.pieza}: {a.formato} en Canva desde la base {b['tipo']}:{b['id']} (marca v{version}).")
    print(f"  1. Escribe la copia en {d / 'copia.json'} (mismas reglas; titular: lista de líneas).")
    print(f"  2. Canva: {'copy-design con design_id=' + b['id'] if b['tipo'] == 'design' else 'create-design-from-brand-template con brand_template_id=' + b['id']}"
          " (una vez). Del resultado sale el design_id nuevo y su enlace de edición.")
    print("  3. read-design con open_transaction=true → identifica cada texto por su texto de muestra:")
    for rol, t in rec["textos"].items():
        print(f"       {rol}: \"{t}\"")
    print("     edit-design: replace_text de cada rol con su copia (kicker vacío → delete_element) y luego finalize=commit.")
    print("  4. read-design con open_transaction=true (transacción NUEVA, después del commit) → guarda ese resultado en un archivo (lectura.json),")
    print("     confirma que quedó la copia y cierra esa transacción con edit-design finalize=cancel. Sin transacción Canva solo da texto plano.")
    print(f"  5. export-design en png al tamaño del formato; move-item-to-folder a la carpeta {rec['carpeta']}.")
    print("  6. pp canva-importar ... y luego pp revisar y pp abrir.")


def _baja(url: str) -> tuple[bytes, str]:
    u = urlparse(url)
    hosts = hosts_export()
    # Solo pruebas (test_pieza_canva.py): http a 127.0.0.1. No abre nada real: el harness vuelve a bajar la exportación de Canva y
    # la compara byte a byte con pieza.png al cerrar.
    prueba = os.environ.get("CANVA_EXPORT_PRUEBA") == "1" and u.scheme == "http" and u.hostname == "127.0.0.1"
    if not prueba and (u.scheme != "https" or (u.hostname or "").lower() not in hosts):
        die(f"La exportación viene de {u.hostname or '?'}, que no está entre los hosts de Canva permitidos ({', '.join(hosts)}). "
            "No se baja. Si Canva cambió de host, se agrega a harness/agentes/canva.json y a la red del entorno; termina y explícalo.")

    class _Sin(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.HTTPError(req.full_url, code, f"redirección a {urlparse(newurl).hostname}", headers, fp)
    try:
        with urllib.request.build_opener(_Sin()).open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
            datos = r.read(MAX + 1)
    except Exception as e:  # noqa: BLE001
        die(f"No pude bajar la exportación de Canva de {u.hostname} ({e}). No se reintenta con otra URL: vuelve a exportar una vez o termina.")
    if len(datos) > MAX:
        die("La exportación pesa más de 15 MB.")
    if not datos.startswith(b"\x89PNG\r\n\x1a\n"):
        die("Lo que bajó no es un PNG: exporta con format.type = png.")
    return datos, u.hostname or ""


def importar(a, d: Path) -> None:
    if not es_canva(d):
        die("Esta pieza no es de Canva (créala con 'nueva --canva').")
    meta = _lee(d / "pieza.json")
    design = (a.design or "").strip()
    if not DISENO.match(design):
        die(f"--design inválido: {design!r} (un id de diseño de Canva: D y 10 caracteres).")
    previo = (meta.get("canva") or {}).get("design_id")
    if previo and previo != design:
        die(f"Esta pieza ya es el diseño {previo}: una pieza = un diseño (en una ronda se edita el mismo).")
    edit = (a.edit_url or "").strip()
    eu = urlparse(edit)
    if eu.scheme != "https" or eu.hostname != "www.canva.com" or not eu.path.startswith(f"/design/{design}/"):
        die("--edit-url tiene que ser el enlace de edición de ese diseño: https://www.canva.com/design/<id>/…")
    try:
        elementos = json.loads(a.elementos or "{}")
    except json.JSONDecodeError:
        die("--elementos no es JSON: {\"kicker\": \"<locator>\", ...}")
    if not isinstance(elementos, dict) or [k for k in elementos if k not in ROLES] or not all(isinstance(v, str) and LOCATOR.match(v) for v in elementos.values()):
        die(f"--elementos lleva solo {', '.join(ROLES)} con el locator de cada texto en Canva.")
    copia = _lee(d / "copia.json")
    faltan = [r for r in ROLES if str(copia.get(r, "") if not isinstance(copia.get(r), list) else " ".join(copia[r])).strip() and r not in elementos]
    if faltan:
        die(f"Falta el elemento de Canva de: {', '.join(faltan)} (cada texto con copia va en su propio elemento).")
    lectura = Path(a.lectura)
    if not lectura.is_file() or lectura.stat().st_size > MAX:
        die("--lectura: el archivo con el resultado de read-design del diseño guardado (transacción nueva después del commit).")
    datos, host = _baja(a.export_url)
    from PIL import Image  # noqa: WPS433 — Pillow ya está en el entorno (lo usa el Verificador)
    import io
    medidas = list(Image.open(io.BytesIO(datos)).size)
    (d / "pieza.png").write_bytes(datos)
    shutil.copy(lectura, d / ".lectura.json")
    _escribe(d / "canva.json", {"schema": 1, "design_id": design, "edit_url": edit, "base": (meta.get("canva") or {}).get("base"),
                                "elementos": elementos, "export": {"tipo": "png", "host": host, "ruta": urlparse(a.export_url).path,
                                                                   "sha256": hashlib.sha256(datos).hexdigest(), "blob_sha": blob_sha(datos),
                                                                   "bytes": len(datos), "medidas": medidas},
                                "importado_el": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    meta.setdefault("canva", {})["design_id"] = design
    if meta.get("ronda"):
        meta["ronda"]["canva_importado"] = True
    _escribe(d / "pieza.json", meta)
    (d / ".revisado").unlink(missing_ok=True)
    print(f"✓ Exportación de Canva guardada tal cual ({len(datos) // 1024} KB, {medidas[0]}x{medidas[1]}, sha256 {hashlib.sha256(datos).hexdigest()[:12]}). Sigue con 'revisar'.")


def revisar(a, d: Path, huella) -> None:
    (d / ".revisado").unlink(missing_ok=True)
    meta = _lee(d / "pieza.json")
    for f in ("pieza.png", "canva.json", ".lectura.json"):
        if not (d / f).exists():
            die("Falta la exportación de Canva: corre 'canva-importar' primero.")
    marca = Path(a.marca)
    sys.path.insert(0, str(marca / "verificador"))
    try:
        from verificar_canva import verificar_canva  # type: ignore
        from verificar import imprime  # type: ignore
    except ImportError:
        die(f"El repo de marca ({marca}) no tiene verificador/verificar_canva.py: no se puede revisar una pieza de Canva. Termina y explícalo.")
    png = (d / "pieza.png").read_bytes()
    canva = _lee(d / "canva.json")
    if canva.get("export", {}).get("sha256") != hashlib.sha256(png).hexdigest():
        die("pieza.png no es la exportación que registró canva-importar.")
    res = verificar_canva(png, (d / ".lectura.json").read_text(encoding="utf-8"), marca, _lee(d / "copia.json"), canva, meta["formato"],
                          ronda=bool(meta.get("ronda")))
    imprime(res)
    res["png_blob_sha"] = blob_sha(png)
    res["png_sha1"] = hashlib.sha1(png).hexdigest()
    res["formato_pedido"] = meta["formato"]
    res["canva_design_id"] = canva.get("design_id")
    _escribe(d / "informe.json", res)
    if res.get("formato") != meta["formato"]:
        die(f"La exportación salió como {res.get('formato')}, no como {meta['formato']}: exporta con el ancho y alto del formato.")
    if not res["aprobada"]:
        die("El Verificador rechazó la pieza (arriba los bloqueos). Corrige los textos en el MISMO diseño, guarda, relee, exporta y vuelve a importar.")
    (d / ".revisado").write_text(huella(d))
    print(f"\n✓ {a.campana}/{a.pieza} (Canva {canva.get('design_id')}) revisada. Mira {d / 'pieza.png'} antes de abrir el PR.")


def para_subir(d: Path) -> dict[str, bytes]:
    return {n: (d / n).read_bytes() for n in SUBE if (d / n).exists()}


def cuerpo_pr(d: Path) -> str:
    c = _lee(d / "canva.json")
    return f"\n\nHecha en Canva: diseño editable {c.get('edit_url')} (copia de la base aprobada {c.get('base', {}).get('id')}). " \
           "pieza.png es la exportación original de Canva."


def revisar_pr(a, d: Path, pref: str, repo: str, pr: dict, huella, claves_copia) -> bool:
    """Ronda de una pieza de Canva. False si la pieza del PR no es de Canva (sigue el camino HTML). Dos pasos:
    1) rearma la pieza desde la rama del PR, aplica --cambios a copia.json e indica qué textos cambiar en el MISMO diseño;
    2) después de canva-importar, revisa y hace UN commit en la misma rama (mismo PR)."""
    head = pr["head"]["sha"]
    previa = (_lee(d / "pieza.json").get("ronda") or {}) if (d / "pieza.json").exists() else {}
    misma = previa.get("pr") == a.pr and previa.get("head") == head and previa.get("foto") == a.foto_ronda
    if misma and not es_canva(d):
        return False  # reintento de una ronda HTML: sigue su camino de siempre
    if not misma:
        archivos = lee_carpeta(repo=repo, ref=head, pref=pref, ua=UA)
        meta = json.loads(archivos.get("pieza.json", b"{}"))
        if meta.get("fuente") != "canva":
            return False
        if not set(SUBE) <= set(archivos):
            die(f"La rama del PR no trae la pieza de Canva completa en {pref}.")
        if meta.get("campana") != a.campana or meta.get("pieza") != a.pieza:
            die("pieza.json de la rama es de otra pieza.")
        canva = json.loads(archivos["canva.json"])
        if not DISENO.match(str(canva.get("design_id", ""))) or canva["design_id"] != (meta.get("canva") or {}).get("design_id"):
            die("canva.json y pieza.json de la rama no son del mismo diseño.")
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        for k in SUBE:
            (d / k).write_bytes(archivos[k])
        (d / ".copia_original.json").write_bytes(archivos["copia.json"])
        meta["ronda"] = {"pr": a.pr, "rama": pr["head"]["ref"], "head": head, "foto": a.foto_ronda,
                         "export_antes": canva.get("export", {}).get("sha256"), "canva_importado": False}
        _escribe(d / "pieza.json", meta)
        print(f"· Pieza de Canva rearmada desde {pr['head']['ref']} ({head[:7]}).")
    if a.foto_ronda != "Igual":
        die("Una pieza de Canva no lleva foto: la ronda va con Foto en la ronda = Igual.")
    cambios = _lee(Path(a.cambios)) if a.cambios else {}
    if not isinstance(cambios, dict) or [k for k in cambios if k not in claves_copia]:
        die(f"--cambios lleva solo claves de copia ({', '.join(claves_copia)}).")
    _escribe(d / "copia.json", {**_lee(d / ".copia_original.json"), **cambios})
    meta = _lee(d / "pieza.json")
    canva = _lee(d / "canva.json")
    if not meta["ronda"].get("canva_importado"):
        el = canva.get("elementos") or {}
        print(json.dumps({"pendiente": "canva", "design_id": canva["design_id"], "edit_url": canva.get("edit_url"),
                          "cambiar": {k: {"locator": el.get(k), "texto": v} for k, v in cambios.items()}}, ensure_ascii=False))
        print(f"→ En Canva, sobre el MISMO diseño {canva['design_id']} (no copies otro): read-design open_transaction=true, edit-design solo con "
              "replace_text de esos elementos, finalize=commit, read-design con open_transaction=true (nueva; guárdalo en lectura.json y ciérrala con finalize=cancel) y export-design png. "
              f"Luego: pp canva-importar --design {canva['design_id']} --edit-url {canva.get('edit_url')} ... y repite este mismo revisar-pr.")
        return True
    revisar(a, d, huella)
    if (d / ".revisado").read_text() != huella(d):
        die("La pieza cambió después de revisar.")
    titulo = (a.titulo or "cambios pedidos").strip()
    r = commit_en_rama(repo=repo, pref=pref, locales=para_subir(d), rama=meta["ronda"]["rama"], head=meta["ronda"]["head"], ua=UA,
                       mensaje=f"Ronda {a.campana}/{a.pieza} ({meta['formato']}, Canva {canva['design_id']}): {titulo}")
    inf = _lee(d / "informe.json")
    print(json.dumps({"pr_url": pr.get("html_url"), "pr_numero": a.pr, "rama": r["rama"], "commit": r["commit"], "campana": a.campana,
                      "pieza": a.pieza, "formato": meta["formato"], "foto": False, "ronda": True, "foto_ronda": a.foto_ronda,
                      "canva_design_id": canva["design_id"], "png_blob_sha": inf["png_blob_sha"], "archivos": r["archivos"]}, ensure_ascii=False))
    return True
