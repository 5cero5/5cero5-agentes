#!/usr/bin/env python3
"""Prueba de la ruta Canva de pr_pieza.py (pieza_canva.py) contra el GitHub FALSO de test_pr_pieza.py, una exportación de Canva
FALSA (servidor local) y una copia del repo de marca con canva/recursos.json habilitado para la prueba.

  MARCA_REPO=../../5cero5-marca python3 test_pieza_canva.py

Necesita Pillow y Playwright con Chromium (la "exportación" de prueba es el render de la plantilla, como la de una base de Canva
que la replica). No llama a Canva: lo que pasa en Canva lo comprueba el harness en el log de la sesión (test/canva.test.mjs)."""
import json, os, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import test_pr_pieza as T  # GitHub falso, copia de la marca y la herramienta (no corre su main)

BASE, DIS, CARPETA, LOGO = "DAGbase0001", "DAGpieza001", "FAFcarpeta1", "MAGlogo5c05"
EXPORT = {"png": b"", "pedidos": 0}


class HExport(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        EXPORT["pedidos"] += 1
        if self.path.startswith("/redirige"):
            self.send_response(302); self.send_header("Location", "https://evil.example/x.png"); self.end_headers(); return
        b = EXPORT["png"]
        self.send_response(200); self.send_header("Content-Type", "image/png"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


srv = ThreadingHTTPServer(("127.0.0.1", 0), HExport); threading.Thread(target=srv.serve_forever, daemon=True).start()
URL_EXP = f"http://127.0.0.1:{srv.server_address[1]}"
ENV = {**T.ENV, "CANVA_EXPORT_PRUEBA": "1", "CANVA_EXPORT_HOSTS": "127.0.0.1"}
LOC = {"kicker": "PB-LB1", "titular": "PB-LB2", "subtitulo": "PB-LB3", "nota": "PB-LB4"}
EDIT = f"https://www.canva.com/design/{DIS}/edit"


def recursos(habilitado=True):
    p = T.MARCA_COPIA / "canva" / "recursos.json"
    r = json.loads(p.read_text(encoding="utf-8"))
    r.update(habilitado=habilitado, carpeta_id=CARPETA, logo_asset_id=LOGO)
    r["formatos"]["post-4x5"]["base"] = {"tipo": "design", "id": BASE}
    p.write_text(json.dumps(r, ensure_ascii=False))
    return r


def lectura(copia, ruta, extra=None):
    els = [{"locator_id": LOC[k], "type": "text", "text": "\n".join(v) if isinstance(v, list) else v} for k, v in copia.items()]
    els += [{"locator_id": f"PB-LB9{i}", "type": "text", "text": t} for i, t in enumerate(extra or [])]
    els.append({"locator_id": "PB-LB5", "type": "image", "asset_id": LOGO})
    ruta.write_text(json.dumps({"design_content": {"pages": [{"page_id": "PB", "elements": els}]}}, ensure_ascii=False))
    return ruta


def corre(*args):
    r = subprocess.run(T.TOOL + list(args), capture_output=True, text=True, env=ENV, timeout=300)
    return r.returncode, r.stdout + r.stderr


def importa(c, p, design=DIS, edit=EDIT, url=None, lect=None, el=None):
    return corre("canva-importar", "--campana", c, "--pieza", p, "--design", design, "--edit-url", edit, "--export-url", url or f"{URL_EXP}/exp.png",
                 "--lectura", str(lect), "--elementos", json.dumps(el or LOC))


def main():
    check = T.check
    if not (T.MARCA_COPIA / "verificador" / "verificar_canva.py").exists():
        sys.exit(f"El repo de marca {T.MARCA} no tiene verificador/verificar_canva.py.")
    # La "exportación" de prueba: el render aprobado de la plantilla post-4x5 con la copia BIEN.
    rc, o = corre("nueva", "--campana", "ref", "--pieza", "html", "--formato", "post-4x5")
    T.copia("ref", "html", T.BIEN); corre("llenar", "--campana", "ref", "--pieza", "html")
    rc, o = corre("revisar", "--campana", "ref", "--pieza", "html")
    if rc != 0:
        sys.exit("No se pudo armar la exportación de prueba:\n" + o[-1500:])
    EXPORT["png"] = (T.dir_("ref", "html") / "pieza.png").read_bytes()
    lect = T.TMP / "lectura.json"

    # Recursos deshabilitados: no se empieza.
    recursos(False)
    rc, o = corre("nueva", "--campana", "poc", "--pieza", "canva-x", "--formato", "post-4x5", "--canva")
    check("canva: recursos.json sin habilitar → no crea la pieza", rc != 0 and "no está habilitado" in o and not T.dir_("poc", "canva-x").exists(), o)
    recursos(True)
    rc, o = corre("nueva", "--campana", "poc", "--pieza", "canva-f", "--formato", "post-4x5", "--canva", "--foto")
    check("canva: con foto todavía no (falla cerrado sin pedir nada)", rc != 0 and "con foto" in o, o)

    # Camino bueno.
    rc, o = corre("nueva", "--campana", "poc", "--pieza", "canva-a", "--formato", "post-4x5", "--canva")
    d = T.dir_("poc", "canva-a")
    meta = json.loads((d / "pieza.json").read_text())
    check("canva nueva: pieza.json fuente canva con la base aprobada y sin plantilla HTML",
          rc == 0 and meta["fuente"] == "canva" and meta["canva"]["base"] == {"tipo": "design", "id": BASE} and not (d / "plantillas").exists()
          and BASE in o and "KICKER DE MUESTRA" in o and CARPETA in o, o)
    T.copia("poc", "canva-a", T.BIEN)
    rc, o = importa("poc", "canva-a", url="https://evil.example/exp.png", lect=lectura(T.BIEN, lect))
    check("canva-importar: una URL fuera de los hosts de Canva no se baja", rc != 0 and "no está entre los hosts" in o and not (d / "pieza.png").exists(), o)
    n = EXPORT["pedidos"]
    rc, o = importa("poc", "canva-a", url=f"{URL_EXP}/redirige", lect=lectura(T.BIEN, lect))
    check("canva-importar: no sigue redirecciones", rc != 0 and "redirección" in o and not (d / "pieza.png").exists() and EXPORT["pedidos"] == n + 1, o)
    rc, o = importa("poc", "canva-a", edit="https://www.canva.com/design/DAGotro0001/edit", lect=lectura(T.BIEN, lect))
    check("canva-importar: el enlace de edición tiene que ser de ese diseño", rc != 0 and "--edit-url" in o, o)
    rc, o = importa("poc", "canva-a", el={"kicker": "PB-LB1"}, lect=lectura(T.BIEN, lect))
    check("canva-importar: cada texto con copia necesita su elemento", rc != 0 and "titular, subtitulo, nota" in o, o)
    rc, o = importa("poc", "canva-a", lect=lectura(T.BIEN, lect))
    canva = json.loads((d / "canva.json").read_text()) if (d / "canva.json").exists() else {}
    check("canva-importar: pieza.png es la exportación tal cual y canva.json la registra (sha256, diseño, enlace, elementos)",
          rc == 0 and (d / "pieza.png").read_bytes() == EXPORT["png"] and canva.get("design_id") == DIS and canva.get("edit_url") == EDIT
          and canva["export"]["sha256"] == __import__("hashlib").sha256(EXPORT["png"]).hexdigest() and canva["elementos"] == LOC, o)
    rc, o = importa("poc", "canva-a", design="DAGotro0001", edit="https://www.canva.com/design/DAGotro0001/edit", lect=lectura(T.BIEN, lect))
    check("canva-importar: una pieza = un diseño (otro design_id se rechaza)", rc != 0 and "una pieza = un diseño" in o, o)
    # Relectura con un texto de la base que quedó: el Verificador la rechaza y no se puede abrir PR.
    lectura(T.BIEN, d / ".lectura.json", extra=["TITULAR DE MUESTRA"])
    rc, o = corre("revisar", "--campana", "poc", "--pieza", "canva-a")
    rc2, o2 = corre("abrir", "--campana", "poc", "--pieza", "canva-a", "--titulo", "x")
    check("canva revisar: texto extra en el diseño → rechazada y abrir se niega", rc != 0 and "sin_texto_extra" in o and rc2 != 0 and not T.G.prs, o + o2)
    lectura(T.BIEN, d / ".lectura.json")
    rc, o = corre("revisar", "--campana", "poc", "--pieza", "canva-a")
    inf = json.loads((d / "informe.json").read_text())
    check("canva revisar: verificar_canva aprueba, sin HTML y con el PNG de la exportación", rc == 0 and inf["aprobada"] and inf["fuente"] == "canva"
          and inf["verificador"] == "verificar_canva" and inf["formato"] == "post-4x5" and not (d / "pieza.html").exists(), o)
    rc, o = corre("abrir", "--campana", "poc", "--pieza", "canva-a", "--titulo", "Post Canva")
    out = json.loads(o.strip().splitlines()[-1]) if rc == 0 else {}
    pr = T.G.prs[-1] if T.G.prs else {}
    check("canva abrir: un PR con exactamente pieza.png, canva.json, copia.json, pieza.json e informe.json (sin pieza.html)",
          rc == 0 and sorted(out.get("archivos", [])) == sorted(f"piezas/poc/canva-a/{k}" for k in ("pieza.png", "canva.json", "copia.json", "pieza.json", "informe.json")), o)
    check("canva abrir: el cuerpo del PR lleva el enlace editable de Canva", EDIT in pr.get("body", "") and "exportación original" in pr.get("body", ""), pr.get("body", ""))

    # Ronda Igual: mismo diseño y mismo PR, en dos pasos.
    num, rama = out.get("pr_numero"), out.get("rama")
    head0 = T.G.refs["refs/heads/" + rama]
    cambios = T.TMP / "cambios.json"; cambios.write_text(json.dumps({"subtitulo": "Un solo equipo coordina tus citas y pedidos."}, ensure_ascii=False))
    rc, o = corre("revisar-pr", "--campana", "poc", "--pieza", "canva-a", "--pr", str(num), "--foto-ronda", "Editar", "--cambios", str(cambios))
    check("ronda canva: Editar no aplica (la pieza no lleva foto)", rc != 0 and "Igual" in o and T.G.refs["refs/heads/" + rama] == head0, o)
    rc, o = corre("revisar-pr", "--campana", "poc", "--pieza", "canva-a", "--pr", str(num), "--foto-ronda", "Igual", "--cambios", str(cambios))
    check("ronda canva paso 1: rearma desde la rama, dice qué texto cambiar en el MISMO diseño y no hace commit",
          rc == 0 and '"pendiente": "canva"' in o and DIS in o and "PB-LB3" in o and T.G.refs["refs/heads/" + rama] == head0, o)
    nueva_copia = {**T.BIEN, "subtitulo": "Un solo equipo coordina tus citas y pedidos."}
    rc, o = importa("poc", "canva-a", design="DAGotro0001", edit="https://www.canva.com/design/DAGotro0001/edit", lect=lectura(nueva_copia, lect))
    check("ronda canva: importar otro diseño se rechaza", rc != 0 and "una pieza = un diseño" in o, o)
    rc, o = importa("poc", "canva-a", lect=lectura(nueva_copia, lect))
    rc2, o2 = corre("revisar-pr", "--campana", "poc", "--pieza", "canva-a", "--pr", str(num), "--foto-ronda", "Igual", "--cambios", str(cambios))
    r2 = json.loads(o2.strip().splitlines()[-1]) if rc2 == 0 else {}
    head1 = T.G.refs["refs/heads/" + rama]
    check("ronda canva paso 2: un commit nuevo en la misma rama, mismo PR y mismo diseño; no abre otro PR",
          rc == 0 and rc2 == 0 and r2.get("pr_numero") == num and r2.get("canva_design_id") == DIS and head1 != head0
          and T.G.commits[head1]["parents"] == [head0] and len(T.G.prs) == 1, o + o2)
    copia_rama = json.loads(T.G.blobs[next(e["sha"] for e in T.G.trees[T.G.commits[head1]["tree"]] if e["path"] == "piezas/poc/canva-a/copia.json")])
    check("ronda canva: solo cambió la clave pedida de la copia", copia_rama == nueva_copia, copia_rama)

    srv.shutdown()
    print(f"\n{sum(T.res)}/{len(T.res)} comprobaciones correctas.")
    sys.exit(0 if all(T.res) else 1)


if __name__ == "__main__":
    main()
