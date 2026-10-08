# Prueba de factibilidad 6 · Salida a Netlify + Verificador

Contesta dos preguntas: ¿el Creativo puede entregar su pieza byte por byte a un deploy en borrador de Netlify?, y ¿un Verificador que corre fuera del agente puede revisar esa pieza, tal como quedó en Netlify, y aprobarla o rechazarla?

## Antes de correrla (unos 5 minutos)

1. **Sube el repo 0.2.0.** Descomprime `5cero5-marca-0.2.0.zip` y sube al repo de GitHub los cambios (la carpeta nueva `verificador/` y los archivos que cambiaron: `VERSION`, `tokens.json`, `reglas.md`, `README.md`, `CAMBIOS.md`). La prueba baja el Verificador del repo, no de tu disco.
2. **Llena `verificador/bloqueos.json`** con los competidores y las otras empresas del fundador, si quieres que esa revisión detecte algo. Si lo dejas vacío, la prueba corre y el informe trae un aviso.
3. **Variables.** Las de la prueba 2 (`NETLIFY_TOKEN`, `NETLIFY_SITE_ID`) y las de la prueba 5 (`GH_TOKEN`, `GH_REPO_URL`), más `ANTHROPIC_API_KEY`. Deja en la misma carpeta `prueba_netlify.py`, `prueba_repo.py` y `prueba_render.py`.

## Correrla

```bash
uv run --with "anthropic>=1.9" --with httpx --with pillow python prueba_salida.py --dry-run   # no crea nada
uv run --with "anthropic>=1.9" --with httpx --with pillow python prueba_salida.py
```

## Qué cuenta como "pasó"

El script revisa en Netlify y en los archivos, no en lo que dijo el agente:

- El deploy existe, está `ready`, es borrador y el deploy publicado del sitio no cambió.
- Baja `pieza.png`, `pieza.html` y `copia.json` de la URL del borrador. El SHA1 del PNG coincide con el que dijo el agente y con el que Netlify registró (así se sabe que el archivo llegó igual, no una copia aproximada).
- El Verificador del repo corre sobre lo bajado y aprueba esta pieza. El informe queda en `salidas/salida-<fecha>/verificacion.json`.
- Control negativo: el mismo Verificador rechaza una copia con "¡Garantizamos 300% más clientes!" por promesa, porcentaje y exclamación.

Esperado: un aviso por el titular de 3 palabras (la regla dice 4 a 12, el ejemplo oficial tiene 3) y, si no llenaste `bloqueos.json`, otro por la lista vacía. No detienen.

## Si algo falla

- Si el borrador no se puede abrir (Netlify pide contraseña o login en las vistas previas): el script lo dice. Se revisa la protección del sitio de prueba.
- Para volver a verificar un deploy sin gastar otra sesión: `... prueba_salida.py --revisar-deploy ID_DEL_DEPLOY` (sin comparar contra lo que dijo el agente).
- Que no pase es un resultado válido. El script imprime qué revisión falló.

## Qué crea en Anthropic

| Recurso | Nombre | Para qué |
|---|---|---|
| Entorno | `poc-5cero5-salida` | Red solo a api.netlify.com; el repo lo monta la plataforma |
| Credencial | `Netlify · equipo agentes · salida` en el vault `5cero5` | El token llega como $NETLIFY_TOKEN y solo sale hacia api.netlify.com |
| Agente | `5cero5 · Creativo (prueba salida)` | Hace la pieza y la sube al borrador |

Los IDs quedan en `.estado_salida.json`. Para archivar todo: `... prueba_salida.py --limpiar`. Los borradores de Netlify no se borran solos.
