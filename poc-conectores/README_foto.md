# Prueba de factibilidad 4b · Foto de Higgsfield en la pieza

Contesta: ¿el Creativo puede hacer una pieza completa con una foto generada en Higgsfield, siguiendo la plantilla con foto y las reglas de fotografía del repo, y entregarla a un borrador de Netlify con su prompt guardado, de modo que el Verificador la apruebe?

Se cobra **una imagen** de tu saldo de la API de Higgsfield (anótalo antes y después).

## Antes de correrla (unos 10 minutos)

1. **Sube el repo 0.3.0** (`5cero5-marca-0.3.0.zip`). Cambian: `VERSION`, `tokens.json`, `reglas.md`, `README.md`, `CAMBIOS.md`, `verificador/` (verificar.py, probar.py, README.md) y son nuevos `plantillas/post-4x5-foto.html` y `fotos/README.md`.
2. **Netlify**: el token de la prueba 6. Si ya regresaste el proyecto a Private, vuelve a ponerlo en Public solo para previews mientras corres la prueba.
3. **Dominio de los archivos de Higgsfield** (`HF_FILES_HOST`): el agente necesita descargar la imagen terminada. La prueba 3 lo imprimió como "dominio que sirve los archivos". Si no lo tienes a la mano, desde `poc-conectores`:
   `grep -oh 'https://[^/"\\]*' bitacora/higgsfield-api-*.jsonl | sort -u` (busca el que parezca de imágenes, no api.higgsfield.ai).
4. Variables: las de las pruebas 3, 5 y 6 (`ANTHROPIC_API_KEY`, `NETLIFY_TOKEN`, `NETLIFY_SITE_ID`, `HF_API_KEY`, `GH_TOKEN`, `GH_REPO_URL`) y `export HF_FILES_HOST=...`.

## Correrla

```bash
uv run --with "anthropic>=1.9" --with httpx --with pillow python prueba_foto.py --dry-run   # no crea ni cobra
uv run --with "anthropic>=1.9" --with httpx --with pillow python prueba_foto.py
```

## Qué cuenta como "pasó"

- Netlify: deploy listo, borrador, el publicado no cambió, y el SHA1 de cada archivo bajado coincide con el que Netlify registró (pieza.png, pieza.html, copia.json, prompt.txt y la foto).
- Higgsfield: la solicitud existe y está `completed`, y la foto del borrador es exactamente el archivo que Higgsfield sirve (mismo SHA1).
- Una sola solicitud de generación (si hay más, avisa que pudo cobrarse más).
- El Verificador v0.3.0 aprueba la pieza con su prompt.
- Control negativo: sin prompt y con promesa, la rechaza.

Lo que el script NO puede juzgar: si la foto parece una pyme real de Monterrey, sin gente de banco, sin letras ni logos visibles. Eso lo ves tú en `salidas/foto-<fecha>/pieza.png`. Dime qué opinas: es la prueba de si Higgsfield da fotos con el tono de la marca.

## Si algo falla

- Que no pase es un resultado válido. Para volver a verificar un deploy sin otra sesión (ni otro cobro): `... prueba_foto.py --revisar-deploy ID`.
- Si el agente no puede descargar la imagen, casi seguro `HF_FILES_HOST` está mal: el script imprime los comandos y el error.
- Limpieza: `... prueba_foto.py --limpiar`.
