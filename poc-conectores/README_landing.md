# Landing: de la terminal a producción (puntos 1 y 2)

Necesitas: `uv` (el mismo de las pruebas anteriores), el repo `5cero5-marca` v0.5.0 descomprimido y las variables NETLIFY_TOKEN y NETLIFY_SITE_ID (el sitio poc505). No hace falta instalar Python ni las herramientas de Apple: uv trae su propio Python.

```
# una sola vez: baja el Chromium que usa el Verificador (sin admin, va a ~/Library/Caches/ms-playwright)
uv run --with playwright playwright install chromium

export NETLIFY_TOKEN="..."
export NETLIFY_SITE_ID="..."
export MARCA_REPO="$PWD/5cero5-marca"
alias landing='uv run --with httpx --with pillow --with playwright python landing.py'

landing construir     # arma el sitio: lo que había en la raíz + la landing en /landingtest; lo revisa y guarda el manifiesto
                      # otra ruta: landing construir --ruta otra-ruta · sin conservar la raíz: --base-deploy ninguno
landing borrador      # sube a Netlify como BORRADOR y compara SHA1 contra el manifiesto
# abre la URL del borrador en /landingtest/ y la raíz, y míralas en el teléfono
landing promover --deploy <ID> --acepto-aviso-provisional
landing revertir      # si algo sale mal
```

Prueba local contra un Netlify falso: `uv run --with httpx --with pillow --with playwright python test_landing.py`

Qué impide el script: promover un deploy que él no subió; promover si la carpeta cambió o Netlify guarda otros bytes; publicar con el aviso provisional sin tu bandera explícita; publicar sin escribir la frase `PUBLICAR <8 primeros del id>`. Después de publicar compara lo que sirve la URL pública contra el manifiesto.

Probado: 14 comprobaciones contra un Netlify FALSO (`test_landing.py`). NO probado contra Netlify real: (1) que el API acepte publicar un borrador con /restore, (2) que Netlify Forms detecte el formulario en un deploy por API y reciba envíos desde un borrador, (3) el redirect a /gracias.html.
Si (1) falla, el script lo dirá y la salida es "Publish deploy" en la interfaz de Netlify.

Esta publicación es la primera de la landing: el comando `promover` es la aprobación de Al o Bonzo.


## Ruta propia y noindex (v0.5.0)

Un deploy de Netlify es el sitio completo. Para que la landing viva en /landingtest sin borrar la raíz, `construir` baja los archivos del deploy que estaba publicado antes de la primera promoción (el "sitio base") y acepta cada uno solo si su SHA1 coincide con el que Netlify registró. Si la lista de Netlify omite archivos en subcarpetas, también sigue los enlaces de los HTML y CSS del sitio base. Todo el sitio sale con noindex: cabecera `X-Robots-Tag` en `_headers` y un `robots.txt` que bloquea todo.

Después de publicar, los HTML se verifican por una marca del build (Netlify puede reescribirlos al servirlos) y lo demás byte por byte.

No probado contra Netlify real: bajar archivos con `Accept: application/vnd.bitballoon.v1.raw` (si falla, usa la URL fija del deploy y también exige el SHA1), y que Netlify aplique `_headers` en un deploy por API (el script lo revisa al publicar y avisa si no llega la cabecera).


## Formulario → HighLevel (v0.8.0)

El formulario envía a la función `prospecto` (se sube junto con la landing). La función registra en HighLevel por API: contacto, UTM, primer toque, aviso aceptado, tags `prospecto` y `discovery-pendiente`, y una oportunidad en "Ventas 5cero5 / Prospecto nuevo". Si HighLevel falla, el prospecto ve "No se pudo enviar" (no se finge que llegó) y el error queda en Netlify > Logs > Functions.

Antes del borrador, en Netlify (poc505 > Site configuration > Environment variables), con alcance Functions y marcadas como secretas:
- `HL_TOKEN`: token de integración privada de la subcuenta 5cero5 con permisos de contactos (leer y escribir), oportunidades (leer y escribir) y campos personalizados (leer).
- `HL_LOCATION_ID`: Location ID de la subcuenta.
Las variables se leen al desplegar: si las cambias, vuelve a correr `borrador` y `promover`.

`landing borrador` y `landing promover` llaman a la función con `?verificar=1` (no crea nada) y dicen si falta algo.

Después de enviar el formulario, en tu Terminal (con las mismas dos variables):
```
export HL_TOKEN="..." HL_LOCATION_ID="..."
landing lead --email tu-correo@ejemplo.com --campana e2e
```

## La raíz se conserva (4 oct 2026)

Regla: mkt.5cero5.com/ se queda como está (deploy original 6ab9e4bf33abe600082e4939); solo se edita /landingtest.

1. Netlify > poc505 > Deploys > el deploy 6ab9e4bf… > menú (…) > Download deploy. Descomprime la descarga.
2. `landing construir --base-dir /ruta/a/la/descarga` — cada archivo se compara con el SHA1 que Netlify registró para ese deploy; si uno no coincide o falta, se detiene.
3. Con sitio base, el noindex aplica solo a /landingtest (cabecera en `_headers`) y no se escribe robots.txt: la raíz no cambia.

`construir` sin `--base-dir` se niega a reemplazar la raíz, y `promover` no publica un borrador que no la conserve (salvo `--reemplazar-raiz`, decisión explícita).
