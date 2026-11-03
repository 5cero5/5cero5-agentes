#!/usr/bin/env python3
"""Prueba de rotar_llave_higgsfield.py con un SDK de Anthropic FALSO, sobre una copia temporal de infra/ (no toca los
estado-*.json reales ni la red). Comprueba que solo actualiza la credencial del cliente, con su red en api.higgsfield.ai,
y que se detiene sin llamar a la API si la llave nueva es igual a la anterior, no coincide o el vault no es el suyo.

  python3 test_rotar.py"""
import contextlib, importlib.util, io, json, shutil, sys, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
tmp = Path(tempfile.mkdtemp()) / "infra"
shutil.copytree(HERE, tmp, ignore=shutil.ignore_patterns("estado-*.json", "__pycache__", "test_*.py"))
for nombre, d in {"opticas-del-rosario-creativo": {"vault_id": "vlt_O", "cred_github_id": "vcrd_G", "cred_higgsfield_id": "vcrd_H"},
                  "creativo": {"vault_id": "vlt_5", "cred_higgsfield_id": "vcrd_5"},
                  "otro-creativo": {"vault_id": "vlt_X", "cred_higgsfield_id": "vcrd_X"},
                  "entorno": {"environment_id": "env_1"}}.items():
    (tmp / f"estado-{nombre}.json").write_text(json.dumps(d))
sys.path.insert(0, str(tmp))
spec = importlib.util.spec_from_file_location("rotar", tmp / "rotar_llave_higgsfield.py")
rotar_mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(rotar_mod)

NUEVA, ANTERIOR = "id_nuevo:secreto_nuevo_123", "id_viejo:secreto_viejo_456"
T0 = datetime(2026, 11, 3, tzinfo=timezone.utc)


class O:
    def __init__(self, **kw): self.__dict__.update(kw)


class Falso:
    """Anthropic().beta mínimo: vaults.retrieve, vaults.credentials.{retrieve,update}. Registra cada llamada."""
    def __init__(self, meta=None, secret_name="HIGGSFIELD_API_KEY", archivada=False):
        self.llamadas, falso = [], self
        self.cred = O(id="vcrd_H", vault_id="vlt_O", archived_at="x" if archivada else None, updated_at=T0,
                      auth=O(secret_name=secret_name, networking=O(type="limited", allowed_hosts=["api.higgsfield.ai"])))

        class Creds:
            def retrieve(self, cid, vault_id): falso.llamadas.append(("cred.retrieve", cid, vault_id)); return falso.cred
            def update(self, cid, vault_id, auth):
                falso.llamadas.append(("cred.update", cid, vault_id, auth))
                falso.cred = O(**{**falso.cred.__dict__, "updated_at": falso.cred.updated_at + timedelta(seconds=5),
                                  "auth": O(secret_name=falso.cred.auth.secret_name,
                                            networking=O(type="limited", allowed_hosts=auth["networking"]["allowed_hosts"]))})
            def create(self, *a, **k): falso.llamadas.append(("cred.create",)); raise AssertionError("no debe crear")

        class Vaults:
            credentials = Creds()
            def retrieve(self, vid): falso.llamadas.append(("vault.retrieve", vid)); return O(id=vid, metadata=meta if meta is not None else {"cliente": "opticas-del-rosario", "rol": "creativo"})

        self.vaults = Vaults()


res = []


def caso(nombre, ok, detalle=""):
    res.append(bool(ok)); print(("✓" if ok else "✗"), nombre, "" if ok else detalle)


def corre(b, **kw):
    args = {"slug": "opticas-del-rosario", "vault": "vlt_O", "nueva": NUEVA, "confirmacion": NUEVA, "anterior": ANTERIOR, **kw}
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            return rotar_mod.rotar(b, **args), None, out.getvalue()
    except SystemExit as e:
        return None, str(e), out.getvalue()


b = Falso()
r, err, out = corre(b)
ups = [x for x in b.llamadas if x[0] == "cred.update"]
caso("actualiza SOLO vcrd_H del vault vlt_O, con el valor nuevo", err is None and len(ups) == 1 and ups[0][1:3] == ("vcrd_H", "vlt_O")
     and ups[0][3]["secret_value"] == NUEVA and ups[0][3]["type"] == "environment_variable", f"{err} {ups}")
caso("vuelve a fijar la red en api.higgsfield.ai", ups and ups[0][3]["networking"] == {"type": "limited", "allowed_hosts": ["api.higgsfield.ai"]})
caso("relee metadatos: updated_at avanza y la red queda en api.higgsfield.ai", r and r["actualizada"] and r["red_ok"], str(r))
caso("no crea credenciales nuevas", not any(x[0] == "cred.create" for x in b.llamadas))
caso("no imprime ninguna llave", NUEVA not in out and ANTERIOR not in out and NUEVA not in json.dumps(r, default=str), out)

paran = [
    ("se detiene si la nueva es IGUAL a la anterior", {"anterior": NUEVA}, "IGUAL"),
    ("se detiene si la confirmación no coincide", {"confirmacion": NUEVA + "x"}, "no coinciden"),
    ("se detiene si la llave no es ID:secreto", {"nueva": "sinpuntos", "confirmacion": "sinpuntos"}, "formato"),
    ("no toca el vault de 5cero5 (--vault de otro)", {"vault": "vlt_5"}, "no es el vault Creativo"),
    ("no corre con el cliente 5cero5", {"slug": "5cero5", "vault": "vlt_5"}, "no toca el vault de 5cero5"),
]
for nombre, kw, texto in paran:
    b = Falso(); r, err, _ = corre(b, **kw)
    caso(nombre + " (sin ninguna llamada a la API)", err and texto in err and not b.llamadas, f"{err} {b.llamadas}")

for nombre, falso, texto in [
    ("se detiene si la metadata del vault no es de ese cliente", Falso(meta={"cliente": "otro", "rol": "creativo"}), "metadata del vault"),
    ("se detiene si la credencial no es HIGGSFIELD_API_KEY", Falso(secret_name="GITHUB_TOKEN"), "no es HIGGSFIELD_API_KEY"),
    ("se detiene si la credencial está archivada", Falso(archivada=True), "archivada"),
]:
    r, err, _ = corre(falso)
    caso(nombre + " (sin actualizar)", err and texto in err and not any(x[0] == "cred.update" for x in falso.llamadas), f"{err} {falso.llamadas}")

(tmp / "estado-otro-creativo.json").write_text(json.dumps({"vault_id": "vlt_O"}))
b = Falso(); r, err, _ = corre(b)
caso("se detiene si otro cliente aparece con el mismo vault", err and "también aparece" in err and not b.llamadas, str(err))
(tmp / "estado-otro-creativo.json").write_text(json.dumps({"vault_id": "vlt_X"}))
(tmp / "estado-opticas-del-rosario-creativo.json").write_text(json.dumps({"vault_id": "vlt_O"}))
b = Falso(); r, err, _ = corre(b)
caso("sin cred_higgsfield_id no crea otra: se detiene", err and "no se crea otra" in err and not b.llamadas, str(err))

print(f"\n{sum(res)}/{len(res)} casos")
sys.exit(0 if all(res) else 1)
